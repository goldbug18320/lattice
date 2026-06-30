"""Drone movement simulator — advances all non-idle drone positions at 1 Hz.
Also advances mobile enemy targets each tick (§8.8).
"""
from __future__ import annotations
import math
from models.drone import DroneModel, DroneStatus, SwarmStatus
from models.target import Position, TargetStatus, TargetType
from services.config_service import assets_config

# ── Terrain checking (Feature 21 + 27) ────────────────────────────────────────
# Delegates to terrain_service which loads real GeoJSON coastline polygons
# covering Taiwan, China, North Korea, South Korea, Japan, and Philippines.
from services.terrain_service import is_land as _terrain_is_land

_TERRAIN_ENABLED: bool = True  # always on; can be patched False in tests to disable


def _is_land(lat: float, lon: float) -> bool:
    """Return True if (lat, lon) is over land (Feature 27)."""
    return _terrain_is_land(lat, lon)


_GROUND_ASSET_TYPES = frozenset({
    TargetType.SOLDIER_UNIT,
    TargetType.TANK,
    TargetType.MISSILE_LAUNCHER,
})


def _terrain_blocks(target_type: TargetType, pos: Position) -> bool:
    """Feature 21: return True if pos violates terrain constraints for target_type."""
    if not _TERRAIN_ENABLED:
        return False
    land = _is_land(pos.lat, pos.lon)
    if target_type in _GROUND_ASSET_TYPES:
        return not land  # ground assets must remain on land
    if target_type == TargetType.SHIP:
        return land      # ships must remain at sea
    return False         # drones: unconstrained

DT = 1.0  # seconds per tick

# Cruise speed (m/s) per drone model
_MODEL_SPEED: dict[DroneModel, float] = {
    DroneModel.MQ9_RECON:   60.0,   # 216 km/h
    DroneModel.SCOUT_RECON: 42.0,   # 150 km/h
    DroneModel.FPV_COMBAT:  42.0,   # 150 km/h
    DroneModel.ALTIUS_600M: 25.0,   # 90 km/h
}

# Detection radii from config (configurable, not hard-coded)
MQ9_DETECTION_RADIUS_KM   = assets_config["mq9"]["detection_radius_km"]
SCOUT_DETECTION_RADIUS_KM = assets_config["scout_recon"]["detection_radius_km"]

# Speed fraction per status
_STATUS_SPEED_MULT: dict[DroneStatus, float] = {
    DroneStatus.PATROLLING: 1.0,
    DroneStatus.SEARCHING:  0.5,
    DroneStatus.TRACKING:   0.8,
    DroneStatus.ENGAGING:   1.0,
    DroneStatus.RETURNING:  1.0,
}

_ARRIVE_THRESHOLD_KM = 0.5     # home arrival radius (500 m)
_PATROL_HEADING_DELTA = 2.0    # degrees/tick for MQ-9 / scout orbit
_FPV_PATROL_HEADING_DELTA = 3.0  # degrees/tick for enemy FPV patrol rotation
CONTACT_RADIUS_KM = assets_config.get("combat", {}).get("contact_radius_m", 500.0) / 1000.0
TRACKING_STANDOFF_KM = 10.0   # Feature 28: recon drones maintain this distance from their target


def _advance(pos: Position, heading_deg: float, speed_ms: float, dt: float) -> Position:
    """Move pos along heading by speed*dt using flat-earth approximation."""
    heading_rad = math.radians(heading_deg)
    lat_rad = math.radians(pos.lat)
    delta_lat = speed_ms * dt * math.cos(heading_rad) / 111_320
    delta_lon = speed_ms * dt * math.sin(heading_rad) / (111_320 * math.cos(lat_rad))
    return Position(lat=pos.lat + delta_lat, lon=pos.lon + delta_lon, alt=pos.alt)


def _distance_km(a: Position, b: Position) -> float:
    """Approximate flat-earth distance in km."""
    dlat = (b.lat - a.lat) * 111.32
    dlon = (b.lon - a.lon) * 111.32 * math.cos(math.radians(a.lat))
    return math.sqrt(dlat ** 2 + dlon ** 2)


