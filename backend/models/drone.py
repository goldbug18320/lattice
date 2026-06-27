from __future__ import annotations
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
import uuid
from datetime import datetime
from .target import Position


class DroneType(str, Enum):
    RECON = "recon"
    COMBAT = "combat"
    SWARM_MEMBER = "swarm_member"


class DroneModel(str, Enum):
    MQ9_RECON   = "mq9_recon"
    SCOUT_RECON = "scout_recon"
    FPV_COMBAT  = "fpv_combat"
    ALTIUS_600M = "altius_600m"


class DroneStatus(str, Enum):
    IDLE = "idle"
    PATROLLING = "patrolling"
    SEARCHING = "searching"
    TRACKING = "tracking"
    ENGAGING = "engaging"
    RETURNING = "returning"
    OFFLINE = "offline"


class SwarmStatus(str, Enum):
    IDLE = "idle"
    SEARCHING = "searching"
    TRACKING = "tracking"
    ENGAGING = "engaging"
    RETURNING = "returning"


class CommandType(str, Enum):
    LOCATE = "locate"
    TRACK = "track"
    ATTACK = "attack"
    PATROL = "patrol"
    RETURN = "return"
    ABORT = "abort"


class Drone(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: DroneType
    model: Optional[DroneModel] = None
    position: Optional[Position] = None
    home_position: Optional[Position] = None      # launch/base position for return logic
    heading: float = 0.0
    speed: float = 0.0
    altitude: float = 100.0
    status: DroneStatus = DroneStatus.IDLE
    battery: float = Field(100.0, ge=0.0, le=100.0)
    max_payload_kg: Optional[float] = None
    max_range_km: Optional[float] = None
    max_flight_time_hours: Optional[float] = None
    range_used_km: float = Field(0.0, description="Distance travelled since launch")
    current_task: Optional[str] = None
    swarm_id: Optional[str] = None
    last_update: datetime = Field(default_factory=datetime.utcnow)


class DroneUpdate(BaseModel):
    position: Optional[Position] = None
    home_position: Optional[Position] = None
    heading: Optional[float] = None
    speed: Optional[float] = None
    altitude: Optional[float] = None
    status: Optional[DroneStatus] = None
    battery: Optional[float] = None
    current_task: Optional[str] = None


class TelemetryReport(BaseModel):
    """Single drone telemetry report submitted via POST /api/swarm/telemetry."""
    drone_id: str
    position: Position
    heading: float
    speed: float
    battery: Optional[float] = None       # omit if unknown; use previous value
    status: Optional[DroneStatus] = None


class BatchTelemetry(BaseModel):
    """Batch telemetry submission from one or more drones."""
    reports: List[TelemetryReport]


class Swarm(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    drone_ids: list[str] = Field(default_factory=list)
    drone_model: Optional[DroneModel] = None
    total_drone_count: int = Field(0, description="Total fleet size (may exceed len(drone_ids) for large AI swarms)")
    status: SwarmStatus = SwarmStatus.IDLE
    objective: Optional[str] = None
    target_ids: list[str] = Field(default_factory=list)
    area_of_interest: Optional[dict] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_command: Optional[datetime] = None


class SwarmCommand(BaseModel):
    command_type: CommandType
    target_ids: list[str] = Field(default_factory=list)
    area_of_interest: Optional[dict] = Field(None)
    priority: int = Field(5, ge=1, le=10)
    objective: Optional[str] = None
    notes: Optional[str] = None


class DroneCommand(BaseModel):
    command_type: CommandType
    target_id: Optional[str] = None
    waypoint: Optional[Position] = None
    objective: Optional[str] = None
    notes: Optional[str] = None
