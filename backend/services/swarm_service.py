"""Swarm command execution service."""
from __future__ import annotations
from models.drone import SwarmCommand, DroneCommand, CommandType, SwarmStatus, DroneStatus, DroneModel
from models.target import TargetStatus
from services.state_service import state_service


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

        # Reflect the mission in each target's status
        if command.command_type == CommandType.ATTACK:
            for tid in (command.target_ids or []):
                state_service.update_target_status(tid, TargetStatus.ENGAGED)
        elif command.command_type == CommandType.TRACK:
            for tid in (command.target_ids or []):
                state_service.update_target_status(tid, TargetStatus.TRACKED)

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
        # Feature 24 + 28: assign tracking target; release any drone already tracking it first
        if command.command_type == CommandType.TRACK and command.target_id:
            state_service.replace_tracker_for_target(command.target_id)  # Feature 28: release previous
            state_service.update_drone(drone_id, {"tracking_target_id": command.target_id})
            state_service.update_target_status(command.target_id, TargetStatus.TRACKED)
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


swarm_service = SwarmService()