def _bearing(from_pos: Position, to_pos: Position) -> float:
    """Compass bearing (0-360°) from from_pos to to_pos."""
    dlat = (to_pos.lat - from_pos.lat) * 111_320
    dlon = (to_pos.lon - from_pos.lon) * 111_320 * math.cos(math.radians(from_pos.lat))
    return math.degrees(math.atan2(dlon, dlat)) % 360


class MovementService:
    """Ticked by the broadcast loop in main.py once per second."""

    def tick(self, state_service) -> None:
        """Advance all non-idle drone positions and all mobile enemy targets one step."""
        self._tick_friendly_drones(state_service)
        self._tick_enemy_assets(state_service)
        self._check_combat_contacts(state_service)
        self._run_mq9_detection(state_service)
        self._run_scout_detection(state_service)
        self._maybe_launch_standby_mq9(state_service)

    def _tick_friendly_drones(self, state_service) -> None:
        """Advance all non-idle friendly drone positions one step."""
        for drone in state_service.get_all_drones():
            if drone.position is None:
                continue
            if drone.status in (DroneStatus.IDLE, DroneStatus.OFFLINE):
                continue

            speed = _MODEL_SPEED.get(drone.model, 42.0)
            range_used = drone.range_used_km

            # ── Returning to home ────────────────────────────────────────────
            if drone.status == DroneStatus.RETURNING:
                if drone.home_position is None:
                    continue
                dist = _distance_km(drone.position, drone.home_position)
                if dist <= _ARRIVE_THRESHOLD_KM:
                    state_service.update_drone(drone.id, {
                        "status": DroneStatus.IDLE,
                        "position": drone.home_position,
                        "range_used_km": 0.0,
                        "speed": 0.0,
                    })
                else:
                    hdg = _bearing(drone.position, drone.home_position)
                    new_pos = _advance(drone.position, hdg, speed, DT)
                    state_service.update_drone(drone.id, {
                        "position": new_pos,
                        "heading": hdg,
                        "speed": speed,
                        "range_used_km": range_used + speed * DT / 1000,
                    })
                continue

            # ── Range-budget check ───────────────────────────────────────────
            max_range = drone.max_range_km or 9_999_999
            if range_used >= max_range:
                # FPV engaging → expended (one-way strike)
                if drone.model == DroneModel.FPV_COMBAT and drone.status == DroneStatus.ENGAGING:
                    state_service.update_drone(drone.id, {
                        "status": DroneStatus.OFFLINE,
                        "speed": 0.0,
                    })
                else:
                    state_service.update_drone(drone.id, {
                        "status": DroneStatus.RETURNING,
                        "speed": speed,
                    })
                continue

            # ── Determine heading ────────────────────────────────────────────
            hold_at_standoff = False  # Feature 28: set True below for tracking recon within standoff
            if drone.status == DroneStatus.PATROLLING and drone.model == DroneModel.MQ9_RECON:
                # Stable circular orbit around home_position (§8.5): heading perpendicular
                # to the inward radial gives constant-radius clockwise orbit.
                if drone.home_position and _distance_km(drone.position, drone.home_position) > 0.1:
                    inward_bearing = _bearing(drone.position, drone.home_position)
                    new_heading = (inward_bearing - 90.0) % 360.0
                else:
                    new_heading = (drone.heading + _PATROL_HEADING_DELTA) % 360
            elif drone.status == DroneStatus.PATROLLING and drone.model == DroneModel.SCOUT_RECON:
                new_heading = (drone.heading + _PATROL_HEADING_DELTA) % 360
            elif drone.status == DroneStatus.SEARCHING and drone.swarm_id:
                swarm = state_service.get_swarm(drone.swarm_id)
                if swarm and swarm.area_of_interest:
                    bbox = swarm.area_of_interest
                    inside = (
                        bbox["min_lat"] <= drone.position.lat <= bbox["max_lat"]
                        and bbox["min_lon"] <= drone.position.lon <= bbox["max_lon"]
                    )
                    if inside:
                        state_service.update_drone(drone.id, {
                            "status": DroneStatus.PATROLLING,
                            "current_task": swarm.objective or "Patrol area",
                        })
                        new_heading = (drone.heading + _PATROL_HEADING_DELTA) % 360
                    else:
                        new_heading = drone.heading
                else:
                    new_heading = drone.heading
            elif drone.status in (DroneStatus.TRACKING, DroneStatus.ENGAGING):
                new_heading = drone.heading
                target = None
                if drone.swarm_id:
                    swarm = state_service.get_swarm(drone.swarm_id)
                    if swarm and swarm.target_ids:
                        target = state_service.get_target(swarm.target_ids[0])
                elif drone.tracking_target_id:
                    target = state_service.get_target(drone.tracking_target_id)
                    # Feature 26: release recon drone when its target is gone or destroyed
                    if target is None or target.status == TargetStatus.DESTROYED:
                        state_service.release_tracking_drone(drone.id)
                        continue
                if target and target.position:
                    # Feature 26: recalculate bearing toward target's current position each tick
                    new_heading = _bearing(drone.position, target.position)
                    # Feature 28: recon drones hold at 10 km standoff instead of closing further
                    if (
                        drone.status == DroneStatus.TRACKING
                        and _distance_km(drone.position, target.position) <= TRACKING_STANDOFF_KM
                    ):
                        hold_at_standoff = True
            else:
                new_heading = drone.heading

            # ── Advance position ─────────────────────────────────────────────
            if hold_at_standoff:
                # Feature 28: within standoff radius — hold position, face target, drain battery
                state_service.update_drone(drone.id, {
                    "heading": new_heading,
                    "speed": 0.0,
                    "battery": max(0.0, drone.battery - 0.002),
                })
            else:
                mult = _STATUS_SPEED_MULT.get(drone.status, 0.5)
                eff_speed = speed * mult
                new_pos = _advance(drone.position, new_heading, eff_speed, DT)
                delta_km = eff_speed * DT / 1000

                state_service.update_drone(drone.id, {
                    "position": new_pos,
                    "heading": new_heading,
                    "speed": eff_speed,
                    "range_used_km": range_used + delta_km,
                    "battery": max(0.0, drone.battery - 0.002),
                })

    def _tick_enemy_assets(self, state_service) -> None:
        """Advance all mobile enemy targets one step (§8.8).

        Targets are mutated in-place; the next WebSocket broadcast delivers
        the updated positions to all UI clients.
        """
        for target in state_service.get_all_targets():
            if target.status in (TargetStatus.DESTROYED, TargetStatus.LOST):
                continue
            if target.position is None:
                continue

            # Feature 33: drone-specific movement modes set via right-click context menu
            if target.type == TargetType.DRONE and target.movement_mode:
                if target.movement_mode == 'returning' and target.home_position is not None and target.speed > 0:
                    dist = _distance_km(target.position, target.home_position)
                    if dist <= _ARRIVE_THRESHOLD_KM:
                        target.position = target.home_position
                        target.movement_mode = None
                        target.speed = 0.0
                    else:
                        hdg = _bearing(target.position, target.home_position)
                        target.heading = hdg
                        new_pos = _advance(target.position, hdg, target.speed, DT)
                        if not _terrain_blocks(target.type, new_pos):
                            target.position = new_pos
                elif target.movement_mode == 'patrolling' and target.speed > 0:
                    new_pos = _advance(target.position, target.heading, target.speed, DT)
                    if not _terrain_blocks(target.type, new_pos):
                        target.position = new_pos
                    target.heading = (target.heading + 1.0) % 360
                continue  # skip default movement logic for drones with an explicit mode

            if target.speed <= 0:
                continue
            new_pos = _advance(target.position, target.heading, target.speed, DT)
            if _terrain_blocks(target.type, new_pos):
                continue  # halt at terrain boundary (Feature 21)
            target.position = new_pos
            # Enemy FPV drones (low altitude) slowly rotate for a patrol pattern
            if target.type == TargetType.DRONE and target.position.alt <= 500:
                target.heading = (target.heading + _FPV_PATROL_HEADING_DELTA) % 360

    def _check_combat_contacts(self, state_service) -> None:
        """Feature 23: when any engaging drone reaches its target, destroy the target
        and destroy the entire combat drone swarm — every member drone goes offline,
        no drones survive or return."""
        for swarm in state_service.get_all_swarms():
            if swarm.status != SwarmStatus.ENGAGING:
                continue
            if not swarm.target_ids:
                continue
            target = state_service.get_target(swarm.target_ids[0])
            if target is None or target.status == TargetStatus.DESTROYED:
                continue
            if target.position is None:
                continue

            # Check whether any member drone has reached the target
            contact = False
            for did in swarm.drone_ids:
                d = state_service.get_drone(did)
                if (
                    d is not None
                    and d.position is not None
                    and d.status == DroneStatus.ENGAGING
                    and _distance_km(d.position, target.position) <= CONTACT_RADIUS_KM
                ):
                    contact = True
                    break
            if not contact:
                continue

            # ── Contact: destroy target and entire swarm ──────────────────────
            state_service.mark_target_destroyed(target.id)
            drones_destroyed = len(swarm.drone_ids)
            for did in swarm.drone_ids:
                state_service.update_drone(did, {"status": DroneStatus.OFFLINE, "speed": 0.0})
            state_service.update_swarm_status(swarm.id, SwarmStatus.IDLE)
            live_swarm = state_service.get_swarm(swarm.id)
            if live_swarm:
                live_swarm.target_ids = []
                live_swarm.objective = None
            # Feature 26: release any recon drone that was tracking this target
            for d in state_service.get_all_drones():
                if d.tracking_target_id == target.id:
                    state_service.release_tracking_drone(d.id)
            state_service.log_command({
                "type": "combat_contact",
                "swarm_id": swarm.id,
                "swarm_name": swarm.name,
                "target_id": target.id,
                "target_type": target.type.value,
                "drones_destroyed": drones_destroyed,
            })

    def _run_mq9_detection(self, state_service) -> None:
        """Each patrolling MQ-9 detects enemy targets within its configured detection radius."""
        from datetime import datetime
        airborne_mq9 = [
            d for d in state_service.get_all_drones()
            if d.model == DroneModel.MQ9_RECON
            and d.status == DroneStatus.PATROLLING
            and d.position is not None
        ]
        if not airborne_mq9:
            return

        all_targets = state_service.get_all_targets()
        now = datetime.utcnow()
        for drone in airborne_mq9:
            for target in all_targets:
                if target.position is None:
                    continue
                if _distance_km(drone.position, target.position) <= MQ9_DETECTION_RADIUS_KM:
                    target.last_seen = now
                    target.reported_by = drone.name
                    target.confidence = min(1.0, target.confidence + 0.05)

    def _run_scout_detection(self, state_service) -> None:
        """Each patrolling scout recon drone detects enemy targets within its configured detection radius."""
        from datetime import datetime
        scouts = [
            d for d in state_service.get_all_drones()
            if d.model == DroneModel.SCOUT_RECON
            and d.status == DroneStatus.PATROLLING
            and d.position is not None
        ]
        if not scouts:
            return

        all_targets = state_service.get_all_targets()
        now = datetime.utcnow()
        for drone in scouts:
            for target in all_targets:
                if target.position is None:
                    continue
                if _distance_km(drone.position, target.position) <= SCOUT_DETECTION_RADIUS_KM:
                    target.last_seen = now
                    target.reported_by = drone.name
                    target.confidence = min(1.0, target.confidence + 0.03)

    def _maybe_launch_standby_mq9(self, state_service) -> None:
        """Launch a standby MQ-9 whenever fewer than always_airborne are patrolling/returning (§8.1)."""
        always_airborne = assets_config.get("mq9", {}).get("always_airborne", 2)
        all_mq9 = [d for d in state_service.get_all_drones() if d.model == DroneModel.MQ9_RECON]
        airborne_count = sum(
            1 for d in all_mq9 if d.status in (DroneStatus.PATROLLING, DroneStatus.RETURNING)
        )
        if airborne_count >= always_airborne:
            return
        standby = next((d for d in all_mq9 if d.status == DroneStatus.IDLE), None)
        if standby:
            state_service.update_drone(standby.id, {
                "status": DroneStatus.PATROLLING,
                "speed": _MODEL_SPEED[DroneModel.MQ9_RECON],
            })

movement_service = MovementService()
