"""Tests for the drone movement simulator."""
from __future__ import annotations
import math
import pytest
from unittest.mock import MagicMock, patch
from models.drone import Drone, DroneType, DroneModel, DroneStatus, Swarm, SwarmStatus
from models.target import Position, Target, TargetType, TargetStatus
import services.movement_service as msvc
from services.movement_service import (
    MovementService, _advance, _distance_km, _bearing, DT,
    MQ9_DETECTION_RADIUS_KM, SCOUT_DETECTION_RADIUS_KM, CONTACT_RADIUS_KM,
    TRACKING_STANDOFF_KM,
    _terrain_blocks, _GROUND_ASSET_TYPES, _is_land,
)
from services.terrain_service import _point_in_ring


# ─── Unit helpers ─────────────────────────────────────────────────────────────

class TestHelpers:
    def test_advance_north(self):
        pos = Position(lat=25.0, lon=121.0, alt=100.0)
        new_pos = _advance(pos, heading_deg=0.0, speed_ms=60.0, dt=1.0)
        assert new_pos.lat > pos.lat
        assert abs(new_pos.lon - pos.lon) < 1e-8

    def test_advance_east(self):
        pos = Position(lat=25.0, lon=121.0, alt=100.0)
        new_pos = _advance(pos, heading_deg=90.0, speed_ms=60.0, dt=1.0)
        assert abs(new_pos.lat - pos.lat) < 1e-6
        assert new_pos.lon > pos.lon

    def test_advance_preserves_altitude(self):
        pos = Position(lat=25.0, lon=121.0, alt=6000.0)
        new_pos = _advance(pos, heading_deg=45.0, speed_ms=60.0, dt=1.0)
        assert new_pos.alt == 6000.0

    def test_distance_km_self_is_zero(self):
        pos = Position(lat=25.0, lon=121.0, alt=0.0)
        assert _distance_km(pos, pos) < 1e-9

    def test_distance_km_approx(self):
        a = Position(lat=25.0, lon=121.0, alt=0.0)
        b = Position(lat=25.0, lon=122.0, alt=0.0)  # ~1° lon ≈ 100 km
        dist = _distance_km(a, b)
        assert 90 < dist < 110

    def test_bearing_east(self):
        a = Position(lat=25.0, lon=121.0, alt=0.0)
        b = Position(lat=25.0, lon=122.0, alt=0.0)
        assert abs(_bearing(a, b) - 90.0) < 1.0

    def test_bearing_north(self):
        a = Position(lat=25.0, lon=121.0, alt=0.0)
        b = Position(lat=26.0, lon=121.0, alt=0.0)
        assert abs(_bearing(a, b) - 0.0) < 1.0

    def test_bearing_south(self):
        a = Position(lat=25.0, lon=121.0, alt=0.0)
        b = Position(lat=24.0, lon=121.0, alt=0.0)
        assert abs(_bearing(a, b) - 180.0) < 1.0


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_state(drones, targets=None, swarms=None):
    """Build a minimal mock state_service for movement tests."""
    svc = MagicMock()
    drone_map = {d.id: d for d in drones}
    target_map = {t.id: t for t in (targets or [])}
    swarm_map = {s.id: s for s in (swarms or [])}

    svc.get_all_drones.return_value = list(drones)
    svc.get_all_targets.return_value = list(targets or [])
    svc.get_all_swarms.return_value = list(swarms or [])
    svc.get_drone.side_effect = lambda did: drone_map.get(did)
    svc.get_target.side_effect = lambda tid: target_map.get(tid)
    svc.get_swarm.side_effect = lambda sid: swarm_map.get(sid)

    # Capture update_drone calls and actually apply them to drone objects
    def update_drone(drone_id, updates):
        d = drone_map.get(drone_id)
        if d:
            for k, v in updates.items():
                setattr(d, k, v)
        return d
    svc.update_drone.side_effect = update_drone

    # update_swarm_status applies status to the swarm object
    def update_swarm_status(swarm_id, new_status, objective=None):
        s = swarm_map.get(swarm_id)
        if s:
            s.status = new_status
            if objective is not None:
                s.objective = objective
        return bool(s)
    svc.update_swarm_status.side_effect = update_swarm_status

    # mark_target_destroyed sets target.status to DESTROYED
    def mark_target_destroyed(tid):
        t = target_map.get(tid)
        if t:
            t.status = TargetStatus.DESTROYED
        return bool(t)
    svc.mark_target_destroyed.side_effect = mark_target_destroyed

    return svc


