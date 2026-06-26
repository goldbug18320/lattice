"""Drone movement simulator — advances all non-idle drone positions at 1 Hz."""
from __future__ import annotations
import math
from models.drone import DroneModel, DroneStatus
from models.target import Position

DT = 1.0  # seconds per tick

# Cruise speed (m/s) per drone model
_MODEL_SPEED: dict[DroneModel, float] = {
    DroneModel.MQ9_RECON:   60.0,   # 216 km/h
    DroneModel.SCOUT_RECON: 42.0,   # 150 km/h
    DroneModel.FPV_COMBAT:  42.0,   # 150 km/h
    DroneModel.ALTIUS_600M: 50.0,   # 180 km/h
}

MQ9_DETECTION_RADIUS_KM = 20.0  # MQ-9 detects enemy assets within 20 km

# Speed fraction per status
_STATUS_SPEED_MULT: dict[DroneStatus, float] = {
    DroneStatus.PATROLLING: 1.0,
    DroneStatus.SEARCHING:  0.5,
    DroneStatus.TRACKING:   0.8,
    DroneStatus.ENGAGING:   1.0,
    DroneStatus.RETURNING:  1.0,
}

_ARRIVE_THRESHOLD_KM = 0.5     # home arrival radius (500 m)
_PATROL_HEADING_DELTA = 2.0    # degrees/tick for MQ-9 orbit


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
        """Advance all non-idle drone positions one step."""
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
            if drone.status == DroneStatus.PATROLLING and drone.model in (DroneModel.MQ9_RECON, DroneModel.SCOUT_RECON):
                # Slow orbit: rotate heading each tick
                new_heading = (drone.heading + _PATROL_HEADING_DELTA) % 360
            elif drone.status == DroneStatus.SEARCHING and drone.swarm_id:
                # If inside the swarm's area_of_interest, switch to patrolling
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
                        new_heading = drone.heading  # keep heading toward region center
                else:
                    new_heading = drone.heading
            elif drone.status in (DroneStatus.TRACKING, DroneStatus.ENGAGING):
                # Steer toward assigned swarm target if available
                new_heading = drone.heading
                if drone.swarm_id:
                    swarm = state_service.get_swarm(drone.swarm_id)
                    if swarm and swarm.target_ids:
                        target = state_service.get_target(swarm.target_ids[0])
                        if target and target.position:
                            new_heading = _bearing(drone.position, target.position)
            else:
                new_heading = drone.heading  # searching / other: keep heading

            # ── Advance position ─────────────────────────────────────────────
            mult = _STATUS_SPEED_MULT.get(drone.status, 0.5)
            eff_speed = speed * mult
            new_pos = _advance(drone.position, new_heading, eff_speed, DT)
            delta_km = eff_speed * DT / 1000

            state_service.update_drone(drone.id, {
                "position": new_pos,
                "heading": new_heading,
                "speed": eff_speed,
                "range_used_km": range_used + delta_km,
                "battery": max(0.0, drone.battery - 0.002),  # slow drain
            })

        # ── MQ-9 Auto-Detection (20 km radius) ──────────────────────────────────
        self._run_mq9_detection(state_service)

    def _run_mq9_detection(self, state_service) -> None:
        """
        Each patrolling MQ-9 detects enemy targets within 20 km and refreshes
        their last_seen timestamp, simulating continuous ISR coverage.
        """
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


movement_service = MovementService()
