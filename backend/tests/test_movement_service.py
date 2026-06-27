"""Tests for the drone movement simulator."""
from __future__ import annotations
import math
import pytest
from unittest.mock import MagicMock
from models.drone import Drone, DroneType, DroneModel, DroneStatus
from models.target import Position, Target, TargetType, TargetStatus
from services.movement_service import (
    MovementService, _advance, _distance_km, _bearing, DT,
    MQ9_DETECTION_RADIUS_KM, SCOUT_DETECTION_RADIUS_KM,
)


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
    return svc


def _make_drone(**kwargs):
    defaults = dict(
        name="Test-Drone",
        type=DroneType.SWARM_MEMBER,
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
        assert drone.speed == 42.0  # full speed for FPV

    def test_searching_drone_at_half_speed(self):
        drone = _make_drone(status=DroneStatus.SEARCHING, heading=0.0)
        state = _make_state([drone])
        self.svc.tick(state)
        assert abs(drone.speed - 21.0) < 1e-6  # 50% of 42

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
        from models.drone import Swarm, SwarmStatus
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
        tank = _make_target(type=TargetType.TANK, heading=90.0, speed=2.78)
        orig_lon = tank.position.lon
        state = _make_state([], targets=[tank])
        self.svc.tick(state)
        assert tank.position.lon > orig_lon

    def test_soldier_advances_along_heading(self):
        soldier = _make_target(type=TargetType.SOLDIER_UNIT, heading=90.0, speed=1.39)
        orig_lon = soldier.position.lon
        state = _make_state([], targets=[soldier])
        self.svc.tick(state)
        assert soldier.position.lon > orig_lon

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
        tank = _make_target(
            type=TargetType.TANK,
            position=Position(lat=25.0, lon=120.5, alt=0.0),
            heading=90.0,
            speed=2.78,
        )
        orig_ship_lon = ship.position.lon
        orig_tank_lon = tank.position.lon
        state = _make_state([], targets=[ship, tank])
        self.svc.tick(state)
        assert ship.position.lon > orig_ship_lon
        assert tank.position.lon > orig_tank_lon

    def test_detection_radii_match_config(self):
        assert MQ9_DETECTION_RADIUS_KM == 15.0
        assert SCOUT_DETECTION_RADIUS_KM == 10.0


class TestScoutPatrolRefill:
    def setup_method(self):
        self.svc = MovementService()

    def test_idle_scout_launched_when_below_max_in_flight(self):
        """When no scouts are patrolling, an idle scout is dispatched to the first patrol grid."""
        idle_scout = _make_drone(
            model=DroneModel.SCOUT_RECON,
            type=DroneType.RECON,
            status=DroneStatus.IDLE,
            position=Position(lat=25.0, lon=121.5, alt=0.0),
            home_position=Position(lat=25.0, lon=121.5, alt=0.0),
            max_range_km=150.0,
            current_task=None,
        )
        state = _make_state([idle_scout])
        self.svc.tick(state)
        assert idle_scout.status == DroneStatus.PATROLLING
        assert idle_scout.current_task is not None
        assert idle_scout.current_task.startswith("Grid patrol")

    def test_already_covered_grid_not_doubled(self):
        """A grid already being patrolled does not get a second scout assigned to it."""
        from services.state_service import SCOUT_PATROL_GRIDS
        g_lat, g_lon = SCOUT_PATROL_GRIDS[0]
        task = f"Grid patrol ({g_lat:.4f}°N, {g_lon:.4f}°E)"
        patrolling = _make_drone(
            model=DroneModel.SCOUT_RECON,
            type=DroneType.RECON,
            status=DroneStatus.PATROLLING,
            position=Position(lat=g_lat, lon=g_lon, alt=3000.0),
            home_position=Position(lat=25.0, lon=121.5, alt=0.0),
            max_range_km=150.0,
            current_task=task,
        )
        idle_scout = _make_drone(
            model=DroneModel.SCOUT_RECON,
            type=DroneType.RECON,
            status=DroneStatus.IDLE,
            position=Position(lat=25.0, lon=121.5, alt=0.0),
            home_position=Position(lat=25.0, lon=121.5, alt=0.0),
            max_range_km=150.0,
            current_task=None,
        )
        from services.config_service import assets_config
        max_in_flight = assets_config["scout_recon"].get("max_in_flight", 20)
        if len(SCOUT_PATROL_GRIDS) >= max_in_flight:
            # Only one grid open; already covered → idle scout stays idle
            state = _make_state([patrolling, idle_scout])
            # Patch max_in_flight to 1 for this assertion
            orig = assets_config["scout_recon"]["max_in_flight"]
            assets_config["scout_recon"]["max_in_flight"] = 1
            try:
                self.svc._refill_scout_patrols(state)
            finally:
                assets_config["scout_recon"]["max_in_flight"] = orig
            assert idle_scout.status == DroneStatus.IDLE

    def test_returned_scout_triggers_replacement(self):
        """When a scout arrives home (goes IDLE), refill sends a new scout to its grid."""
        from services.state_service import SCOUT_PATROL_GRIDS
        g_lat, g_lon = SCOUT_PATROL_GRIDS[0]
        task = f"Grid patrol ({g_lat:.4f}°N, {g_lon:.4f}°E)"
        # Scout just returned home — now IDLE, grid is uncovered
        returned = _make_drone(
            model=DroneModel.SCOUT_RECON,
            type=DroneType.RECON,
            status=DroneStatus.IDLE,
            position=Position(lat=25.0, lon=121.5, alt=0.0),
            home_position=Position(lat=25.0, lon=121.5, alt=0.0),
            max_range_km=150.0,
            current_task=task,
        )
        state = _make_state([returned])
        self.svc._refill_scout_patrols(state)
        assert returned.status == DroneStatus.PATROLLING
        assert returned.range_used_km == 0.0