def _make_drone(**kwargs):
    defaults = dict(
        name="Test-Drone",
        type=DroneType.COMBAT_SWARM,
        model=DroneModel.FPV_COMBAT,
        position=Position(lat=25.0, lon=121.0, alt=150.0),
        home_position=Position(lat=25.0, lon=121.0, alt=0.0),
        heading=0.0,
        speed=42.0,
        status=DroneStatus.SEARCHING,
        battery=100.0,
        max_range_km=15.0,
        range_used_km=0.0,
        swarm_id=None,
    )
    defaults.update(kwargs)
    return Drone(**defaults)


# ─── Movement tick tests ───────────────────────────────────────────────────────

class TestMovementTick:
    def setup_method(self):
        self.svc = MovementService()

    def test_idle_drone_does_not_move(self):
        drone = _make_drone(status=DroneStatus.IDLE)
        state = _make_state([drone])
        orig_pos = (drone.position.lat, drone.position.lon)
        self.svc.tick(state)
        state.update_drone.assert_not_called()

    def test_offline_drone_does_not_move(self):
        drone = _make_drone(status=DroneStatus.OFFLINE)
        state = _make_state([drone])
        self.svc.tick(state)
        state.update_drone.assert_not_called()

    def test_drone_without_position_skipped(self):
        drone = _make_drone(status=DroneStatus.SEARCHING, position=None)
        state = _make_state([drone])
        self.svc.tick(state)
        state.update_drone.assert_not_called()

    def test_searching_drone_advances_position(self):
        drone = _make_drone(status=DroneStatus.SEARCHING, heading=0.0)
        orig_lat = drone.position.lat
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.position.lat > orig_lat

    def test_engaging_drone_advances_at_full_speed(self):
        drone = _make_drone(status=DroneStatus.ENGAGING, heading=0.0)
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.speed == pytest.approx(60.0 / 3.6)  # full speed for FPV

    def test_searching_drone_at_half_speed(self):
        drone = _make_drone(status=DroneStatus.SEARCHING, heading=0.0)
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.speed == pytest.approx(60.0 / 3.6 * 0.5)  # 50% of FPV max speed

    def test_range_accumulates_each_tick(self):
        drone = _make_drone(status=DroneStatus.SEARCHING, heading=0.0, range_used_km=0.0)
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.range_used_km > 0.0

    def test_battery_drains_each_tick(self):
        drone = _make_drone(status=DroneStatus.SEARCHING, battery=100.0)
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.battery < 100.0

    def test_range_exceeded_triggers_returning(self):
        drone = _make_drone(status=DroneStatus.SEARCHING, max_range_km=0.01, range_used_km=0.01)
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.status == DroneStatus.RETURNING

    def test_fpv_engaging_at_max_range_goes_offline(self):
        """FPV drones expend themselves (one-way strike) when range is consumed while engaging."""
        drone = _make_drone(
            model=DroneModel.FPV_COMBAT,
            status=DroneStatus.ENGAGING,
            max_range_km=0.01,
            range_used_km=0.01,
        )
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.status == DroneStatus.OFFLINE

    def test_altius_engaging_at_max_range_returns(self):
        """Altius-600M returns to base when range is consumed (not expended)."""
        drone = _make_drone(
            model=DroneModel.ALTIUS_600M,
            status=DroneStatus.ENGAGING,
            max_range_km=0.01,
            range_used_km=0.01,
        )
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.status == DroneStatus.RETURNING


class TestReturningDrone:
    def setup_method(self):
        self.svc = MovementService()

    def test_returning_drone_moves_toward_home(self):
        home = Position(lat=25.0, lon=121.0, alt=0.0)
        drone = _make_drone(
            status=DroneStatus.RETURNING,
            position=Position(lat=25.10, lon=121.0, alt=150.0),
            home_position=home,
        )
        state = _make_state([drone])
        self.svc.tick(state)
        # Should be closer to home after one tick
        assert drone.position.lat < 25.10

    def test_returning_drone_arrives_home(self):
        home = Position(lat=25.0, lon=121.0, alt=0.0)
        drone = _make_drone(
            status=DroneStatus.RETURNING,
            position=Position(lat=25.001, lon=121.0, alt=100.0),  # ~110 m away
            home_position=home,
            range_used_km=5.0,
        )
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.status == DroneStatus.IDLE
        assert drone.range_used_km == 0.0

    def test_returning_drone_without_home_skipped(self):
        drone = _make_drone(status=DroneStatus.RETURNING, home_position=None)
        state = _make_state([drone])
        orig_pos = (drone.position.lat, drone.position.lon)
        self.svc.tick(state)
        assert (drone.position.lat, drone.position.lon) == orig_pos


