"""In-memory state management for drones, swarms, and targets."""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta
import threading
from models.target import Target, TargetStatus, PendingApproval
from models.drone import Drone, Swarm, DroneStatus, DroneType, DroneModel, SwarmStatus

APPROVAL_TTL_MINUTES = 5

# Feature 21 — terrain placement constraints
# Rough geographic heuristic for the Taiwan theater (not GIS-precise).
_LAND_TARGET_TYPES = {'tank', 'missile_launcher', 'soldier_unit'}
_SEA_TARGET_TYPES  = {'ship'}

def _likely_sea(lat: float, lon: float) -> bool:
    """Return True if lat/lon is probably open water in the Taiwan theater.
    Bounds match the frontend likelySea() function: Fujian coast ends ~119.4E,
    Taiwan west coast starts ~120.1E, so the open Strait is 119.4-120.1."""
    if 119.4 <= lon <= 120.1 and 22.0 <= lat <= 26.5:   # Taiwan Strait
        return True
    if lon > 122.0:                                       # Pacific east of Taiwan
        return True
    if lat < 21.5 and lon > 116.0:                        # South China Sea / Bashi Channel
        return True
    return False

def _check_terrain_constraint(ttype: str, lat: float, lon: float) -> None:
    """Log a warning if a target's position violates the land/sea constraint."""
    sea = _likely_sea(lat, lon)
    if ttype in _LAND_TARGET_TYPES and sea:
        print(f"[Feature 21] WARNING: {ttype} at ({lat:.3f},{lon:.3f}) appears to be in water")
    elif ttype in _SEA_TARGET_TYPES and not sea:
        print(f"[Feature 21] WARNING: ship at ({lat:.3f},{lon:.3f}) appears to be on land")

# City home-base coordinates (lat, lon)
# 60% Taipei area, 40% rest of Taiwan — used for scout and combat drone home positions
_TAIPEI_BASES = [
    (25.04, 121.56),   # Taipei
    (25.00, 121.47),   # New Taipei
    (25.13, 121.74),   # Keelung
    (24.99, 121.30),   # Taoyuan
]
_OTHER_BASES = [
    (24.15, 120.68),   # Taichung
    (23.00, 120.21),   # Tainan
    (22.63, 120.30),   # Kaohsiung
    (23.97, 121.60),   # Hualien
    (24.80, 120.97),   # Hsinchu
]


def _city_base(index: int, total: int, taipei_pct: float) -> tuple[float, float]:
    """Return a city (lat, lon) for the given drone index, respecting taipei_pct."""
    taipei_n = int(total * taipei_pct)
    if index < taipei_n:
        return _TAIPEI_BASES[index % len(_TAIPEI_BASES)]
    else:
        j = index - taipei_n
        return _OTHER_BASES[j % len(_OTHER_BASES)]


