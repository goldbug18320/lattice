"""Swarm and drone control API endpoints."""
from fastapi import APIRouter, HTTPException
from models.drone import Drone, DroneUpdate, Swarm, SwarmCommand, DroneCommand, BatchTelemetry
from services.state_service import state_service
from services.swarm_service import swarm_service

router = APIRouter()


# ─── Drone Management ──────────────────────────────────────────────────────────

@router.get("/drones", summary="List all drones")
async def list_drones():
    return state_service.get_all_drones()


@router.post("/drones", summary="Register a new drone")
async def register_drone(drone: Drone):
    return state_service.register_drone(drone)


@router.get("/drones/{drone_id}", summary="Get drone details")
async def get_drone(drone_id: str):
    drone = state_service.get_drone(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail="Drone not found")
    return drone


@router.patch("/drones/{drone_id}", summary="Update drone telemetry/status")
async def update_drone(drone_id: str, update: DroneUpdate):
    result = state_service.update_drone(drone_id, update.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail="Drone not found")
    return result


@router.post("/drones/{drone_id}/command", summary="Issue command to a single drone")
async def command_drone(drone_id: str, command: DroneCommand):
    result = swarm_service.execute_drone_command(drone_id, command)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# ─── Swarm Management ──────────────────────────────────────────────────────────

@router.get("/swarms", summary="List all swarms")
async def list_swarms():
    swarms = state_service.get_all_swarms()
    result = []
    for swarm in swarms:
        drones = [state_service.get_drone(did) for did in swarm.drone_ids]
        result.append({
            **swarm.model_dump(),
            "drone_count": len(swarm.drone_ids),
            "fleet_size": swarm.total_drone_count if swarm.total_drone_count > 0 else len(swarm.drone_ids),
            "active_drones": sum(1 for d in drones if d and d.status.value not in ("offline", "idle")),
        })
    return result


@router.post("/swarms", summary="Create a new swarm")
async def create_swarm(swarm: Swarm):
    return state_service.create_swarm(swarm)


@router.get("/swarms/{swarm_id}", summary="Get swarm status")
async def get_swarm(swarm_id: str):
    swarm = state_service.get_swarm(swarm_id)
    if not swarm:
        raise HTTPException(status_code=404, detail="Swarm not found")
    drones = [state_service.get_drone(did) for did in swarm.drone_ids]
    return {**swarm.model_dump(), "drones": [d.model_dump() for d in drones if d]}


@router.post("/swarms/{swarm_id}/command", summary="Issue command to a swarm")
async def command_swarm(swarm_id: str, command: SwarmCommand):
    """
    Issue a high-level mission command to an entire swarm.
    The swarm's AI-enabled drones will self-coordinate to execute the objective.
    """
    result = swarm_service.execute_swarm_command(swarm_id, command)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.get("/log", summary="Get command log")
async def get_command_log(limit: int = 50):
    return state_service.get_command_log(limit)


@router.post("/telemetry", summary="Batch live telemetry from drones")
async def batch_telemetry(batch: BatchTelemetry):
    """
    Accept position/heading/speed/battery reports from one or more drones.
    In hardware mode each physical drone calls this directly.
    In simulation the movement service updates state internally.
    """
    updated = []
    not_found = []
    for report in batch.reports:
        updates = {
            "position": report.position,
            "heading": report.heading,
            "speed": report.speed,
        }
        if report.battery is not None:
            updates["battery"] = report.battery
        if report.status is not None:
            updates["status"] = report.status
        result = state_service.update_drone(report.drone_id, updates)
        if result:
            updated.append(report.drone_id)
        else:
            not_found.append(report.drone_id)
    return {"updated": len(updated), "not_found": not_found}