class TestMQ9Patrol:
    def setup_method(self):
        self.svc = MovementService()

    def test_mq9_heading_increments_each_tick(self):
        drone = _make_drone(
            model=DroneModel.MQ9_RECON,
            type=DroneType.RECON,
            status=DroneStatus.PATROLLING,
            heading=10.0,
            max_range_km=1900.0,
        )
        state = _make_state([drone])
        self.svc.tick(state)
        assert abs(drone.heading - 12.0) < 1e-6

    def test_mq9_heading_wraps_at_360(self):
        drone = _make_drone(
            model=DroneModel.MQ9_RECON,
            type=DroneType.RECON,
            status=DroneStatus.PATROLLING,
            heading=359.0,
            max_range_km=1900.0,
        )
        state = _make_state([drone])
        self.svc.tick(state)
        assert drone.heading == 1.0


class TestTrackingTowardTarget:
    def setup_method(self):
        self.svc = MovementService()

    def test_tracking_drone_steers_toward_target(self):
        """Drone in tracking status should point toward swarm target."""
        target = Target(
            type=TargetType.TANK,
            position=Position(lat=25.0, lon=122.0, alt=0.0),  # east of drone
            confidence=0.9,
            status=TargetStatus.ACTIVE,
        )
        swarm = Swarm(name="T-Swarm", target_ids=[target.id])
        drone = _make_drone(
            status=DroneStatus.TRACKING,
            heading=0.0,
            swarm_id=swarm.id,
        )
        state = _make_state([drone], targets=[target], swarms=[swarm])
        self.svc.tick(state)
        # Heading should be ~90° (east toward target at higher lon)
        assert 80 < drone.heading < 100


# ─── Feature 28: recon drone 10 km standoff orbit ─────────────────────────────

def _make_recon_drone_at_dist_km(dist_km: float, target_pos: Position, **kwargs) -> "Drone":
    """Place a Scout recon drone due north of target_pos at exactly dist_km away."""
    drone_lat = target_pos.lat + dist_km / 111.32
    return _make_drone(
        model=DroneModel.SCOUT_RECON,
        type=DroneType.RECON,
        status=DroneStatus.TRACKING,
        position=Position(lat=drone_lat, lon=target_pos.lon, alt=500.0),
        home_position=Position(lat=drone_lat + 0.5, lon=target_pos.lon, alt=0.0),
        heading=180.0,  # pointing south (toward target)
        max_range_km=150.0,
        range_used_km=0.0,
        swarm_id=None,
        **kwargs,
    )