class StateService:
    def __init__(self):
        self._lock = threading.Lock()
        self._targets: dict[str, Target] = {}
        self._drones: dict[str, Drone] = {}
        self._swarms: dict[str, Swarm] = {}
        self._approvals: dict[str, PendingApproval] = {}
        self._command_log: list[dict] = []
        self._seed_demo_data()

    def _load_from_initial_state(self, initial_state: dict):
        """Restore drones, targets, and swarms from a saved initial_state snapshot."""
        from models.target import Position, TargetType, TargetStatus, ThreatValue

        for s_data in initial_state.get("swarms", []):
            swarm = Swarm(
                id=s_data["id"],
                name=s_data["name"],
                drone_model=DroneModel(s_data["drone_model"]) if s_data.get("drone_model") else None,
                total_drone_count=s_data.get("total_drone_count", 0),
                drone_ids=list(s_data.get("drone_ids", [])),
                status=SwarmStatus(s_data.get("status", "idle")),
                objective=s_data.get("objective"),
                target_ids=list(s_data.get("target_ids", [])),
            )
            self._swarms[swarm.id] = swarm

        for d_data in initial_state.get("drones", []):
            pos  = d_data.get("position")
            home = d_data.get("home_position")
            drone = Drone(
                id=d_data["id"],
                name=d_data["name"],
                model=DroneModel(d_data["model"]) if d_data.get("model") else None,
                type=DroneType(d_data["type"]),
                status=DroneStatus(d_data.get("status", "idle")),
                heading=d_data.get("heading", 0.0),
                speed=d_data.get("speed", 0.0),
                altitude=d_data.get("altitude", 100.0),
                battery=d_data.get("battery", 100.0),
                range_used_km=d_data.get("range_used_km", 0.0),
                max_range_km=d_data.get("max_range_km", 100.0),
                max_payload_kg=d_data.get("max_payload_kg"),
                max_flight_time_hours=d_data.get("max_flight_time_hours"),
                swarm_id=d_data.get("swarm_id"),
                current_task=d_data.get("current_task"),
                position=Position(**pos) if pos else None,
                home_position=Position(**home) if home else None,
            )
            self._drones[drone.id] = drone

        for t_data in initial_state.get("targets", []):
            pos = t_data.get("position")
            if pos:
                _check_terrain_constraint(t_data.get("type", ""), pos["lat"], pos["lon"])
            target = Target(
                id=t_data["id"],
                type=TargetType(t_data["type"]),
                status=TargetStatus(t_data.get("status", "active")),
                threat_value=ThreatValue(t_data["threat_value"]) if t_data.get("threat_value") else None,
                heading=t_data.get("heading", 0.0),
                speed=t_data.get("speed", 0.0),
                confidence=t_data.get("confidence", 1.0),
                reported_by=t_data.get("reported_by", ""),
                notes=t_data.get("notes"),
                position=Position(**pos) if pos else Position(lat=0.0, lon=0.0),
            )
            self._targets[target.id] = target

    def _build_initial_state(self) -> dict:
        """Serialize current in-memory state for persistence to assets_config.json."""
        drones_data = []
        for d in self._drones.values():
            entry: dict = {
                "id": d.id,
                "name": d.name,
                "model": d.model.value if d.model else None,
                "type": d.type.value,
                "status": "idle",
                "heading": d.heading,
                "speed": d.speed,
                "altitude": d.altitude,
                "battery": d.battery,
                "range_used_km": d.range_used_km,
                "max_range_km": d.max_range_km,
                "max_payload_kg": d.max_payload_kg,
                "max_flight_time_hours": d.max_flight_time_hours,
                "swarm_id": d.swarm_id,
                "current_task": None,
            }
            if d.position:
                entry["position"] = {"lat": d.position.lat, "lon": d.position.lon, "alt": d.position.alt}
            if d.home_position:
                entry["home_position"] = {"lat": d.home_position.lat, "lon": d.home_position.lon, "alt": d.home_position.alt}
            drones_data.append(entry)

        targets_data = []
        for t in self._targets.values():
            entry = {
                "id": t.id,
                "type": t.type.value,
                "status": t.status.value,
                "heading": t.heading,
                "speed": t.speed,
                "confidence": t.confidence,
                "reported_by": t.reported_by,
                "notes": t.notes,
                "threat_value": t.threat_value.value if t.threat_value else None,
            }
            if t.position:
                entry["position"] = {"lat": t.position.lat, "lon": t.position.lon, "alt": t.position.alt}
            targets_data.append(entry)

        swarms_data = []
        for s in self._swarms.values():
            swarms_data.append({
                "id": s.id,
                "name": s.name,
                "drone_model": s.drone_model.value if s.drone_model else None,
                "total_drone_count": s.total_drone_count,
                "drone_ids": list(s.drone_ids),
                "status": "idle",
                "objective": None,
                "target_ids": [],
            })

        return {"drones": drones_data, "targets": targets_data, "swarms": swarms_data}

    def save_config_to_file(self) -> bool:
        """Flush current asset positions to assets_config.json under 'initial_state'."""
        import json
        from services.config_service import CONFIG_PATH
        try:
            try:
                with open(CONFIG_PATH) as f:
                    raw_config = json.load(f)
            except FileNotFoundError:
                raw_config = {}
            with self._lock:
                raw_config["initial_state"] = self._build_initial_state()
            with open(CONFIG_PATH, "w") as f:
                json.dump(raw_config, f, indent=2)
            return True
        except Exception as exc:
            print(f"[state_service] save_config_to_file error: {exc}")
            return False

    def _seed_demo_data(self):
        """Seed platform with Taiwan war game assets per spec (values from assets_config.json)."""
        from models.target import Position
        from services.config_service import assets_config

        # Restore from saved initial_state if present (e.g. after drag-and-drop edits)
        if "initial_state" in assets_config:
            self._load_from_initial_state(assets_config["initial_state"])
            return

        cfg_mq9  = assets_config["mq9"]
        cfg_scou = assets_config["scout_recon"]
        cfg_fpv  = assets_config["fpv_combat"]
        cfg_alt  = assets_config["altius_600m"]
        cfg_en   = assets_config["enemy"]
        taipei_pct = assets_config["deployment"]["taipei_pct"]

        # No default deployments — if all counts are 0, start with empty battlefield
        total = (cfg_mq9.get("count", 0) + cfg_scou.get("count", 0) +
                 cfg_fpv.get("count", 0) + cfg_alt.get("count", 0))
        if total == 0:
            return

        # ── 4 MQ-9 Recon Drones ────────────────────────────────────────────────
        # always_airborne of them start patrolling; the rest are idle standby
        mq9_starts = [
            ("MQ9-01", 25.04, 121.56, 6000.0),   # Taipei area
            ("MQ9-02", 23.55, 119.63, 6000.0),   # Taiwan Strait
            ("MQ9-03", 22.62, 120.30, 0.0),       # Kaohsiung (standby)
            ("MQ9-04", 24.15, 120.68, 0.0),       # Taichung (standby)
        ]
        always_airborne = cfg_mq9["always_airborne"]
        for idx, (name, lat, lon, alt) in enumerate(mq9_starts[:cfg_mq9["count"]]):
            status = DroneStatus.PATROLLING if idx < always_airborne else DroneStatus.IDLE
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
                max_range_km=cfg_mq9["max_range_km"],
                max_flight_time_hours=cfg_mq9["max_flight_time_hours"],
            )
            self._drones[d.id] = d

        # ── FPV Combat Swarms ──────────────────────────────────────────────────
        # swarm_count swarms, each representing swarm_size drones; 60% Taipei
        fpv_swarm_names = [
            "FPV-Alpha", "FPV-Bravo", "FPV-Charlie", "FPV-Delta", "FPV-Echo",
            "FPV-Foxtrot", "FPV-Golf", "FPV-Hotel", "FPV-India", "FPV-Juliet",
        ]
        total_fpv_swarms = cfg_fpv["swarm_count"]
        for s_idx in range(total_fpv_swarms):
            base_lat, base_lon = _city_base(s_idx, total_fpv_swarms, taipei_pct)
            swarm = Swarm(
                name=fpv_swarm_names[s_idx],
                drone_model=DroneModel.FPV_COMBAT,
                total_drone_count=cfg_fpv["swarm_size"],
            )
            for i in range(5):
                pos = Position(lat=base_lat + i * 0.002, lon=base_lon, alt=150.0)
                d = Drone(
                    name=f"{fpv_swarm_names[s_idx]}-{i+1:03d}",
                    type=DroneType.SWARM_MEMBER,
                    model=DroneModel.FPV_COMBAT,
                    position=pos,
                    home_position=Position(lat=base_lat + i * 0.002, lon=base_lon, alt=0.0),
                    swarm_id=swarm.id,
                    max_payload_kg=cfg_fpv["max_payload_kg"],
                    max_range_km=cfg_fpv["max_range_km"],
                )
                self._drones[d.id] = d
                swarm.drone_ids.append(d.id)
            self._swarms[swarm.id] = swarm

        # ── Altius-600M Combat Swarms ──────────────────────────────────────────
        alt_swarm_names = ["ALT-Alpha", "ALT-Bravo", "ALT-Charlie", "ALT-Delta", "ALT-Echo"]
        total_alt_swarms = cfg_alt["swarm_count"]
        alt_base_cities = [
            (25.04, 121.56),  # Taipei
            (24.15, 120.68),  # Taichung
            (23.00, 120.21),  # Tainan
            (22.63, 120.30),  # Kaohsiung
            (24.80, 120.97),  # Hsinchu
        ]
        for s_idx in range(total_alt_swarms):
            base_lat, base_lon = alt_base_cities[s_idx % len(alt_base_cities)]
            swarm = Swarm(
                name=alt_swarm_names[s_idx],
                drone_model=DroneModel.ALTIUS_600M,
                total_drone_count=cfg_alt["swarm_size"],
            )
            for i in range(5):
                pos = Position(lat=base_lat + i * 0.002, lon=base_lon, alt=200.0)
                d = Drone(
                    name=f"{alt_swarm_names[s_idx]}-{i+1:03d}",
                    type=DroneType.SWARM_MEMBER,
                    model=DroneModel.ALTIUS_600M,
                    position=pos,
                    home_position=Position(lat=base_lat + i * 0.002, lon=base_lon, alt=0.0),
                    swarm_id=swarm.id,
                    max_payload_kg=cfg_alt["max_payload_kg"],
                    max_range_km=cfg_alt["max_range_km"],
                    max_flight_time_hours=4.0,
                )
                self._drones[d.id] = d
                swarm.drone_ids.append(d.id)
            self._swarms[swarm.id] = swarm

        # ── Scout Recon Drones (city home bases) ──────────────────────────────
        scout_count = cfg_scou["count"]
        for i in range(scout_count):
            home_lat, home_lon = _city_base(i, scout_count, taipei_pct)
            d = Drone(
                name=f"SCOUT-{i+1:03d}",
                type=DroneType.RECON,
                model=DroneModel.SCOUT_RECON,
                position=Position(lat=home_lat, lon=home_lon, alt=3000.0),
                home_position=Position(lat=home_lat, lon=home_lon, alt=0.0),
                status=DroneStatus.PATROLLING,
                heading=float(((i + 1) * 37) % 360),
                max_range_km=cfg_scou["max_range_km"],
            )
            self._drones[d.id] = d

        # ── Seeded Enemy Assets ────────────────────────────────────────────────
        from models.target import TargetType, TargetStatus, ThreatValue

        _SHIP_MS    = cfg_en["ships"]["speed_knots"] * 0.5144      # knots → m/s
        _TANK_MS    = cfg_en["tanks"]["speed_kmh"] / 3.6           # km/h → m/s
        _LR_MS      = cfg_en["long_range_drones"]["max_speed_kmh"] / 3.6
        _FPV_MS     = cfg_en["fpv_drones"]["max_speed_kmh"] / 3.6
        _SOLDIER_MS = cfg_en["soldiers"]["speed_kmh"] / 3.6

        _enemy_seed = [
            # Ships in Taiwan Strait — heading east toward Taiwan
            (TargetType.SHIP,             24.50, 119.50,    0,  90, _SHIP_MS, 0.92),
            (TargetType.SHIP,             24.00, 119.80,    0,  85, _SHIP_MS, 0.88),
            (TargetType.SHIP,             23.50, 119.60,    0,  95, _SHIP_MS, 0.85),
            (TargetType.SHIP,             23.00, 119.40,    0,  80, _SHIP_MS, 0.90),
            (TargetType.SHIP,             25.00, 119.90,    0,  88, _SHIP_MS, 0.87),
            # Tanks on west coast Taiwan — moving inland
            (TargetType.TANK,             25.00, 120.50,    0,  90, _TANK_MS, 0.91),
            (TargetType.TANK,             24.50, 120.60,    0,  75, _TANK_MS, 0.89),
            (TargetType.TANK,             23.50, 120.30,    0, 110, _TANK_MS, 0.86),
            (TargetType.TANK,             24.00, 120.50,    0,  95, _TANK_MS, 0.83),
            # Missile launchers in Fujian — stationary
            (TargetType.MISSILE_LAUNCHER, 25.90, 119.30,    0,   0,  0.0, 0.94),
            (TargetType.MISSILE_LAUNCHER, 25.00, 119.00,    0,   0,  0.0, 0.90),
            (TargetType.MISSILE_LAUNCHER, 24.50, 118.50,    0,   0,  0.0, 0.88),
            # Long-range attack drones — launched from mainland, heading east
            (TargetType.DRONE,            24.50, 120.00, 3000,  90, _LR_MS, 0.78),
            (TargetType.DRONE,            24.00, 120.50, 2500,  88, _LR_MS, 0.72),
            (TargetType.DRONE,            25.00, 120.20, 3500,  85, _LR_MS, 0.80),
            (TargetType.DRONE,            23.50, 119.80, 2000,  92, _LR_MS, 0.75),
            # Enemy FPV drones — low altitude, deployed in Taiwan
            (TargetType.DRONE,            25.00, 120.70,   50, 350, _FPV_MS, 0.65),
            (TargetType.DRONE,            24.50, 120.40,   30, 320, _FPV_MS, 0.60),
            (TargetType.DRONE,            23.80, 120.30,   40, 340, _FPV_MS, 0.62),
            # Soldier formations — advancing inland
            (TargetType.SOLDIER_UNIT,     25.00, 120.80,    0,  90, _SOLDIER_MS, 0.82),
            (TargetType.SOLDIER_UNIT,     24.60, 120.60,    0,  85, _SOLDIER_MS, 0.79),
            (TargetType.SOLDIER_UNIT,     24.20, 120.50,    0,  95, _SOLDIER_MS, 0.76),
            (TargetType.SOLDIER_UNIT,     23.70, 120.30,    0,  88, _SOLDIER_MS, 0.73),
        ]
        for ttype, lat, lon, alt, hdg, spd, conf in _enemy_seed:
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

    def get_all_targets(
        self,
        status_filter: Optional[TargetStatus] = None,
        reported_by: Optional[str] = None,
    ) -> list[Target]:
        targets = list(self._targets.values())
        if status_filter:
            targets = [t for t in targets if t.status == status_filter]
        if reported_by:
            targets = [t for t in targets if t.reported_by == reported_by]
        return targets

    def update_target_status(self, target_id: str, status: TargetStatus) -> bool:
        with self._lock:
            if target_id in self._targets:
                self._targets[target_id].status = status
                return True
        return False

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
        from models.target import Position
        with self._lock:
            if drone_id not in self._drones:
                return None
            drone = self._drones[drone_id]
            for key, value in updates.items():
                if value is not None and hasattr(drone, key):
                    if key in ("position", "home_position") and isinstance(value, dict):
                        value = Position(**value)
                    setattr(drone, key, value)
            drone.last_update = datetime.utcnow()
        return drone

    def get_drone(self, drone_id: str) -> Optional[Drone]:
        return self._drones.get(drone_id)

    def get_all_drones(self) -> list[Drone]:
        return list(self._drones.values())

    def remove_drone(self, drone_id: str) -> bool:
        with self._lock:
            if drone_id not in self._drones:
                return False
            del self._drones[drone_id]
            for swarm in self._swarms.values():
                if drone_id in swarm.drone_ids:
                    swarm.drone_ids.remove(drone_id)
            return True

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
                approval.decided_at = datetime.utcnow()
            return approval

    def expire_approvals(self):
        """Mark expired pending approvals. Called each tick."""
        now = datetime.utcnow()
        with self._lock:
            for approval in self._approvals.values():
                if approval.status == "pending" and approval.expires_at <= now:
                    approval.status = "expired"

    def release_tracking_drone(self, drone_id: str) -> None:
        """Feature 26: clear target assignment and resume patrolling when target is gone."""
        with self._lock:
            if drone_id in self._drones:
                d = self._drones[drone_id]
                d.tracking_target_id = None
                d.status = DroneStatus.PATROLLING
                d.current_task = None

    def replace_tracker_for_target(self, target_id: str) -> Optional[str]:
        """Feature 28: find any drone currently tracking target_id and send it home.
        Returns the released drone's ID, or None if no drone was tracking."""
        with self._lock:
            for d in self._drones.values():
                if d.tracking_target_id == target_id:
                    d.tracking_target_id = None
                    d.status = DroneStatus.RETURNING
                    d.current_task = None
                    return d.id
        return None

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
