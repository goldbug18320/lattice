from __future__ import annotations
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


class TargetType(str, Enum):
    DRONE = "drone"
    SHIP = "ship"
    TANK = "tank"
    MISSILE_LAUNCHER = "missile_launcher"
    SOLDIER_UNIT = "soldier_unit"


class TargetStatus(str, Enum):
    ACTIVE = "active"
    TRACKED = "tracked"
    ENGAGED = "engaged"
    DESTROYED = "destroyed"
    LOST = "lost"


class ThreatValue(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Position(BaseModel):
    lat: float = Field(..., description="Latitude in decimal degrees")
    lon: float = Field(..., description="Longitude in decimal degrees")
    alt: float = Field(0.0, description="Altitude in meters above sea level")


class Target(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: TargetType
    position: Position
    heading: float = Field(0.0, description="Heading in degrees (0-360)")
    speed: float = Field(0.0, description="Speed in meters per second")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Detection confidence 0-1")
    status: TargetStatus = TargetStatus.ACTIVE
    threat_value: Optional[ThreatValue] = Field(None, description="Threat classification: high/medium/low")
    reported_by: str = Field("", description="Reporting recon drone ID")
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None


class PendingApproval(BaseModel):
    """Pending human-in-the-loop attack approval request."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command_text: str = Field(..., description="Original natural language command")
    approval_prompt: str = Field(..., description="LLM-generated summary for the operator")
    threat_summary: dict = Field(default_factory=dict, description="high/medium/low counts")
    classified_targets: list[dict] = Field(default_factory=list, description="List of classified target entries")
    proposed_action: dict = Field(..., description="The assign_swarm/assign_drone action to execute on approval")
    status: Literal["pending", "approved", "denied", "expired"] = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(..., description="Approval expires at this UTC time")


class TargetUpdate(BaseModel):
    """Partial update payload for an existing target (e.g. drag-and-drop reposition)."""
    position: Optional[Position] = None
    heading: Optional[float] = None
    speed: Optional[float] = None
    confidence: Optional[float] = None
    status: Optional[TargetStatus] = None
    threat_value: Optional[ThreatValue] = None
    notes: Optional[str] = None


class TargetReport(BaseModel):
    """Single target report from a reconnaissance drone."""
    type: TargetType
    position: Position
    heading: float = 0.0
    speed: float = 0.0
    confidence: float = 1.0
    notes: Optional[str] = None
    existing_target_id: Optional[str] = Field(None, description="If updating an existing target, provide its ID")


class ReconFeed(BaseModel):
    """Batch report submitted by a recon drone."""
    recon_drone_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    targets: list[TargetReport]
