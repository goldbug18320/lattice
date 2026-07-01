"""In-memory state management for drones, swarms, and targets."""
from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta
import threading
import uuid
from models.target import Target, TargetStatus, PendingApproval
from models.drone import Drone, Swarm, DroneStatus, DroneType, DroneModel, SwarmStatus

APPROVAL_TTL_MINUTES = 5

# Feature 21 + 27 — terrain placement constraints using real coastline polygons
from services.terrain_service import is_land as _terrain_is_land

_LAND_TARGET_TYPES = {'tank', 'missile_launcher', 'soldier_unit'}
_SEA_TARGET_TYPES  = {'ship'}

def _check_terrain_constraint(ttype: str, lat: float, lon: float) -> None:
    """Log a warning if a target's position violates the land/sea constraint (Feature 27)."""
    land = _terrain_is_land(lat, lon)
    if ttype in _LAND_TARGET_TYPES and not land:
        print(f"[Feature 21] WARNING: {ttype} at ({lat:.3f},{lon:.3f}) appears to be in water")
    elif ttype in _SEA_TARGET_TYPES and land:
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


def _zone_position(zones: list[tuple[float, float]], index: int, step: float = 0.02) -> tuple[float, float]:
    """Distribute `index` across `zones`, jittering by ring so repeated passes don't stack exactly."""
    zlat, zlon = zones[index % len(zones)]
    ring = index // len(zones)
    lat = zlat + ((ring % 10) - 5) * step
    lon = zlon + ((ring // 10 % 10) - 5) * step
    return lat, lon


def _snap_to_terrain(lat: float, lon: float, want_land: bool, step: float = 0.01, max_rings: int = 12) -> tuple[float, float]:
    """Nudge (lat, lon) to the nearest point matching `want_land` if it doesn't already.

    Used at seed time to enforce Feature 21 (soldiers/tanks/missile launchers on
    land, ships at sea) — jittered zone positions can otherwise land in the wrong
    terrain near a coastline. Spirals outward in a small grid; falls back to the
    original position (with a warning) if no valid point is found nearby.
    """
    if _terrain_is_land(lat, lon) == want_land:
        return lat, lon
    for ring in range(1, max_rings + 1):
        for dlat in range(-ring, ring + 1):
            for dlon in range(-ring, ring + 1):
                if abs(dlat) != ring and abs(dlon) != ring:
                    continue  # only test the outer edge of this ring
                clat, clon = lat + dlat * step, lon + dlon * step
                if _terrain_is_land(clat, clon) == want_land:
                    return clat, clon
    print(f"[Feature 21] WARNING: could not snap ({lat:.3f},{lon:.3f}) to "
          f"{'land' if want_land else 'water'} within {max_rings * step:.2f}° — leaving as-is")
    return lat, lon


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

        # ── Drones ──────────────────────────────────────────────────────────────
        for d_data in initial_state.get("drones", []):
            pos  = d_data.get("position")
            home = d_data.get("home_position")
            dtype = d_data.get("type")

            if dtype == "combat_swarm":
                # Feature 36: single entry represents the whole swarm.
                # The entry id is shared by both the Swarm object and its representative Drone.
                eid   = d_data["id"]
                model = DroneModel(d_data["model"]) if d_data.get("model") else None
                swarm = Swarm(
                    id=eid,
                    name=d_data["name"],
                    drone_model=model,
                    total_drone_count=d_data.get("total_drone_count", 1),
                    status=SwarmStatus.IDLE,
                    drone_ids=[eid],
                )
                drone = Drone(
                    id=eid,
                    name=d_data["name"],
                    model=model,
                    type=DroneType.COMBAT_SWARM,
                    status=DroneStatus.IDLE,
                    heading=d_data.get("heading", 0.0),
                    speed=d_data.get("speed", 0.0),
                    altitude=d_data.get("altitude", 100.0),
                    battery=d_data.get("battery", 100.0),
                    range_used_km=d_data.get("range_used_km", 0.0),
                    max_range_km=d_data.get("max_range_km", 15.0),
                    max_payload_kg=d_data.get("max_payload_kg"),
                    max_flight_time_hours=d_data.get("max_flight_time_hours"),
                    swarm_id=eid,
                    current_task=None,
                    position=Position(**pos) if pos else None,
                    home_position=Position(**home) if home else None,
                )
                self._swarms[swarm.id] = swarm
                self._drones[drone.id] = drone
                continue

            if dtype == "swarm_member":
                # Old format — skip individual member drones; swarm objects are in the swarms array below.
                continue

            drone = Drone(
                id=d_data["id"],
                name=d_data["name"],
                model=DroneModel(d_data["model"]) if d_data.get("model") else None,
                type=DroneType(dtype),
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

        # Old format backward compat: load swarms from a separate swarms array if present.
        for s_data in initial_state.get("swarms", []):
            if s_data["id"] in self._swarms:
                continue
            swarm = Swarm(
                id=s_data["id"],
                name=s_data["name"],
                drone_model=DroneModel(s_data["drone_model"]) if s_data.get("drone_model") else None,
                total_drone_count=s_data.get("total_drone_count", 0),
                drone_ids=list(s_data.get("drone_ids", [])),
                status=SwarmStatus.IDLE,
            )
            self._swarms[swarm.id] = swarm

        # ── Targets ──────────────────────────────────────────────────────────────
        for t_data in initial_state.get("targets", []):
            pos = t_data.get("position")
            if pos:
                _check_terrain_constraint(t_data.get("type", ""), pos["lat"], pos["lon"])
            parsed_pos = Position(**pos) if pos else Position(lat=0.0, lon=0.0)
            dest_raw = t_data.get("destination")
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
                position=parsed_pos,
                destination=Position(**dest_raw) if dest_raw else None,
            )
            self._targets[target.id] = target

    def _build_initial_state(self) -> dict:
        """Serialize current in-memory state for persistence to assets_config.json.

        Feature 36: combat swarms are stored as a single 'combat_swarm' entry in the
        drones list — no separate swarms array, no individual swarm_member drones.
        """
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
                "current_task": None,
            }
            if d.type == DroneType.COMBAT_SWARM:
                swarm = self._swarms.get(d.swarm_id)
                entry["total_drone_count"] = swarm.total_drone_count if swarm else 1
            else:
                entry["swarm_id"] = d.swarm_id
            if d.position:
                entry["position"] = {"lat": d.position.lat, "lon": d.position.lon, "alt": d.position.alt}
            if d.home_position:
                entry["home_position"] = {"lat": d.home_position.lat, "lon": d.home_position.lon, "alt": d.home_position.alt}
            drones_data.append(entry)

        _PERSIST_STATUSES = {"active", "destroyed", "lost"}
        targets_data = []
        for t in self._targets.values():
            entry = {
                "id": t.id,
                "type": t.type.value,
                "status": t.status.value if t.status.value in _PERSIST_STATUSES else "active",
                "heading": t.heading,
                "speed": t.speed,
                "confidence": t.confidence,
                "reported_by": t.reported_by,
                "notes": t.notes,
                "threat_value": t.threat_value.value if t.threat_value else None,
            }
            if t.position:
                entry["position"] = {"lat": t.position.lat, "lon": t.position.lon, "alt": t.position.alt}
            if t.destination:
                entry["destination"] = {"lat": t.destination.lat, "lon": t.destination.lon, "alt": t.destination.alt}
            targets_data.append(entry)

        return {"drones": drones_data, "targets": targets_data}

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
        cfg_fpv  = assets_config["fpv_combat"]
        cfg_alt  = assets_config["altius_600m"]
        cfg_en   = assets_config["enemy"]
        cfg_seed = assets_config["initial_seed"]
        cfg_seed_f = cfg_seed["friendly"]
        cfg_seed_e = cfg_seed["enemy"]
        taipei_pct = assets_config["deployment"]["taipei_pct"]

        # No default deployments — if all counts are 0, start with empty battlefield
        total = (cfg_mq9.get("count", 0) + cfg_seed_f.get("scout_recon", 0) +
                 cfg_seed_f.get("fpv_swarms", 0) + cfg_seed_f.get("altius_swarms", 0) +
                 cfg_seed_f.get("soldier_units", 0))
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

        # ── Friendly Soldier Units (seeded first so FPV swarms can collocate) ───
        # Ground formation (blue IFF); shares the soldier_unit TargetType with
        # enemy soldiers, distinguished by affiliation.
        from models.target import TargetType, TargetStatus, ThreatValue

        friendly_soldier_count = cfg_seed_f.get("soldier_units", 0)
        friendly_soldier_positions: list[Position] = []
        for i in range(friendly_soldier_count):
            base_lat, base_lon = _city_base(i, max(friendly_soldier_count, 1), taipei_pct)
            lat = base_lat + ((i % 7) - 3) * 0.01
            lon = base_lon + ((i // 7 % 7) - 3) * 0.01
            lat, lon = _snap_to_terrain(lat, lon, want_land=True)  # Feature 21: soldiers must be on land
            pos = Position(lat=lat, lon=lon, alt=0.0)
            friendly_soldier_positions.append(pos)
            t = Target(
                type=TargetType.SOLDIER_UNIT,
                position=pos,
                heading=0.0,
                speed=0.0,
                status=TargetStatus.ACTIVE,
                reported_by="seed",
                affiliation="friendly",
            )
            self._targets[t.id] = t

        # ── FPV Combat Swarms (collocated with the friendly Soldier Units) ──────
        # Feature 36: one combat_swarm entry per swarm (representative drone shares swarm id)
        fpv_swarm_names_base = [
            "Alpha", "Bravo", "Charlie", "Delta", "Echo",
            "Foxtrot", "Golf", "Hotel", "India", "Juliet",
        ]

        def _fpv_swarm_name(idx: int) -> str:
            if idx < len(fpv_swarm_names_base):
                return f"FPV-{fpv_swarm_names_base[idx]}"
            return f"FPV-{idx + 1:03d}"

        total_fpv_swarms = cfg_seed_f.get("fpv_swarms", 0)
        for s_idx in range(total_fpv_swarms):
            if friendly_soldier_positions:
                collocated = friendly_soldier_positions[s_idx % len(friendly_soldier_positions)]
                base_lat, base_lon = collocated.lat, collocated.lon
            else:
                base_lat, base_lon = _city_base(s_idx, total_fpv_swarms, taipei_pct)
            sid = str(uuid.uuid4())
            name = _fpv_swarm_name(s_idx)
            swarm = Swarm(
                id=sid,
                name=name,
                drone_model=DroneModel.FPV_COMBAT,
                total_drone_count=cfg_fpv["swarm_size"],
                drone_ids=[sid],
            )
            d = Drone(
                id=sid,
                name=name,
                type=DroneType.COMBAT_SWARM,
                model=DroneModel.FPV_COMBAT,
                position=Position(lat=base_lat, lon=base_lon, alt=150.0),
                home_position=Position(lat=base_lat, lon=base_lon, alt=0.0),
                swarm_id=sid,
                max_payload_kg=cfg_fpv["max_payload_kg"],
                max_range_km=cfg_fpv["max_range_km"],
            )
            self._drones[d.id] = d
            self._swarms[swarm.id] = swarm

        # ── Altius-600M Combat Swarms ──────────────────────────────────────────
        total_alt_swarms = cfg_seed_f.get("altius_swarms", 0)
        alt_base_cities = [
            (25.04, 121.56),  # Taipei
            (24.15, 120.68),  # Taichung
            (23.00, 120.21),  # Tainan
            (22.63, 120.30),  # Kaohsiung
            (24.80, 120.97),  # Hsinchu
        ]
        for s_idx in range(total_alt_swarms):
            base_lat, base_lon = alt_base_cities[s_idx % len(alt_base_cities)]
            sid = str(uuid.uuid4())
            name = f"ALT-{s_idx + 1:03d}"
            swarm = Swarm(
                id=sid,
                name=name,
                drone_model=DroneModel.ALTIUS_600M,
                total_drone_count=cfg_alt["swarm_size"],
                drone_ids=[sid],
            )
            d = Drone(
                id=sid,
                name=name,
                type=DroneType.COMBAT_SWARM,
                model=DroneModel.ALTIUS_600M,
                position=Position(lat=base_lat, lon=base_lon, alt=200.0),
                home_position=Position(lat=base_lat, lon=base_lon, alt=0.0),
                swarm_id=sid,
                max_payload_kg=cfg_alt["max_payload_kg"],
                max_range_km=cfg_alt["max_range_km"],
                max_flight_time_hours=4.0,
            )
            self._drones[d.id] = d
            self._swarms[swarm.id] = swarm

        # ── Scout Recon Drones (city home bases) ──────────────────────────────
        scout_count = cfg_seed_f.get("scout_recon", 0)
        for i in range(scout_count):
            home_lat, home_lon = _city_base(i, scout_count, taipei_pct)
            d = Drone(
                name=f"SCOUT-{i+1:03d}",
                type=DroneType.RECON,
                model=DroneModel.SCOUT_RECON,
                position=Position(lat=home_lat, lon=home_lon, alt=0.0),
                home_position=Position(lat=home_lat, lon=home_lon, alt=0.0),
                status=DroneStatus.IDLE,
                heading=float(((i + 1) * 37) % 360),
                max_range_km=assets_config["scout_recon"]["max_range_km"],
            )
            self._drones[d.id] = d

        # ── Seeded Enemy Assets ────────────────────────────────────────────────
        # All enemy assets are stationary by default at spawn (Feature 33); the
        # operator sets heading/destination via the right-click context menu.

        # Verified-on-land mainland China coastal points (Fujian) for ground assets
        _CHINA_ZONES   = [(26.08, 119.30), (24.51, 117.65), (25.72, 119.38), (25.50, 119.78)]
        # Verified-on-land Taiwan west-coast points for ground assets
        _TANK_ZONES    = [(24.15, 120.68), (23.00, 120.21), (22.63, 120.30), (23.97, 121.60)]
        _SOLDIER_ZONES = [(24.15, 120.68), (23.00, 120.21), (22.63, 120.30), (24.80, 120.97)]
        # Taiwan Strait open-water points for ships
        _SHIP_ZONES    = [(24.50, 119.50), (24.00, 119.80), (23.50, 119.60), (23.00, 119.40), (25.00, 119.90)]

        # ── Enemy Soldier Units (seeded first so enemy FPV swarms can collocate) ──
        enemy_soldier_count = cfg_seed_e.get("soldier_units", 0)
        enemy_soldier_positions: list[Position] = []
        for i in range(enemy_soldier_count):
            lat, lon = _zone_position(_SOLDIER_ZONES, i)
            lat, lon = _snap_to_terrain(lat, lon, want_land=True)  # Feature 21: soldiers must be on land
            pos = Position(lat=lat, lon=lon, alt=0.0)
            enemy_soldier_positions.append(pos)
            t = Target(
                type=TargetType.SOLDIER_UNIT,
                position=pos,
                heading=float((90 + i * 5) % 360),
                speed=0.0,
                confidence=0.8,
                status=TargetStatus.ACTIVE,
                threat_value=ThreatValue.LOW,
                reported_by="seed",
                affiliation="enemy",
            )
            self._targets[t.id] = t

        # ── Enemy FPV Swarms (collocated with the enemy Soldier Units) ──────────
        # Organized into swarms (mirroring the friendly FPV combat structure) rather
        # than tracked as individual drones — one Target entry per swarm, low altitude.
        _FPV_MS = cfg_en["fpv_drones"]["max_speed_kmh"] / 3.6
        fpv_swarm_count = cfg_seed_e.get("fpv_swarms", 0)
        fpv_swarm_size  = cfg_en["fpv_drones"].get("swarm_size", 1)
        for i in range(fpv_swarm_count):
            if enemy_soldier_positions:
                collocated = enemy_soldier_positions[i % len(enemy_soldier_positions)]
                lat, lon = collocated.lat, collocated.lon
            else:
                lat, lon = _zone_position([(25.00, 120.70), (24.50, 120.40), (23.80, 120.30)], i)
            t = Target(
                type=TargetType.DRONE,
                position=Position(lat=lat, lon=lon, alt=50.0),
                heading=float((320 + i * 7) % 360),
                speed=_FPV_MS,
                confidence=0.6,
                status=TargetStatus.ACTIVE,
                threat_value=ThreatValue.LOW,
                reported_by="seed",
                affiliation="enemy",
                swarm_size=fpv_swarm_size,
            )
            self._targets[t.id] = t

        # ── Enemy Long-Range Attack Drone Swarms ────────────────────────────────
        # Now organized into swarms (mirroring the enemy FPV reorg); deployed in
        # mainland China and stationary at spawn like every other seeded asset.
        lr_swarm_count = cfg_seed_e.get("long_range_swarms", 0)
        lr_swarm_size  = cfg_en["long_range_drones"].get("swarm_size", 1)
        for i in range(lr_swarm_count):
            lat, lon = _zone_position(_CHINA_ZONES, i)
            t = Target(
                type=TargetType.DRONE,
                position=Position(lat=lat, lon=lon, alt=3000.0),
                heading=float((85 + i * 3) % 360),
                speed=0.0,
                confidence=0.78,
                status=TargetStatus.ACTIVE,
                threat_value=ThreatValue.MEDIUM,
                reported_by="seed",
                affiliation="enemy",
                swarm_size=lr_swarm_size,
            )
            self._targets[t.id] = t

        # ── Enemy Tanks ──────────────────────────────────────────────────────────
        for i in range(cfg_seed_e.get("tanks", 0)):
            lat, lon = _zone_position(_TANK_ZONES, i)
            lat, lon = _snap_to_terrain(lat, lon, want_land=True)  # Feature 21: tanks must be on land
            t = Target(
                type=TargetType.TANK,
                position=Position(lat=lat, lon=lon, alt=0.0),
                heading=float((90 + i * 11) % 360),
                speed=0.0,
                confidence=0.88,
                status=TargetStatus.ACTIVE,
                threat_value=ThreatValue.MEDIUM,
                reported_by="seed",
                affiliation="enemy",
            )
            self._targets[t.id] = t

        # ── Enemy Ships (Taiwan Strait) ──────────────────────────────────────────
        for i in range(cfg_seed_e.get("ships", 0)):
            lat, lon = _zone_position(_SHIP_ZONES, i)
            lat, lon = _snap_to_terrain(lat, lon, want_land=False)  # Feature 21: ships must be in the water
            t = Target(
                type=TargetType.SHIP,
                position=Position(lat=lat, lon=lon, alt=0.0),
                heading=float((90 + i * 5) % 360),
                speed=0.0,
                confidence=0.9,
                status=TargetStatus.ACTIVE,
                threat_value=ThreatValue.HIGH,
                reported_by="seed",
                affiliation="enemy",
            )
            self._targets[t.id] = t

        # ── Enemy Missile Launchers (mainland China) ─────────────────────────────
        for i in range(cfg_seed_e.get("missile_launchers", 0)):
            lat, lon = _zone_position(_CHINA_ZONES, i)
            lat, lon = _snap_to_terrain(lat, lon, want_land=True)  # Feature 21: missile launchers must be on land
            t = Target(
                type=TargetType.MISSILE_LAUNCHER,
                position=Position(lat=lat, lon=lon, alt=0.0),
                heading=0.0,
                speed=0.0,
                confidence=0.9,
                status=TargetStatus.ACTIVE,
                threat_value=ThreatValue.HIGH,
                reported_by="seed",
                affiliation="enemy",
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
                if not hasattr(drone, key):
                    continue
                if value is None and key != "destination":
                    continue
                if key in ("position", "home_position", "destination") and isinstance(value, dict):
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
            for sid in list(self._swarms.keys()):
                swarm = self._swarms[sid]
                if drone_id in swarm.drone_ids:
                    swarm.drone_ids.remove(drone_id)
                    if not swarm.drone_ids:  # Feature 36: remove swarm when its representative drone is removed
                        del self._swarms[sid]
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

    def disengage_target(self, target_id: str) -> Optional[dict]:
        """Feature 32: release an engaged target and recall its combat swarm to base.

        Returns {"swarm_id", "swarm_name"} for the recalled swarm, or None if the
        target was not in `engaged` status (no-op) or no engaging swarm was found."""
        with self._lock:
            target = self._targets.get(target_id)
            if not target or target.status != TargetStatus.ENGAGED:
                return None

            target.status = TargetStatus.ACTIVE

            swarm = next(
                (s for s in self._swarms.values()
                 if target_id in s.target_ids and s.status == SwarmStatus.ENGAGING),
                None,
            )
            if swarm is None:
                return None

            swarm.target_ids = []
            swarm.objective = None
            swarm.status = SwarmStatus.RETURNING
            for did in swarm.drone_ids:
                d = self._drones.get(did)
                if d is not None:
                    d.status = DroneStatus.RETURNING
                    d.current_task = None

            return {"swarm_id": swarm.id, "swarm_name": swarm.name}

    def stop_tracking_target(self, target_id: str) -> Optional[dict]:
        """Feature 37: release a tracked target and recall its recon drone to base.

        Returns {"drone_id", "drone_name"} for the recalled drone, or None if the
        target was not in `tracked` status (no-op) or no tracking drone was found."""
        with self._lock:
            target = self._targets.get(target_id)
            if not target or target.status != TargetStatus.TRACKED:
                return None

            target.status = TargetStatus.ACTIVE

            drone = next(
                (d for d in self._drones.values()
                 if d.tracking_target_id == target_id and d.status == DroneStatus.TRACKING),
                None,
            )
            if drone is None:
                return None

            drone.tracking_target_id = None
            drone.status = DroneStatus.RETURNING
            drone.current_task = None

            return {"drone_id": drone.id, "drone_name": drone.name}

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