class TestTrackingStandoff:
    """Feature 28: recon drone holds 10 km standoff when within TRACKING_STANDOFF_KM of its target."""

    def setup_method(self):
        self.svc = MovementService()

    def _make_recon_state(self, dist_km: float):
        target = Target(
            type=TargetType.SHIP,
            position=Position(lat=24.0, lon=119.8, alt=0.0),
            confidence=0.9,
            status=TargetStatus.ACTIVE,
            speed=0.0,
            heading=0.0,
        )
        drone = _make_recon_drone_at_dist_km(dist_km, target.position, tracking_target_id=target.id)
        state = _make_state([drone], targets=[target])
        return state, drone, target

    def test_standoff_constant_is_10km(self):
        assert TRACKING_STANDOFF_KM == 10.0

    def test_drone_beyond_standoff_advances_toward_target(self):
        """A tracking drone more than 10 km away should close on the target."""
        state, drone, target = self._make_recon_state(dist_km=15.0)
        orig_lat = drone.position.lat
        self.svc.tick(state)
        assert drone.position.lat < orig_lat  # moved south toward target

    def test_drone_within_standoff_does_not_advance(self):
        """A tracking drone within 10 km must hold its position (Feature 28)."""
        state, drone, target = self._make_recon_state(dist_km=8.0)
        orig_pos = (drone.position.lat, drone.position.lon)
        self.svc.tick(state)
        assert (drone.position.lat, drone.position.lon) == orig_pos

    def test_drone_near_standoff_boundary_does_not_advance(self):
        """A drone just inside the standoff boundary (9.99 km) must also hold."""
        state, drone, target = self._make_recon_state(dist_km=9.99)
        orig_pos = (drone.position.lat, drone.position.lon)
        self.svc.tick(state)
        assert (drone.position.lat, drone.position.lon) == orig_pos

    def test_drone_within_standoff_faces_target(self):
        """Heading must still be updated toward the target when holding."""
        state, drone, target = self._make_recon_state(dist_km=8.0)
        drone.heading = 0.0  # start facing north, away from target
        self.svc.tick(state)
        # Target is due south, so heading should be ~180°
        assert 170 < drone.heading < 190

    def test_drone_within_standoff_speed_is_zero(self):
        """Speed must be 0 when holding at standoff."""
        state, drone, target = self._make_recon_state(dist_km=8.0)
        self.svc.tick(state)
        assert drone.speed == 0.0

    def test_drone_within_standoff_battery_drains(self):
        """Battery still drains while hovering at standoff."""
        state, drone, target = self._make_recon_state(dist_km=8.0)
        drone.battery = 100.0
        self.svc.tick(state)
        assert drone.battery < 100.0

    def test_drone_within_standoff_range_not_accumulated(self):
        """Range budget must not accumulate while the drone is stationary."""
        state, drone, target = self._make_recon_state(dist_km=8.0)
        drone.range_used_km = 5.0
        self.svc.tick(state)
        assert drone.range_used_km == 5.0

    def test_engaging_drone_within_10km_is_not_held(self):
        """Feature 28 applies only to TRACKING drones; ENGAGING drones must keep closing."""
        target = Target(
            type=TargetType.SHIP,
            position=Position(lat=24.0, lon=119.8, alt=0.0),
            confidence=0.9,
            status=TargetStatus.ACTIVE,
            speed=0.0,
            heading=0.0,
        )
        drone_lat = target.position.lat + 8.0 / 111.32  # 8 km away
        drone = _make_drone(
            model=DroneModel.ALTIUS_600M,
            status=DroneStatus.ENGAGING,
            position=Position(lat=drone_lat, lon=119.8, alt=200.0),
            heading=180.0,
            max_range_km=440.0,
            range_used_km=0.0,
            swarm_id="sw-engage",
        )
        swarm = Swarm(
            id="sw-engage", name="ALT-Alpha",
            drone_ids=[drone.id], target_ids=[target.id],
            status=SwarmStatus.ENGAGING,
        )
        state = _make_state([drone], targets=[target], swarms=[swarm])
        orig_lat = drone.position.lat
        self.svc.tick(state)
        # Engaging drone must advance (or be destroyed on contact — either way not held)
        assert drone.position.lat != orig_lat or drone.status == DroneStatus.OFFLINE


# ─── Enemy Asset Movement (§8.8) ─────────────────────────────────────────────

def _make_target(**kwargs) -> Target:
    defaults = dict(
        type=TargetType.SHIP,
        position=Position(lat=24.0, lon=119.5, alt=0.0),
        heading=90.0,
        speed=11.3,   # 22 knots in m/s
        confidence=0.9,
        status=TargetStatus.ACTIVE,
    )
    defaults.update(kwargs)
    return Target(**defaults)


