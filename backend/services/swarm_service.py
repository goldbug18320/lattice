"""Swarm command execution service."""
from __future__ import annotations
from models.drone import SwarmCommand, DroneCommand, CommandType, SwarmStatus, DroneStatus, DroneModel
from services.state_service import state_service


# Asset filter → which DroneModel values to include
_ASSET_FILTER_MODELS: dict[str, set[str]] = {
    "all":    {"mq9_recon", "scout_recon", "fpv_combat", "altius_600m"},
    "combat": {"fpv_combat", "altius_600m"},
    "recon":  {"mq9_recon", "scout_recon"},
    "fpv":    {"fpv_combat"},
    "altius": {"altius_600m"},
}


class SwarmService:
    def execute_swarm_command(self, swarm_id: str, command: SwarmCommand) -> dict:
        swarm = state_service.get_swarm(swarm_id)
        if not swarm:
            return {"success": False, "error": f"Swarm {swarm_id} not found"}

        status_map = {
            CommandType.LOCATE: SwarmStatus.SEARCHING,
            CommandType.TRACK: SwarmStatus.TRACKING,
            CommandType.ATTACK: SwarmStatus.ENGAGING,
            CommandType.PATROL: SwarmStatus.SEARCHING,
            CommandType.RETURN: SwarmStatus.RETURNING,
            CommandType.ABORT: SwarmStatus.IDLE,
        }
        drone_status_map = {
            CommandType.LOCATE: DroneStatus.SEARCHING,
            CommandType.TRACK: DroneStatus.TRACKING,
            CommandType.ATTACK: DroneStatus.ENGAGING,
            CommandType.PATROL: DroneStatus.PATROLLING,
            CommandType.RETURN: DroneStatus.RETURNING,
            CommandType.ABORT: DroneStatus.IDLE,
        }

        new_swarm_status = status_map.get(command.command_type, SwarmStatus.IDLE)
        new_drone_status = drone_status_map.get(command.command_type, DroneStatus.IDLE)

        state_service.update_swarm_status(swarm_id, new_swarm_status, command.objective)

        # Update swarm's target list
        swarm = state_service.get_swarm(swarm_id)
        if swarm and command.target_ids:
            swarm.target_ids = command.target_ids

        # Propagate status to individual drones (they will self-coordinate internally)
        updated_drones = 0
        for drone_id in (swarm.drone_ids if swarm else []):
            result = state_service.update_drone(drone_id, {
                "status": new_drone_status,
                "current_task": command.objective or command.command_type.value,
            })
            if result:
                updated_drones += 1

        # Log
        state_service.log_command({
            "type": "swarm_command",
            "swarm_id": swarm_id,
            "swarm_name": swarm.name if swarm else swarm_id,
            "command": command.command_type.value,
            "target_ids": command.target_ids,
            "objective": command.objective,
            "priority": command.priority,
            "drones_tasked": updated_drones,
        })

        return {
            "success": True,
            "swarm_id": swarm_id,
            "command_type": command.command_type.value,
            "drones_tasked": updated_drones,
            "objective": command.objective,
        }

    def execute_drone_command(self, drone_id: str, command: DroneCommand) -> dict:
        drone = state_service.get_drone(drone_id)
        if not drone:
            return {"success": False, "error": f"Drone {drone_id} not found"}

        status_map = {
            CommandType.LOCATE: DroneStatus.SEARCHING,
            CommandType.TRACK: DroneStatus.TRACKING,
            CommandType.ATTACK: DroneStatus.ENGAGING,
            CommandType.PATROL: DroneStatus.PATROLLING,
            CommandType.RETURN: DroneStatus.RETURNING,
            CommandType.ABORT: DroneStatus.IDLE,
        }
        new_status = status_map.get(command.command_type, DroneStatus.IDLE)
        state_service.update_drone(drone_id, {
            "status": new_status,
            "current_task": command.objective or command.command_type.value,
        })
        state_service.log_command({
            "type": "drone_command",
            "drone_id": drone_id,
            "drone_name": drone.name,
            "command": command.command_type.value,
            "target_id": command.target_id,
            "objective": command.objective,
        })
        return {
            "success": True,
            "drone_id": drone_id,
            "command_type": command.command_type.value,
            "objective": command.objective,
        }


    def execute_deploy_to_region(
        self,
        region: str,
        asset_filter: str = "all",
        objective: str | None = None,
        priority: int = 5,
    ) -> dict:
        """
        Fan out a patrol command to all swarms whose drone model matches asset_filter.
        Sets each drone's heading toward the region center so the movement simulator
        flies them there. Once inside the bounding box the movement simulator
        switches them to patrolling automatically.
        """
        from services.llm_service import GEOGRAPHIC_REGIONS
        from models.target import Position as _Pos
        import math as _math

        region_info = GEOGRAPHIC_REGIONS.get(region)
        if region_info is None:
            return {"success": False, "error": f"Unknown region: {region}"}

        allowed_models = _ASSET_FILTER_MODELS.get(asset_filter, _ASSET_FILTER_MODELS["all"])
        patrol_objective = objective or f"Patrol {region_info['display']}"
        area = region_info["bbox"]
        center = region_info["center"]
        center_pos = _Pos(lat=center["lat"], lon=center["lon"], alt=0.0)

        def _bearing_to_center(drone_pos) -> float:
            dlat = (center_pos.lat - drone_pos.lat) * 111_320
            dlon = (center_pos.lon - drone_pos.lon) * 111_320 * _math.cos(_math.radians(drone_pos.lat))
            return _math.degrees(_math.atan2(dlon, dlat)) % 360

        swarms_tasked = 0
        drones_tasked = 0
        tasked_swarm_names = []

        for swarm in state_service.get_all_swarms():
            model_val = swarm.drone_model.value if swarm.drone_model else None
            if model_val not in allowed_models:
                continue

            state_service.update_swarm_status(swarm.id, SwarmStatus.SEARCHING, patrol_objective)
            swarm_obj = state_service.get_swarm(swarm.id)
            if swarm_obj:
                swarm_obj.area_of_interest = area
                swarm_obj.target_ids = []

            for drone_id in (swarm_obj.drone_ids if swarm_obj else []):
                drone = state_service.get_drone(drone_id)
                if drone is None:
                    continue
                # Point drone toward region center
                heading = _bearing_to_center(drone.position) if drone.position else 270.0
                result = state_service.update_drone(drone_id, {
                    "status": DroneStatus.SEARCHING,
                    "heading": heading,
                    "current_task": patrol_objective,
                })
                if result:
                    drones_tasked += 1

            swarms_tasked += 1
            tasked_swarm_names.append(swarm.name)

        state_service.log_command({
            "type": "deploy_to_region",
            "region": region,
            "region_display": region_info["display"],
            "asset_filter": asset_filter,
            "objective": patrol_objective,
            "priority": priority,
            "swarms_tasked": swarms_tasked,
            "drones_tasked": drones_tasked,
        })

        return {
            "success": True,
            "region": region,
            "region_display": region_info["display"],
            "asset_filter": asset_filter,
            "swarms_tasked": swarms_tasked,
            "drones_tasked": drones_tasked,
            "swarm_names": tasked_swarm_names,
            "objective": patrol_objective,
        }


swarm_service = SwarmService()
