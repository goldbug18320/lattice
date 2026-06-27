"""In-memory state management for drones, swarms, and targets."""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta
import math
import threading
from models.target import Target, TargetStatus, PendingApproval
from models.drone import Drone, Swarm, DroneStatus, DroneType, DroneModel, SwarmStatus

APPROVAL_TTL_MINUTES = 5

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


# ── Scout Patrol Grid (§8.2) ──────────────────────────────────────────────────
# 50×50 km grid covering coastal sea (within 25 km of Taiwan coast) and city areas.
# Mountain areas are excluded. Coastal sea cells have highest priority.
_SCOUT_LAT_STEP = 50.0 / 111.32                                       # ~0.449° per 50 km
_SCOUT_LON_STEP = 50.0 / (111.32 * math.cos(math.radians(24.0)))      # ~0.492° at 24°N
_SCOUT_LAT0, _SCOUT_LAT1 = 21.5, 26.5
_SCOUT_LON0, _SCOUT_LON1 = 119.0, 122.5


def _scout_zone(lat: float, lon: float) -> int:
    """
    Classify a grid cell for scout recon patrol:
      0 — excluded (Central Mountain Range, mainland interior, deep ocean)
      1 — coastal sea (highest priority — within ~25 km of Taiwan coastline)
      2 — city / plains (lower priority — on-island non-mountain areas)
    """
    # Central Mountain Range interior — excluded per spec
    if 120.7 <= lon <= 121.4 and 23.0 <= lat <= 25.0:
        return 0
    # West coastal sea (Taiwan Strait, within ~25 km of west coast)
    if lon <= 120.2 and lat >= 21.5:
        return 1
    # East coastal sea (Pacific Ocean, within ~25 km of east coast)
    if lon >= 121.7:
        return 1
    # North coast sea
    if lat >= 25.4 and 120.0 <= lon <= 122.2:
        return 1
    # South coast sea
    if lat <= 22.2 and 119.5 <= lon <= 121.5:
        return 1
    # City / plains on the island (non-mountain)
    if 22.0 <= lat <= 25.5 and 120.0 <= lon <= 121.8:
        return 2
    return 0  # outside patrol theater


def _build_scout_patrol_grids() -> list[tuple[float, float]]:
    """Return 50×50 km patrol grid centres sorted coastal-sea-first, then cities."""
    grids: list[tuple[float, float, int]] = []
    glat = _SCOUT_LAT0 + _SCOUT_LAT_STEP / 2
    while glat < _SCOUT_LAT1:
        glon = _SCOUT_LON0 + _SCOUT_LON_STEP / 2
        while glon < _SCOUT_LON1:
            z = _scout_zone(glat, glon)
            if z > 0:
                grids.append((glat, glon, z))
            glon += _SCOUT_LON_STEP
        glat += _SCOUT_LAT_STEP
    grids.sort(key=lambda x: x[2])  # priority 1 (coastal_sea) before 2 (city)
    return [(lat, lon) for lat, lon, _ in grids]


SCOUT_PATROL_GRIDS: list[tuple[float, float]] = _build_scout_patrol_grids()


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
        """Seed platform with Taiwan war game assets per spec (values from assets_config.json)."""
        from models.target import Position
        from services.config_service import assets_config

        cfg_mq9  = assets_config["mq9"]
        cfg_scou = assets_config["scout_recon"]
        cfg_fpv  = assets_config["fpv_combat"]
        cfg_alt  = assets_config["altius_600m"]
        cfg_en   = assets_config["enemy"]
        taipei_pct = assets_config["deployment"]["taipei_pct"]

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

        # ── Scout Recon Drones (grid patrol, city home bases) ─────────────────
        # Exactly max_in_flight scouts start PATROLLING (one per active patrol grid,
        # coastal-sea grids first). The remaining scouts start IDLE at their home
        # bases and are launched automatically by the movement service as replacements
        # when a patrolling scout exhausts its range and returns home (§8.2).
        max_in_flight = cfg_scou.get("max_in_flight", 20)
        active_grids = SCOUT_PATROL_GRIDS[:max_in_flight]

        scout_count = cfg_scou["count"]
        for i in range(scout_count):
            home_lat, home_lon = _city_base(i, scout_count, taipei_pct)
            if i < len(active_grids):
                g_lat, g_lon = active_grids[i]
                d = Drone(
                    name=f"SCOUT-{i+1:03d}",
                    type=DroneType.RECON,
                    model=DroneModel.SCOUT_RECON,
                    position=Position(lat=g_lat, lon=g_lon, alt=3000.0),
                    home_position=Position(lat=home_lat, lon=home_lon, alt=0.0),
                    status=DroneStatus.PATROLLING,
                    heading=float(((i + 1) * 37) % 360),
                    max_range_km=cfg_scou["max_range_km"],
                    max_flight_time_hours=5.0,
                    current_task=f"Grid patrol ({g_lat:.4f}°N, {g_lon:.4f}°E)",
                )
            else:
                d = Drone(
                    name=f"SCOUT-{i+1:03d}",
                    type=DroneType.RECON,
                    model=DroneModel.SCOUT_RECON,
                    position=Position(lat=home_lat, lon=home_lon, alt=0.0),
                    home_position=Position(lat=home_lat, lon=home_lon, alt=0.0),
                    status=DroneStatus.IDLE,
                    heading=0.0,
                    max_range_km=cfg_scou["max_range_km"],
                    max_flight_time_hours=5.0,
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