class TestEnemyMovement:
    def setup_method(self):
        self.svc = MovementService()

    def test_ship_advances_eastward(self):
        ship = _make_target(type=TargetType.SHIP, heading=90.0, speed=11.3)
        orig_lon = ship.position.lon
        state = _make_state([], targets=[ship])
        self.svc.tick(state)
        assert ship.position.lon > orig_lon

    def test_tank_advances_along_heading(self):
        # Place tank on land (inland Taiwan: 25°N, 121.5°E) so terrain allows movement
        tank = _make_target(
            type=TargetType.TANK,
            position=Position(lat=25.0, lon=121.5, alt=0.0),
            heading=270.0,  # heading west (deeper inland)
            speed=2.78,
        )
        orig_lon = tank.position.lon
        state = _make_state([], targets=[tank])
        self.svc.tick(state)
        assert tank.position.lon < orig_lon

    def test_soldier_advances_along_heading(self):
        # Place soldier on land (inland Taiwan) so terrain allows movement
        soldier = _make_target(
            type=TargetType.SOLDIER_UNIT,
            position=Position(lat=25.0, lon=121.5, alt=0.0),
            heading=270.0,  # heading west (deeper inland)
            speed=1.39,
        )
        orig_lon = soldier.position.lon
        state = _make_state([], targets=[soldier])
        self.svc.tick(state)
        assert soldier.position.lon < orig_lon

    def test_missile_launcher_stationary(self):
        ml = _make_target(type=TargetType.MISSILE_LAUNCHER, heading=0.0, speed=0.0)
        orig_lat = ml.position.lat
        orig_lon = ml.position.lon
        state = _make_state([], targets=[ml])
        self.svc.tick(state)
        assert ml.position.lat == orig_lat
        assert ml.position.lon == orig_lon

    def test_destroyed_target_does_not_move(self):
        ship = _make_target(type=TargetType.SHIP, speed=11.3, status=TargetStatus.DESTROYED)
        orig_lon = ship.position.lon
        state = _make_state([], targets=[ship])
        self.svc.tick(state)
        assert ship.position.lon == orig_lon

    def test_lost_target_does_not_move(self):
        ship = _make_target(type=TargetType.SHIP, speed=11.3, status=TargetStatus.LOST)
        orig_lon = ship.position.lon
        state = _make_state([], targets=[ship])
        self.svc.tick(state)
        assert ship.position.lon == orig_lon

    def test_long_range_drone_high_altitude_advances(self):
        lr_drone = _make_target(
            type=TargetType.DRONE,
            position=Position(lat=24.0, lon=120.0, alt=3000.0),
            heading=90.0,
            speed=41.7,
        )
        orig_lon = lr_drone.position.lon
        state = _make_state([], targets=[lr_drone])
        self.svc.tick(state)
        assert lr_drone.position.lon > orig_lon

    def test_enemy_fpv_drone_low_altitude_rotates_heading(self):
        fpv = _make_target(
            type=TargetType.DRONE,
            position=Position(lat=25.0, lon=120.7, alt=50.0),
            heading=0.0,
            speed=41.7,
        )
        state = _make_state([], targets=[fpv])
        self.svc.tick(state)
        # Heading should have rotated by _FPV_PATROL_HEADING_DELTA (3°)
        assert abs(fpv.heading - 3.0) < 1e-6

    def test_high_altitude_drone_heading_unchanged(self):
        lr_drone = _make_target(
            type=TargetType.DRONE,
            position=Position(lat=24.0, lon=120.0, alt=3000.0),
            heading=90.0,
            speed=41.7,
        )
        state = _make_state([], targets=[lr_drone])
        self.svc.tick(state)
        # High-altitude drones keep their heading
        assert abs(lr_drone.heading - 90.0) < 1e-6

    def test_multiple_enemy_targets_all_advance(self):
        ship = _make_target(type=TargetType.SHIP, heading=90.0, speed=11.3)
        # Tank on inland Taiwan (land) heading west so it stays on land
        tank = _make_target(
            type=TargetType.TANK,
            position=Position(lat=25.0, lon=121.5, alt=0.0),
            heading=270.0,
            speed=2.78,
        )
        orig_ship_lon = ship.position.lon
        orig_tank_lon = tank.position.lon
        state = _make_state([], targets=[ship, tank])
        self.svc.tick(state)
        assert ship.position.lon > orig_ship_lon
        assert tank.position.lon < orig_tank_lon

    def test_detection_radii_match_config(self):
        assert MQ9_DETECTION_RADIUS_KM == 15.0
        assert SCOUT_DETECTION_RADIUS_KM == 10.0


# ─── Feature 23: combat-on-contact destruction ────────────────────────────────

def _make_engaging_swarm_state(drone_dist_km: float, swarm_status: SwarmStatus = SwarmStatus.ENGAGING):
    """Return (state, drone, target, swarm) with the drone `drone_dist_km` from the target."""
    target = _make_target(
        type=TargetType.SHIP,
        position=Position(lat=24.0, lon=119.8, alt=0.0),
        status=TargetStatus.ACTIVE,
        speed=0.0,
        heading=0.0,
    )
    # Place the drone due north of the target at the specified distance
    drone_lat = target.position.lat + drone_dist_km / 111.32
    drone = _make_drone(
        model=DroneModel.ALTIUS_600M,
        status=DroneStatus.ENGAGING,
        position=Position(lat=drone_lat, lon=119.8, alt=200.0),
        swarm_id="swarm-contact-1",
        max_range_km=440.0,
    )
    swarm = Swarm(
        id="swarm-contact-1",
        name="ALT-Alpha",
        drone_ids=[drone.id],
        target_ids=[target.id],
        status=swarm_status,
    )
    state = _make_state([drone], targets=[target], swarms=[swarm])
    return state, drone, target, swarm


