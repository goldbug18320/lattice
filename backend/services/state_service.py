"""In-memory state management for drones, swarms, and targets."""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta
import threading
from models.target import Target, TargetStatus, PendingApproval
from models.drone import Drone, Swarm, DroneStatus, DroneType, DroneModel, SwarmStatus

APPROVAL_TTL_MINUTES = 5


class StateService:
    def __init__(self):
        self._lock = threading.Lock()
        self._targets: dict[str, Target] = {}
        self._drones: dict[str, Drone] = {}
        self._swarms: dict[str, Swarm] = {}
        self._approvals: dict[str, PendingApproval] = {}
        self._command_log: list[dict] = []
        self._seed_demo_data()

    def _seed_demo_data(self):
        """Seed platform with Taiwan war game assets per spec."""
        from models.target import Position

        # ── 4 MQ-9 Recon Drones ────────────────────────────────────────────────
        # 2 always airborne (patrolling), 2 on standby (idle)
        mq9_configs = [
            ("MQ9-01", 25.04, 121.56, 6000.0, DroneStatus.PATROLLING),   # Taipei area
            ("MQ9-02", 23.55, 119.63, 6000.0, DroneStatus.PATROLLING),   # Taiwan Strait
            ("MQ9-03", 22.62, 120.30, 0.0,    DroneStatus.IDLE),         # Kaohsiung (standby)
            ("MQ9-04", 24.15, 120.68, 0.0,    DroneStatus.IDLE),         # Taichung (standby)
        ]
        for name, lat, lon, alt, status in mq9_configs:
            pos = Position(lat=lat, lon=lon, alt=alt)
            d = Drone(
                name=name,
                type=DroneType.RECON,
                model=DroneModel.MQ9_RECON,
                position=pos,
                home_position=Position(lat=lat, lon=lon, alt=0.0),
                status=status,
                heading=0.0,
                max_payload_kg=1.7,
                max_range_km=1900.0,
                max_flight_time_hours=27.0,
            )
            self._drones[d.id] = d

        # ── 10 FPV Combat Swarms (10,000 total FPV drones) ────────────────────
        # 60% around Taipei (6 swarms), 40% across rest of Taiwan (4 swarms)
        fpv_swarm_configs = [
            # Taipei area — 6 swarms
            ("FPV-Alpha",   25.04, 121.56),
            ("FPV-Bravo",   25.00, 121.47),
            ("FPV-Charlie", 25.13, 121.74),
            ("FPV-Delta",   24.99, 121.30),
            ("FPV-Echo",    25.08, 121.62),
            ("FPV-Foxtrot", 25.01, 121.41),
            # Rest of Taiwan — 4 swarms
            ("FPV-Golf",    24.15, 120.68),
            ("FPV-Hotel",   23.00, 120.21),
            ("FPV-India",   22.63, 120.30),
            ("FPV-Juliet",  24.80, 120.97),
        ]
        for swarm_name, base_lat, base_lon in fpv_swarm_configs:
            swarm = Swarm(
                name=swarm_name,
                drone_model=DroneModel.FPV_COMBAT,
                total_drone_count=1000,
            )
            for i in range(5):
                pos = Position(lat=base_lat + i * 0.002, lon=base_lon, alt=150.0)
                d = Drone(
                    name=f"{swarm_name}-{i+1:03d}",
                    type=DroneType.SWARM_MEMBER,
                    model=DroneModel.FPV_COMBAT,
                    position=pos,
                    home_position=Position(lat=base_lat + i * 0.002, lon=base_lon, alt=0.0),
                    swarm_id=swarm.id,
                    max_payload_kg=4.0,
                    max_range_km=15.0,
                )
                self._drones[d.id] = d
                swarm.drone_ids.append(d.id)
            self._swarms[swarm.id] = swarm

        # ── 5 Altius-600M Combat Swarms (1,000 total Altius drones) ───────────
        alt_swarm_configs = [
            ("ALT-Alpha",   25.04, 121.56),  # Taipei
            ("ALT-Bravo",   24.15, 120.68),  # Taichung
            ("ALT-Charlie", 23.00, 120.21),  # Tainan
            ("ALT-Delta",   22.63, 120.30),  # Kaohsiung
            ("ALT-Echo",    24.80, 120.97),  # Hsinchu
        ]
        for swarm_name, base_lat, base_lon in alt_swarm_configs:
            swarm = Swarm(
                name=swarm_name,
                drone_model=DroneModel.ALTIUS_600M,
                total_drone_count=200,
            )
            for i in range(5):
                pos = Position(lat=base_lat + i * 0.002, lon=base_lon, alt=200.0)
                d = Drone(
                    name=f"{swarm_name}-{i+1:03d}",
                    type=DroneType.SWARM_MEMBER,
                    model=DroneModel.ALTIUS_600M,
                    position=pos,
                    home_position=Position(lat=base_lat + i * 0.002, lon=base_lon, alt=0.0),
                    swarm_id=swarm.id,
                    max_payload_kg=12.0,
                    max_range_km=440.0,
                    max_flight_time_hours=4.0,
                )
                self._drones[d.id] = d
                swarm.drone_ids.append(d.id)
            self._swarms[swarm.id] = swarm

        # ── 100 Scout Recon Drones ─────────────────────────────────────────────
        # 60% Taipei area (6 bases × 10), 40% rest of Taiwan (4 bases × 10)
        _scout_bases = [
            (25.04, 121.56), (25.00, 121.47), (25.13, 121.74),
            (24.99, 121.30), (25.08, 121.62), (25.01, 121.41),
            (24.15, 120.68), (23.00, 120.21), (22.63, 120.30), (24.80, 120.97),
        ]
        scout_num = 1
        for base_lat, base_lon in _scout_bases:
            for i in range(10):
                offset_lat = (i % 5) * 0.01 - 0.02
                offset_lon = (i // 5) * 0.01 - 0.005
                pos = Position(lat=base_lat + offset_lat, lon=base_lon + offset_lon, alt=3000.0)
                d = Drone(
                    name=f"SCOUT-{scout_num:03d}",
                    type=DroneType.RECON,
                    model=DroneModel.SCOUT_RECON,
                    position=pos,
                    home_position=Position(lat=pos.lat, lon=pos.lon, alt=0.0),
                    status=DroneStatus.PATROLLING,
                    heading=float((scout_num * 37) % 360),
                    max_range_km=150.0,
                    max_flight_time_hours=5.0,
                )
                self._drones[d.id] = d
                scout_num += 1

        # ── Seeded Enemy Assets (representative threat baseline) ───────────────
        from models.target import TargetType, TargetStatus
        _SHIP_KTS   = 11.3   # 22 knots in m/s
        _TANK_MS    = 2.78   # 10 km/hr in m/s
        _LR_DRONE   = 41.7   # 150 km/h in m/s
        _FPV_DRONE  = 41.7   # 150 km/h in m/s
        _SOLDIER_MS = 1.39   # ~5 km/h in m/s
        _enemy_seed = [
            # Ships in Taiwan Strait — heading east toward Taiwan at 22 knots
            (TargetType.SHIP,             24.50, 119.50,    0,  90, _SHIP_KTS, 0.92),
            (TargetType.SHIP,             24.00, 119.80,    0,  85, _SHIP_KTS, 0.88),
            (TargetType.SHIP,             23.50, 119.60,    0,  95, _SHIP_KTS, 0.85),
            (TargetType.SHIP,             23.00, 119.40,    0,  80, _SHIP_KTS, 0.90),
            (TargetType.SHIP,             25.00, 119.90,    0,  88, _SHIP_KTS, 0.87),
            # Tanks on west coast Taiwan — moving inland at 10 km/hr
            (TargetType.TANK,             25.00, 120.50,    0,  90, _TANK_MS, 0.91),
            (TargetType.TANK,             24.50, 120.60,    0,  75, _TANK_MS, 0.89),
            (TargetType.TANK,             23.50, 120.30,    0, 110, _TANK_MS, 0.86),
            (TargetType.TANK,             24.00, 120.50,    0,  95, _TANK_MS, 0.83),
            # Missile launchers in Fujian — stationary (400 total, 3 representative)
            (TargetType.MISSILE_LAUNCHER, 25.90, 119.30,    0,   0,  0.0, 0.94),
            (TargetType.MISSILE_LAUNCHER, 25.00, 119.00,    0,   0,  0.0, 0.90),
            (TargetType.MISSILE_LAUNCHER, 24.50, 118.50,    0,   0,  0.0, 0.88),
            # Long-range attack drones — launched from mainland, heading east at 150 km/h
            (TargetType.DRONE,            24.50, 120.00, 3000,  90, _LR_DRONE, 0.78),
            (TargetType.DRONE,            24.00, 120.50, 2500,  88, _LR_DRONE, 0.72),
            (TargetType.DRONE,            25.00, 120.20, 3500,  85, _LR_DRONE, 0.80),
            (TargetType.DRONE,            23.50, 119.80, 2000,  92, _LR_DRONE, 0.75),
            # Enemy FPV drones — deployed by PLA soldiers, low altitude at 150 km/h
            (TargetType.DRONE,            25.00, 120.70,   50, 350, _FPV_DRONE, 0.65),
            (TargetType.DRONE,            24.50, 120.40,   30, 320, _FPV_DRONE, 0.60),
            (TargetType.DRONE,            23.80, 120.30,   40, 340, _FPV_DRONE, 0.62),
            # Soldier formations (west coast landing zones) — advancing inland ~5 km/h
            (TargetType.SOLDIER_UNIT,     25.00, 120.80,    0,  90, _SOLDIER_MS, 0.82),
            (TargetType.SOLDIER_UNIT,     24.60, 120.60,    0,  85, _SOLDIER_MS, 0.79),
            (TargetType.SOLDIER_UNIT,     24.20, 120.50,    0,  95, _SOLDIER_MS, 0.76),
            (TargetType.SOLDIER_UNIT,     23.70, 120.30,    0,  88, _SOLDIER_MS, 0.73),
        ]
        for ttype, lat, lon, alt, hdg, spd, conf in _enemy_seed:
            from models.target import ThreatValue
            if ttype in (TargetType.SHIP, TargetType.MISSILE_LAUNCHER):
                tv = ThreatValue.HIGH
            elif ttype == TargetType.TANK or (ttype == TargetType.DRONE and float(alt) > 500):
                tv = ThreatValue.MEDIUM
            else:
                tv = ThreatValue.LOW
            t = Target(
                type=ttype,
                position=Position(lat=lat, lon=lon, alt=float(alt)),
                heading=float(hdg),
                speed=float(spd),
                confidence=conf,
                status=TargetStatus.ACTIVE,
                threat_value=tv,
                reported_by="seed",
            )
            self._targets[t.id] = t

    # ─── Targets ────────────────────────────────────────────────────────────────

    def upsert_target(self, target: Target) -> Target:
        with self._lock:
            target.last_seen = datetime.utcnow()
            self._targets[target.id] = target
        return target

    def get_target(self, target_id: str) -> Optional[Target]:
        return self._targets.get(target_id)

    def get_all_targets(self, status_filter: Optional[TargetStatus] = None) -> list[Target]:
        targets = list(self._targets.values())
        if status_filter:
            targets = [t for t in targets if t.status == status_filter]
        return targets

    def mark_target_destroyed(self, target_id: str) -> bool:
        with self._lock:
            if target_id in self._targets:
                self._targets[target_id].status = TargetStatus.DESTROYED
                return True
        return False

    def remove_target(self, target_id: str) -> bool:
        with self._lock:
            if target_id in self._targets:
                del self._targets[target_id]
                return True
        return False

    # ─── Drones ─────────────────────────────────────────────────────────────────

    def register_drone(self, drone: Drone) -> Drone:
        with self._lock:
            self._drones[drone.id] = drone
        return drone

    def update_drone(self, drone_id: str, updates: dict) -> Optional[Drone]:
        with self._lock:
            if drone_id not in self._drones:
                return None
            drone = self._drones[drone_id]
            for key, value in updates.items():
                if value is not None and hasattr(drone, key):
                    setattr(drone, key, value)
            drone.last_update = datetime.utcnow()
        return drone

    def get_drone(self, drone_id: str) -> Optional[Drone]:
        return self._drones.get(drone_id)

    def get_all_drones(self) -> list[Drone]:
        return list(self._drones.values())

    # ─── Swarms ─────────────────────────────────────────────────────────────────

    def create_swarm(self, swarm: Swarm) -> Swarm:
        with self._lock:
            self._swarms[swarm.id] = swarm
        return swarm

    def get_swarm(self, swarm_id: str) -> Optional[Swarm]:
        return self._swarms.get(swarm_id)

    def get_all_swarms(self) -> list[Swarm]:
        return list(self._swarms.values())

    def update_swarm_status(self, swarm_id: str, status: SwarmStatus, objective: Optional[str] = None) -> bool:
        with self._lock:
            if swarm_id not in self._swarms:
                return False
            self._swarms[swarm_id].status = status
            if objective is not None:
                self._swarms[swarm_id].objective = objective
            self._swarms[swarm_id].last_command = datetime.utcnow()
        return True

    # ─── Approval Management ────────────────────────────────────────────────────

    def add_approval(self, approval: PendingApproval) -> PendingApproval:
        with self._lock:
            self._approvals[approval.id] = approval
        return approval

    def get_approval(self, approval_id: str) -> Optional[PendingApproval]:
        return self._approvals.get(approval_id)

    def get_pending_approvals(self) -> list[PendingApproval]:
        now = datetime.utcnow()
        return [a for a in self._approvals.values() if a.status == "pending" and a.expires_at > now]

    def decide_approval(self, approval_id: str, decision: str) -> Optional[PendingApproval]:
        """Set approval status to 'approved' or 'denied'. Returns None if not found."""
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval and approval.status == "pending":
                approval.status = decision
            return approval

    def expire_approvals(self):
        """Mark expired pending approvals. Called each tick."""
        now = datetime.utcnow()
        with self._lock:
            for approval in self._approvals.values():
                if approval.status == "pending" and approval.expires_at <= now:
                    approval.status = "expired"

    # ─── Command Log ────────────────────────────────────────────────────────────

    def log_command(self, entry: dict):
        with self._lock:
            entry["timestamp"] = datetime.utcnow().isoformat()
            self._command_log.append(entry)
            if len(self._command_log) > 200:
                self._command_log = self._command_log[-200:]

    def get_command_log(self, limit: int = 50) -> list[dict]:
        return self._command_log[-limit:]

    # ─── Full State Snapshot ────────────────────────────────────────────────────

    def get_full_state(self) -> dict:
        pending = self.get_pending_approvals()
        return {
            "targets": [t.model_dump() for t in self._targets.values()],
            "drones": [d.model_dump() for d in self._drones.values()],
            "swarms": [s.model_dump() for s in self._swarms.values()],
            "pending_approvals": [a.model_dump() for a in pending],
            "timestamp": datetime.utcnow().isoformat(),
        }


state_service = StateService()
