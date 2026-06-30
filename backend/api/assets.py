"""Assets management API — create/delete scenario assets and persist to config (Feature 17)."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models.target import Target, TargetType, ThreatValue, TargetStatus, Position
from models.drone import Drone, DroneType, DroneModel, DroneStatus, Swarm, SwarmStatus
from services.state_service import state_service
from services.config_service import assets_config

router = APIRouter()

_MODEL_TO_TYPE = {
    DroneModel.MQ9_RECON:   DroneType.RECON,
    DroneModel.SCOUT_RECON: DroneType.RECON,
    DroneModel.FPV_COMBAT:  DroneType.COMBAT,
    DroneModel.ALTIUS_600M: DroneType.COMBAT,
}

_DEFAULT_THREAT = {
    TargetType.SHIP:             ThreatValue.HIGH,
    TargetType.MISSILE_LAUNCHER: ThreatValue.HIGH,
    TargetType.TANK:             ThreatValue.MEDIUM,
    TargetType.DRONE:            ThreatValue.LOW,
    TargetType.SOLDIER_UNIT:     ThreatValue.LOW,
}

_MODEL_RANGES = {
    DroneModel.MQ9_RECON:   assets_config["mq9"]["max_range_km"],
    DroneModel.SCOUT_RECON: assets_config["scout_recon"]["max_range_km"],
    DroneModel.FPV_COMBAT:  assets_config["fpv_combat"]["max_range_km"],
    DroneModel.ALTIUS_600M: assets_config["altius_600m"]["max_range_km"],
}

_MODEL_PAYLOADS = {
    DroneModel.MQ9_RECON:   1.7,
    DroneModel.SCOUT_RECON: 0.5,
    DroneModel.FPV_COMBAT:  assets_config["fpv_combat"]["max_payload_kg"],
    DroneModel.ALTIUS_600M: assets_config["altius_600m"]["max_payload_kg"],
}

_CUSTOM_COUNTERS: dict[str, int] = {}


def _next_name(prefix: str) -> str:
    n = _CUSTOM_COUNTERS.get(prefix, 0) + 1
    _CUSTOM_COUNTERS[prefix] = n
    return f"{prefix}-{n:03d}"


class CreateDroneRequest(BaseModel):
    model: DroneModel
    position: Position
    name: Optional[str] = None


class CreateTargetRequest(BaseModel):
    type: TargetType
    position: Position


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/save-config", summary="Flush current asset positions to assets_config.json")
async def save_config():
    ok = state_service.save_config_to_file()
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to write config file")
    return {"saved": True, "path": "assets_config.json"}


@router.post("/drone", summary="Create a new drone from the Asset Palette")
async def create_drone(req: CreateDroneRequest):
    model = req.model
    dtype = _MODEL_TO_TYPE.get(model, DroneType.COMBAT)
    prefix = model.value.upper().replace("_", "-")
    name = req.name or _next_name(prefix)
    drone = Drone(
        name=name,
        type=dtype,
        model=model,
        position=req.position,
        home_position=Position(lat=req.position.lat, lon=req.position.lon, alt=0.0),
        status=DroneStatus.IDLE,
        max_range_km=_MODEL_RANGES.get(model, 100.0),
        max_payload_kg=_MODEL_PAYLOADS.get(model),
        max_flight_time_hours=assets_config["mq9"]["max_flight_time_hours"] if model == DroneModel.MQ9_RECON else None,
    )
    swarm = None
    if dtype == DroneType.COMBAT:
        swarm_prefix = "FPV-SWM" if model == DroneModel.FPV_COMBAT else "ALT-SWM"
        swarm = Swarm(
            name=_next_name(swarm_prefix),
            drone_ids=[drone.id],
            drone_model=model,
            total_drone_count=1,
            status=SwarmStatus.IDLE,
        )
        drone.swarm_id = swarm.id
        state_service.create_swarm(swarm)
    state_service.register_drone(drone)
    state_service.save_config_to_file()
    return {"drone": drone, "swarm": swarm}


@router.delete("/drone/{drone_id}", summary="Remove a drone from state and config")
async def delete_drone(drone_id: str):
    if not state_service.remove_drone(drone_id):
        raise HTTPException(status_code=404, detail="Drone not found")
    state_service.save_config_to_file()
    return {"removed": drone_id}


@router.post("/target", summary="Create a new enemy target from the Asset Palette")
async def create_target(req: CreateTargetRequest):
    threat = _DEFAULT_THREAT.get(req.type, ThreatValue.LOW)
    if req.type == TargetType.DRONE and req.position.alt > 500:
        threat = ThreatValue.MEDIUM
    target = Target(
        type=req.type,
        position=req.position,
        heading=0.0,
        speed=0.0,
        confidence=1.0,
        status=TargetStatus.ACTIVE,
        threat_value=threat,
        reported_by="manual",
        home_position=req.position,  # Feature 33: spawn position for drone 'returning' mode
    )
    state_service.upsert_target(target)
    state_service.save_config_to_file()
    return target


@router.delete("/target/{target_id}", summary="Remove a target from state and config")
async def delete_target(target_id: str):
    if not state_service.remove_target(target_id):
        raise HTTPException(status_code=404, detail="Target not found")
    state_service.save_config_to_file()
    return {"removed": target_id}