class TestCombatContact:
    """Feature 23: combat swarm destroys target and expends itself on contact."""

    def setup_method(self):
        self.svc = MovementService()

    def test_contact_radius_is_500m(self):
        assert abs(CONTACT_RADIUS_KM - 0.5) < 1e-9

    def test_contact_marks_target_destroyed(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        self.svc.tick(state)
        assert target.status == TargetStatus.DESTROYED

    def test_contact_sets_drones_offline(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        self.svc.tick(state)
        assert drone.status == DroneStatus.OFFLINE

    def test_contact_sets_drone_speed_to_zero(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        self.svc.tick(state)
        assert drone.speed == 0.0

    def test_contact_resets_swarm_to_idle(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        self.svc.tick(state)
        assert swarm.status == SwarmStatus.IDLE

    def test_contact_clears_swarm_target_ids(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        self.svc.tick(state)
        assert swarm.target_ids == []

    def test_contact_clears_swarm_objective(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        swarm.objective = "destroy ship"
        self.svc.tick(state)
        assert swarm.objective is None

    def test_beyond_contact_radius_no_destruction(self):
        """A drone 1 km away (> 500 m) must not trigger contact."""
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=1.0)
        self.svc.tick(state)
        assert target.status == TargetStatus.ACTIVE

    def test_beyond_contact_radius_drone_stays_engaging(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=1.0)
        self.svc.tick(state)
        assert drone.status == DroneStatus.ENGAGING

    def test_already_destroyed_target_skipped(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        target.status = TargetStatus.DESTROYED
        self.svc.tick(state)
        state.mark_target_destroyed.assert_not_called()

    def test_non_engaging_swarm_not_checked(self):
        """Swarm in TRACKING status must not trigger combat contact."""
        state, drone, target, swarm = _make_engaging_swarm_state(
            drone_dist_km=0.3, swarm_status=SwarmStatus.TRACKING
        )
        drone.status = DroneStatus.TRACKING
        self.svc.tick(state)
        assert target.status == TargetStatus.ACTIVE

    def test_multiple_drones_contact_on_first_in_range(self):
        """Contact triggers as long as at least one drone is within radius."""
        target = _make_target(
            type=TargetType.TANK,
            position=Position(lat=24.0, lon=119.8, alt=0.0),
            status=TargetStatus.ACTIVE,
            speed=0.0,
            heading=0.0,
        )
        # Drone 1 is far (2 km), drone 2 is close (0.2 km)
        far_lat  = target.position.lat + 2.0 / 111.32
        near_lat = target.position.lat + 0.2 / 111.32
        d1 = _make_drone(model=DroneModel.ALTIUS_600M, status=DroneStatus.ENGAGING,
                         position=Position(lat=far_lat,  lon=119.8, alt=200.0),
                         swarm_id="sw-multi", max_range_km=440.0)
        d2 = _make_drone(model=DroneModel.ALTIUS_600M, status=DroneStatus.ENGAGING,
                         position=Position(lat=near_lat, lon=119.8, alt=200.0),
                         swarm_id="sw-multi", max_range_km=440.0)
        swarm = Swarm(
            id="sw-multi", name="ALT-Beta",
            drone_ids=[d1.id, d2.id], target_ids=[target.id],
            status=SwarmStatus.ENGAGING,
        )
        state = _make_state([d1, d2], targets=[target], swarms=[swarm])
        self.svc.tick(state)
        assert target.status == TargetStatus.DESTROYED
        assert d1.status == DroneStatus.OFFLINE
        assert d2.status == DroneStatus.OFFLINE

    def test_logs_combat_contact_event(self):
        state, drone, target, swarm = _make_engaging_swarm_state(drone_dist_km=0.3)
        self.svc.tick(state)
        state.log_command.assert_called()
        call_kwargs = state.log_command.call_args[0][0]
        assert call_kwargs["type"] == "combat_contact"
        assert call_kwargs["target_id"] == target.id
        assert call_kwargs["swarm_id"] == swarm.id
        assert call_kwargs["drones_destroyed"] == len(swarm.drone_ids)

    def test_entire_swarm_destroyed_including_non_contact_drones(self):
        """Feature 23: ALL drones in the swarm go offline on contact, even those not in range."""
        target = _make_target(
            type=TargetType.SHIP,
            position=Position(lat=24.0, lon=119.8, alt=0.0),
            status=TargetStatus.ACTIVE,
            speed=0.0,
            heading=0.0,
        )
        # d_near is within contact radius; d_far is 10 km away
        near_lat = target.position.lat + 0.2 / 111.32
        far_lat  = target.position.lat + 10.0 / 111.32
        d_near = _make_drone(
            model=DroneModel.ALTIUS_600M, status=DroneStatus.ENGAGING,
            position=Position(lat=near_lat, lon=119.8, alt=200.0),
            swarm_id="sw-entire", max_range_km=440.0,
        )
        d_far = _make_drone(
            model=DroneModel.ALTIUS_600M, status=DroneStatus.ENGAGING,
            position=Position(lat=far_lat, lon=119.8, alt=200.0),
            swarm_id="sw-entire", max_range_km=440.0,
        )
        d_returning = _make_drone(
            model=DroneModel.ALTIUS_600M, status=DroneStatus.RETURNING,
            position=Position(lat=far_lat, lon=119.9, alt=200.0),
            swarm_id="sw-entire", max_range_km=440.0,
        )
        swarm = Swarm(
            id="sw-entire", name="ALT-Alpha",
            drone_ids=[d_near.id, d_far.id, d_returning.id],
            target_ids=[target.id],
            status=SwarmStatus.ENGAGING,
        )
        state = _make_state([d_near, d_far, d_returning], targets=[target], swarms=[swarm])
        self.svc.tick(state)
        # Entire swarm destroyed — no drones survive or return
        assert d_near.status == DroneStatus.OFFLINE
        assert d_far.status == DroneStatus.OFFLINE
        assert d_returning.status == DroneStatus.OFFLINE
        assert state.log_command.call_args[0][0]["drones_destroyed"] == 3


# ─── Feature 21: terrain-constrained movement ────────────────────────────────

class TestTerrainConstraints:
    """Feature 21: ground assets halt at water; ships halt at shore; drones unconstrained."""

    def setup_method(self):
        self.svc = MovementService()

    # ── _terrain_blocks unit tests ──────────────────────────────────────────

    def test_ground_types_set_contains_expected_types(self):
        assert TargetType.SOLDIER_UNIT in _GROUND_ASSET_TYPES
        assert TargetType.TANK in _GROUND_ASSET_TYPES
        assert TargetType.MISSILE_LAUNCHER in _GROUND_ASSET_TYPES
        assert TargetType.SHIP not in _GROUND_ASSET_TYPES
        assert TargetType.DRONE not in _GROUND_ASSET_TYPES

    # ── polygon sanity checks (known coordinates) ──────────────────────────

    def test_taipei_is_land(self):
        # Taipei (25.0°N, 121.5°E) is clearly on Taiwan island
        assert _is_land(25.0, 121.5) is True

    def test_taiwan_strait_is_sea(self):
        # 24°N, 119.5°E is open water in the Taiwan Strait
        assert _is_land(24.0, 119.5) is False

    def test_fujian_coast_is_land(self):
        # Fuzhou city (26.09°N, 119.30°E) is clearly on the Fujian mainland
        assert _is_land(26.09, 119.30) is True

    def test_pacific_east_of_taiwan_is_sea(self):
        # 24°N, 123°E is the Pacific Ocean east of Taiwan
        assert _is_land(24.0, 123.0) is False

    def test_point_in_ring_basic(self):
        # Simple square ring [lon, lat] — verifies the ray-casting implementation
        square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        assert _point_in_ring(0.5, 0.5, square) is True
        assert _point_in_ring(1.5, 0.5, square) is False

    def test_terrain_blocks_ground_when_next_pos_is_water(self):
        pos = Position(lat=24.0, lon=119.5, alt=0.0)
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=False):
            assert _terrain_blocks(TargetType.TANK, pos) is True
            assert _terrain_blocks(TargetType.SOLDIER_UNIT, pos) is True
            assert _terrain_blocks(TargetType.MISSILE_LAUNCHER, pos) is True

    def test_terrain_allows_ground_when_next_pos_is_land(self):
        pos = Position(lat=25.0, lon=121.5, alt=0.0)
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=True):
            assert _terrain_blocks(TargetType.TANK, pos) is False
            assert _terrain_blocks(TargetType.SOLDIER_UNIT, pos) is False
            assert _terrain_blocks(TargetType.MISSILE_LAUNCHER, pos) is False

    def test_terrain_blocks_ship_when_next_pos_is_land(self):
        pos = Position(lat=25.0, lon=121.5, alt=0.0)
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=True):
            assert _terrain_blocks(TargetType.SHIP, pos) is True

    def test_terrain_allows_ship_when_next_pos_is_water(self):
        pos = Position(lat=24.0, lon=119.5, alt=0.0)
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=False):
            assert _terrain_blocks(TargetType.SHIP, pos) is False

    def test_terrain_never_blocks_drone(self):
        pos = Position(lat=25.0, lon=121.5, alt=3000.0)
        with patch.object(msvc, '_TERRAIN_ENABLED', True):
            # Drones are unconstrained regardless of land/sea result
            with patch.object(msvc, '_is_land', return_value=True):
                assert _terrain_blocks(TargetType.DRONE, pos) is False
            with patch.object(msvc, '_is_land', return_value=False):
                assert _terrain_blocks(TargetType.DRONE, pos) is False

    def test_terrain_disabled_never_blocks_anything(self):
        pos = Position(lat=25.0, lon=121.5, alt=0.0)
        with patch.object(msvc, '_TERRAIN_ENABLED', False):
            assert _terrain_blocks(TargetType.TANK, pos) is False
            assert _terrain_blocks(TargetType.SHIP, pos) is False
            assert _terrain_blocks(TargetType.SOLDIER_UNIT, pos) is False

    # ── integration: terrain blocking in tick ──────────────────────────────

    def test_tank_halts_when_next_pos_is_water(self):
        tank = _make_target(
            type=TargetType.TANK,
            position=Position(lat=25.0, lon=121.9, alt=0.0),
            heading=90.0,  # heading east toward shore
            speed=2.78,
        )
        orig_pos = (tank.position.lat, tank.position.lon)
        state = _make_state([], targets=[tank])
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=False):
            self.svc.tick(state)
        assert (tank.position.lat, tank.position.lon) == orig_pos

    def test_tank_advances_when_next_pos_is_land(self):
        tank = _make_target(
            type=TargetType.TANK,
            position=Position(lat=25.0, lon=121.5, alt=0.0),
            heading=270.0,
            speed=2.78,
        )
        orig_lon = tank.position.lon
        state = _make_state([], targets=[tank])
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=True):
            self.svc.tick(state)
        assert tank.position.lon < orig_lon

    def test_soldier_halts_when_next_pos_is_water(self):
        soldier = _make_target(
            type=TargetType.SOLDIER_UNIT,
            position=Position(lat=25.0, lon=121.9, alt=0.0),
            heading=90.0,
            speed=1.39,
        )
        orig_pos = (soldier.position.lat, soldier.position.lon)
        state = _make_state([], targets=[soldier])
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=False):
            self.svc.tick(state)
        assert (soldier.position.lat, soldier.position.lon) == orig_pos

    def test_ship_halts_when_next_pos_is_land(self):
        ship = _make_target(
            type=TargetType.SHIP,
            position=Position(lat=24.0, lon=119.8, alt=0.0),
            heading=90.0,
            speed=11.3,
        )
        orig_pos = (ship.position.lat, ship.position.lon)
        state = _make_state([], targets=[ship])
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=True):
            self.svc.tick(state)
        assert (ship.position.lat, ship.position.lon) == orig_pos

    def test_ship_advances_when_next_pos_is_water(self):
        ship = _make_target(
            type=TargetType.SHIP,
            position=Position(lat=24.0, lon=119.5, alt=0.0),
            heading=90.0,
            speed=11.3,
        )
        orig_lon = ship.position.lon
        state = _make_state([], targets=[ship])
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=False):
            self.svc.tick(state)
        assert ship.position.lon > orig_lon

    def test_drone_advances_even_when_next_pos_is_land(self):
        drone = _make_target(
            type=TargetType.DRONE,
            position=Position(lat=24.0, lon=120.0, alt=3000.0),
            heading=90.0,
            speed=41.7,
        )
        orig_lon = drone.position.lon
        state = _make_state([], targets=[drone])
        with patch.object(msvc, '_TERRAIN_ENABLED', True), \
             patch.object(msvc, '_is_land', return_value=True):
            self.svc.tick(state)
        assert drone.position.lon > orig_lon

    def test_terrain_disabled_tank_advances_in_water(self):
        """When terrain library is absent, terrain constraints are skipped entirely."""
        tank = _make_target(
            type=TargetType.TANK,
            position=Position(lat=24.0, lon=119.5, alt=0.0),
            heading=90.0,
            speed=2.78,
        )
        orig_lon = tank.position.lon
        state = _make_state([], targets=[tank])
        with patch.object(msvc, '_TERRAIN_ENABLED', False):
            self.svc.tick(state)
        assert tank.position.lon > orig_lon  # no terrain blocking when disabled

