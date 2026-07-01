"""Unit tests for services/state_service.py"""
from __future__ import annotations

import threading
import time

import pytest

from models.target import Position, Target, TargetStatus, TargetType
from models.drone import Drone, DroneModel, DroneStatus, DroneType, Swarm, SwarmStatus
from services.state_service import StateService


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _svc() -> StateService:
    """Return a fresh (seeded) StateService for each test."""
    return StateService()


def _empty_svc() -> StateService:
    """Return a StateService with no seed data."""
    svc = StateService.__new__(StateService)
    svc._lock = threading.Lock()
    svc._targets = {}
    svc._drones = {}
    svc._swarms = {}
    svc._approvals = {}
    svc._command_log = []
    return svc


def _target(**kwargs) -> Target:
    defaults = dict(
        type=TargetType.TANK,
        position=Position(lat=34.05, lon=-118.24, alt=0.0),
        confidence=0.85,
    )
    defaults.update(kwargs)
    return Target(**defaults)


def _drone(**kwargs) -> Drone:
    defaults = dict(name="Test-1", type=DroneType.RECON)
    defaults.update(kwargs)
    return Drone(**defaults)


def _swarm(**kwargs) -> Swarm:
    defaults = dict(name="Test Swarm")
    defaults.update(kwargs)
    return Swarm(**defaults)


# ─── Seeded Demo Data ─────────────────────────────────────────────────────────

class TestSeedData:
    def test_seeded_recon_drones(self):
        svc = _svc()
        drones = svc.get_all_drones()
        mq9 = [d for d in drones if d.model == DroneModel.MQ9_RECON]
        assert len(mq9) == 4
        names = {d.name for d in mq9}
        assert names == {"MQ9-01", "MQ9-02", "MQ9-03", "MQ9-04"}

    def test_two_recon_drones_patrolling(self):
        svc = _svc()
        drones = svc.get_all_drones()
        patrolling = [d for d in drones if d.model == DroneModel.MQ9_RECON and d.status == DroneStatus.PATROLLING]
        assert len(patrolling) == 2

    def test_two_recon_drones_standby(self):
        svc = _svc()
        drones = svc.get_all_drones()
        standby = [d for d in drones if d.model == DroneModel.MQ9_RECON and d.status == DroneStatus.IDLE]
        assert len(standby) == 2

    def test_seeded_swarms(self):
        svc = _svc()
        swarms = svc.get_all_swarms()
        # 20 FPV swarms + 100 ALT swarms (initial seeding counts, §8.9)
        assert len(swarms) == 120
        names = {s.name for s in swarms}
        for fpv_name in ("FPV-Alpha", "FPV-Bravo", "FPV-Charlie", "FPV-Delta", "FPV-Echo"):
            assert fpv_name in names
        assert "ALT-001" in names
        assert "ALT-100" in names

    def test_fpv_swarm_total_drone_count(self):
        svc = _svc()
        fpv_alpha = next(s for s in svc.get_all_swarms() if s.name == "FPV-Alpha")
        assert fpv_alpha.total_drone_count == 2000

    def test_alt_swarm_total_drone_count(self):
        svc = _svc()
        alt_001 = next(s for s in svc.get_all_swarms() if s.name == "ALT-001")
        assert alt_001.total_drone_count == 2

    def test_each_swarm_has_one_representative_drone(self):
        svc = _svc()
        for swarm in svc.get_all_swarms():
            assert len(swarm.drone_ids) == 1

    def test_total_seeded_drones(self):
        svc = _svc()
        # 4 MQ-9 recon + 100 scout recon + 20 FPV + 100 ALT representative drones (§8.9)
        assert len(svc.get_all_drones()) == 224

    def test_no_targets_initially(self):
        svc = _svc()
        # 20 friendly soldier units + 10 enemy soldier units + 10 enemy FPV swarms
        # + 20 enemy long-range swarms + 10 tanks + 20 ships + 20 missile launchers (§8.9)
        assert len(svc.get_all_targets()) == 110

    def test_seeded_targets_have_both_affiliations(self):
        svc = _svc()
        targets = svc.get_all_targets()
        affiliations = {t.affiliation for t in targets}
        assert affiliations == {"friendly", "enemy"}
        friendly = [t for t in targets if t.affiliation == "friendly"]
        assert len(friendly) == 20
        assert all(t.type.value == "soldier_unit" for t in friendly)

    def test_enemy_fpv_drones_seeded_as_swarms(self):
        svc = _svc()
        fpv_swarms = [
            t for t in svc.get_all_targets()
            if t.affiliation == "enemy" and t.type.value == "drone" and t.swarm_size == 5
        ]
        assert len(fpv_swarms) == 10
        assert all(t.position.alt == 50.0 for t in fpv_swarms)

    def test_enemy_long_range_drones_seeded_as_swarms(self):
        svc = _svc()
        lr_swarms = [
            t for t in svc.get_all_targets()
            if t.affiliation == "enemy" and t.type.value == "drone" and t.swarm_size == 500
        ]
        assert len(lr_swarms) == 20
        assert all(t.speed == 0.0 for t in lr_swarms)  # stationary at spawn (Feature 33)

    def test_fpv_swarms_collocated_with_friendly_soldiers(self):
        svc = _svc()
        soldier_positions = {
            (round(t.position.lat, 4), round(t.position.lon, 4))
            for t in svc.get_all_targets() if t.affiliation == "friendly"
        }
        fpv_positions = {
            (round(d.position.lat, 4), round(d.position.lon, 4))
            for d in svc.get_all_drones() if d.model == DroneModel.FPV_COMBAT
        }
        assert fpv_positions.issubset(soldier_positions)

    def test_enemy_fpv_swarms_collocated_with_enemy_soldiers(self):
        svc = _svc()
        targets = svc.get_all_targets()
        soldier_positions = {
            (round(t.position.lat, 4), round(t.position.lon, 4))
            for t in targets if t.affiliation == "enemy" and t.type.value == "soldier_unit"
        }
        fpv_positions = {
            (round(t.position.lat, 4), round(t.position.lon, 4))
            for t in targets if t.affiliation == "enemy" and t.type.value == "drone" and t.swarm_size == 5
        }
        assert fpv_positions.issubset(soldier_positions)

    def test_seeded_ground_and_sea_assets_respect_terrain(self):
        """Feature 21: soldiers/tanks/missile launchers on land, ships in water."""
        from services.terrain_service import is_land

        svc = _svc()
        land_types = {"tank", "missile_launcher", "soldier_unit"}
        for t in svc.get_all_targets():
            if t.type.value in land_types:
                assert is_land(t.position.lat, t.position.lon), (
                    f"{t.type.value} ({t.affiliation}) seeded in water at "
                    f"({t.position.lat}, {t.position.lon})"
                )
            elif t.type.value == "ship":
                assert not is_land(t.position.lat, t.position.lon), (
                    f"ship seeded on land at ({t.position.lat}, {t.position.lon})"
                )

    def test_seeded_scout_drones(self):
        svc = _svc()
        scouts = [d for d in svc.get_all_drones() if d.model == DroneModel.SCOUT_RECON]
        assert len(scouts) == 100

    def test_all_scouts_start_idle(self):
        """All 100 scout drones start IDLE at their city home positions (Feature 33)."""
        svc = _svc()
        scouts = [d for d in svc.get_all_drones() if d.model == DroneModel.SCOUT_RECON]
        idle = [d for d in scouts if d.status == DroneStatus.IDLE]
        assert len(idle) == len(scouts)

    def test_scouts_only_idle_at_startup(self):
        svc = _svc()
        scouts = [d for d in svc.get_all_drones() if d.model == DroneModel.SCOUT_RECON]
        assert all(d.status == DroneStatus.IDLE for d in scouts)

    def test_scouts_have_home_position(self):
        svc = _svc()
        scouts = [d for d in svc.get_all_drones() if d.model == DroneModel.SCOUT_RECON]
        assert all(d.home_position is not None for d in scouts)

    def test_swarm_member_drones_linked_to_swarm(self):
        svc = _svc()
        fpv_alpha = next(s for s in svc.get_all_swarms() if s.name == "FPV-Alpha")
        for did in fpv_alpha.drone_ids:
            drone = svc.get_drone(did)
            assert drone is not None
            assert drone.swarm_id == fpv_alpha.id

    def test_fpv_drone_model_fields(self):
        svc = _svc()
        fpv_alpha = next(s for s in svc.get_all_swarms() if s.name == "FPV-Alpha")
        d = svc.get_drone(fpv_alpha.drone_ids[0])
        assert d.model.value == "fpv_combat"
        assert d.max_payload_kg == 4.0
        assert d.max_range_km == 15.0

    def test_alt_drone_model_fields(self):
        svc = _svc()
        alt_001 = next(s for s in svc.get_all_swarms() if s.name == "ALT-001")
        d = svc.get_drone(alt_001.drone_ids[0])
        assert d.model.value == "altius_600m"
        assert d.max_payload_kg == 12.0
        assert d.max_range_km == 160.0

    def test_recon_drone_model_fields(self):
        svc = _svc()
        mq9 = next(d for d in svc.get_all_drones() if d.name == "MQ9-01")
        assert mq9.model.value == "mq9_recon"
        assert mq9.max_range_km == 1900.0


# ─── Target CRUD ─────────────────────────────────────────────────────────────

class TestTargetCRUD:
    def test_upsert_and_get(self):
        svc = _empty_svc()
        t = _target()
        svc.upsert_target(t)
        result = svc.get_target(t.id)
        assert result is not None
        assert result.id == t.id
        assert result.type == TargetType.TANK

    def test_upsert_updates_last_seen(self):
        svc = _empty_svc()
        t = _target()
        before = t.last_seen
        time.sleep(0.01)
        svc.upsert_target(t)
        assert svc.get_target(t.id).last_seen >= before

    def test_get_nonexistent_returns_none(self):
        svc = _empty_svc()
        assert svc.get_target("does-not-exist") is None

    def test_get_all_returns_all(self):
        svc = _empty_svc()
        t1 = _target(type=TargetType.TANK)
        t2 = _target(type=TargetType.SHIP)
        svc.upsert_target(t1)
        svc.upsert_target(t2)
        all_targets = svc.get_all_targets()
        assert len(all_targets) == 2

    def test_get_all_with_status_filter(self):
        svc = _empty_svc()
        t_active = _target()
        t_destroyed = _target()
        t_destroyed.status = TargetStatus.DESTROYED
        svc.upsert_target(t_active)
        svc.upsert_target(t_destroyed)

        active = svc.get_all_targets(status_filter=TargetStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].id == t_active.id

    def test_mark_target_destroyed(self):
        svc = _empty_svc()
        t = _target()
        svc.upsert_target(t)
        result = svc.mark_target_destroyed(t.id)
        assert result is True
        assert svc.get_target(t.id).status == TargetStatus.DESTROYED

    def test_mark_target_destroyed_nonexistent(self):
        svc = _empty_svc()
        assert svc.mark_target_destroyed("ghost-id") is False

    def test_remove_target_returns_true(self):
        svc = _empty_svc()
        t = _target()
        svc.upsert_target(t)
        assert svc.remove_target(t.id) is True
        assert svc.get_target(t.id) is None

    def test_remove_target_nonexistent_returns_false(self):
        svc = _empty_svc()
        assert svc.remove_target("ghost-id") is False

    def test_upsert_overwrites_existing(self):
        svc = _empty_svc()
        t = _target(confidence=0.5)
        svc.upsert_target(t)
        t.confidence = 0.99
        svc.upsert_target(t)
        assert svc.get_target(t.id).confidence == 0.99


# ─── Drone CRUD ──────────────────────────────────────────────────────────────

class TestDroneCRUD:
    def test_register_and_get(self):
        svc = _empty_svc()
        d = _drone()
        svc.register_drone(d)
        result = svc.get_drone(d.id)
        assert result is not None
        assert result.name == "Test-1"

    def test_get_nonexistent_returns_none(self):
        svc = _empty_svc()
        assert svc.get_drone("ghost") is None

    def test_get_all_drones(self):
        svc = _empty_svc()
        svc.register_drone(_drone(name="A"))
        svc.register_drone(_drone(name="B"))
        assert len(svc.get_all_drones()) == 2

    def test_update_drone_status(self):
        svc = _empty_svc()
        d = _drone()
        svc.register_drone(d)
        svc.update_drone(d.id, {"status": DroneStatus.ENGAGING})
        assert svc.get_drone(d.id).status == DroneStatus.ENGAGING

    def test_update_drone_battery(self):
        svc = _empty_svc()
        d = _drone()
        svc.register_drone(d)
        svc.update_drone(d.id, {"battery": 42.5})
        assert svc.get_drone(d.id).battery == 42.5

    def test_update_drone_current_task(self):
        svc = _empty_svc()
        d = _drone()
        svc.register_drone(d)
        svc.update_drone(d.id, {"current_task": "Patrol sector 7"})
        assert svc.get_drone(d.id).current_task == "Patrol sector 7"

    def test_update_drone_nonexistent_returns_none(self):
        svc = _empty_svc()
        result = svc.update_drone("ghost", {"status": DroneStatus.IDLE})
        assert result is None

    def test_update_drone_updates_last_update_timestamp(self):
        svc = _empty_svc()
        d = _drone()
        svc.register_drone(d)
        original = svc.get_drone(d.id).last_update
        time.sleep(0.01)
        svc.update_drone(d.id, {"battery": 80.0})
        assert svc.get_drone(d.id).last_update >= original

    def test_update_ignores_none_values(self):
        """None values in the update dict should NOT overwrite existing values."""
        svc = _empty_svc()
        d = _drone()
        d.battery = 75.0
        svc.register_drone(d)
        svc.update_drone(d.id, {"battery": None, "status": DroneStatus.RETURNING})
        result = svc.get_drone(d.id)
        assert result.battery == 75.0  # unchanged
        assert result.status == DroneStatus.RETURNING


# ─── Swarm CRUD ──────────────────────────────────────────────────────────────

class TestSwarmCRUD:
    def test_create_and_get(self):
        svc = _empty_svc()
        s = _swarm()
        svc.create_swarm(s)
        result = svc.get_swarm(s.id)
        assert result is not None
        assert result.name == "Test Swarm"

    def test_get_nonexistent_returns_none(self):
        svc = _empty_svc()
        assert svc.get_swarm("ghost") is None

    def test_get_all_swarms(self):
        svc = _empty_svc()
        svc.create_swarm(_swarm(name="S1"))
        svc.create_swarm(_swarm(name="S2"))
        assert len(svc.get_all_swarms()) == 2

    def test_update_swarm_status(self):
        svc = _empty_svc()
        s = _swarm()
        svc.create_swarm(s)
        result = svc.update_swarm_status(s.id, SwarmStatus.ENGAGING)
        assert result is True
        assert svc.get_swarm(s.id).status == SwarmStatus.ENGAGING

    def test_update_swarm_status_sets_objective(self):
        svc = _empty_svc()
        s = _swarm()
        svc.create_swarm(s)
        svc.update_swarm_status(s.id, SwarmStatus.SEARCHING, objective="Find tanks")
        assert svc.get_swarm(s.id).objective == "Find tanks"

    def test_update_swarm_status_objective_none_preserves_existing(self):
        """Passing objective=None should NOT overwrite an existing objective."""
        svc = _empty_svc()
        s = _swarm()
        svc.create_swarm(s)
        svc.update_swarm_status(s.id, SwarmStatus.TRACKING, objective="Track ship")
        svc.update_swarm_status(s.id, SwarmStatus.ENGAGING, objective=None)
        # objective should remain as previously set (update_swarm_status only sets when not None)
        assert svc.get_swarm(s.id).objective == "Track ship"

    def test_update_swarm_status_nonexistent_returns_false(self):
        svc = _empty_svc()
        assert svc.update_swarm_status("ghost", SwarmStatus.IDLE) is False

    def test_update_swarm_sets_last_command(self):
        svc = _empty_svc()
        s = _swarm()
        svc.create_swarm(s)
        assert svc.get_swarm(s.id).last_command is None
        svc.update_swarm_status(s.id, SwarmStatus.RETURNING)
        assert svc.get_swarm(s.id).last_command is not None


# ─── Feature 32: Disengage ───────────────────────────────────────────────────

class TestDisengageTarget:
    def _engaged_target_and_swarm(self, svc: StateService):
        """Seed a target in 'engaged' status with a swarm actively engaging it."""
        target = _target(status=TargetStatus.ENGAGED)
        svc.upsert_target(target)
        drone = _drone(type=DroneType.COMBAT_SWARM, status=DroneStatus.ENGAGING)
        svc._drones[drone.id] = drone
        swarm = _swarm(status=SwarmStatus.ENGAGING, drone_ids=[drone.id], target_ids=[target.id])
        svc.create_swarm(swarm)
        return target, swarm, drone

    def test_disengage_reverts_target_to_active(self):
        svc = _empty_svc()
        target, swarm, drone = self._engaged_target_and_swarm(svc)
        svc.disengage_target(target.id)
        assert svc.get_target(target.id).status == TargetStatus.ACTIVE

    def test_disengage_sets_swarm_status_returning(self):
        svc = _empty_svc()
        target, swarm, drone = self._engaged_target_and_swarm(svc)
        svc.disengage_target(target.id)
        assert svc.get_swarm(swarm.id).status == SwarmStatus.RETURNING

    def test_disengage_clears_swarm_target_ids(self):
        svc = _empty_svc()
        target, swarm, drone = self._engaged_target_and_swarm(svc)
        svc.disengage_target(target.id)
        assert svc.get_swarm(swarm.id).target_ids == []

    def test_disengage_sets_member_drone_status_returning(self):
        svc = _empty_svc()
        target, swarm, drone = self._engaged_target_and_swarm(svc)
        svc.disengage_target(target.id)
        assert svc.get_drone(drone.id).status == DroneStatus.RETURNING

    def test_disengage_returns_swarm_id_and_name(self):
        svc = _empty_svc()
        target, swarm, drone = self._engaged_target_and_swarm(svc)
        result = svc.disengage_target(target.id)
        assert result == {"swarm_id": swarm.id, "swarm_name": swarm.name}

    def test_disengage_on_active_target_returns_none(self):
        svc = _empty_svc()
        target = _target(status=TargetStatus.ACTIVE)
        svc.upsert_target(target)
        assert svc.disengage_target(target.id) is None
        assert svc.get_target(target.id).status == TargetStatus.ACTIVE

    def test_disengage_on_nonexistent_target_returns_none(self):
        svc = _empty_svc()
        assert svc.disengage_target("ghost") is None

    def test_disengage_with_no_matching_swarm_still_releases_target(self):
        """If the target is 'engaged' but no swarm is currently engaging it
        (e.g. stale state), the target still reverts to active."""
        svc = _empty_svc()
        target = _target(status=TargetStatus.ENGAGED)
        svc.upsert_target(target)
        result = svc.disengage_target(target.id)
        assert result is None
        assert svc.get_target(target.id).status == TargetStatus.ACTIVE


# ─── Feature 37: Stop Tracking ────────────────────────────────────────────────

class TestStopTrackingTarget:
    def _tracked_target_and_drone(self, svc: StateService):
        """Seed a target in 'tracked' status with a drone actively tracking it."""
        target = _target(status=TargetStatus.TRACKED)
        svc.upsert_target(target)
        drone = _drone(type=DroneType.RECON, status=DroneStatus.TRACKING, tracking_target_id=target.id)
        svc._drones[drone.id] = drone
        return target, drone

    def test_stop_tracking_reverts_target_to_active(self):
        svc = _empty_svc()
        target, drone = self._tracked_target_and_drone(svc)
        svc.stop_tracking_target(target.id)
        assert svc.get_target(target.id).status == TargetStatus.ACTIVE

    def test_stop_tracking_sets_drone_status_returning(self):
        svc = _empty_svc()
        target, drone = self._tracked_target_and_drone(svc)
        svc.stop_tracking_target(target.id)
        assert svc.get_drone(drone.id).status == DroneStatus.RETURNING

    def test_stop_tracking_clears_drone_tracking_target_id(self):
        svc = _empty_svc()
        target, drone = self._tracked_target_and_drone(svc)
        svc.stop_tracking_target(target.id)
        assert svc.get_drone(drone.id).tracking_target_id is None

    def test_stop_tracking_returns_drone_id_and_name(self):
        svc = _empty_svc()
        target, drone = self._tracked_target_and_drone(svc)
        result = svc.stop_tracking_target(target.id)
        assert result == {"drone_id": drone.id, "drone_name": drone.name}

    def test_stop_tracking_on_active_target_returns_none(self):
        svc = _empty_svc()
        target = _target(status=TargetStatus.ACTIVE)
        svc.upsert_target(target)
        assert svc.stop_tracking_target(target.id) is None
        assert svc.get_target(target.id).status == TargetStatus.ACTIVE

    def test_stop_tracking_on_nonexistent_target_returns_none(self):
        svc = _empty_svc()
        assert svc.stop_tracking_target("ghost") is None

    def test_stop_tracking_with_no_matching_drone_still_releases_target(self):
        """If the target is 'tracked' but no drone is currently tracking it
        (e.g. stale state), the target still reverts to active."""
        svc = _empty_svc()
        target = _target(status=TargetStatus.TRACKED)
        svc.upsert_target(target)
        result = svc.stop_tracking_target(target.id)
        assert result is None
        assert svc.get_target(target.id).status == TargetStatus.ACTIVE


# ─── Command Log ─────────────────────────────────────────────────────────────

class TestCommandLog:
    def test_log_entry_stored(self):
        svc = _empty_svc()
        svc.log_command({"type": "test", "msg": "hello"})
        log = svc.get_command_log()
        assert len(log) == 1
        assert log[0]["msg"] == "hello"

    def test_log_entry_gets_timestamp(self):
        svc = _empty_svc()
        svc.log_command({"type": "test"})
        assert "timestamp" in svc.get_command_log()[0]

    def test_get_command_log_limit(self):
        svc = _empty_svc()
        for i in range(10):
            svc.log_command({"i": i})
        assert len(svc.get_command_log(limit=3)) == 3

    def test_get_command_log_returns_latest(self):
        svc = _empty_svc()
        for i in range(10):
            svc.log_command({"i": i})
        last = svc.get_command_log(limit=1)[0]
        assert last["i"] == 9

    def test_log_capped_at_200(self):
        svc = _empty_svc()
        for i in range(250):
            svc.log_command({"i": i})
        assert len(svc._command_log) == 200
        # Should contain the LATEST 200 entries
        assert svc._command_log[0]["i"] == 50


# ─── Full State Snapshot ──────────────────────────────────────────────────────

class TestFullState:
    def test_snapshot_keys(self):
        svc = _svc()
        state = svc.get_full_state()
        assert "targets" in state
        assert "drones" in state
        assert "swarms" in state
        assert "timestamp" in state

    def test_snapshot_drones_count(self):
        svc = _svc()
        state = svc.get_full_state()
        # 4 MQ-9 + 100 scout recon + 20 FPV + 100 ALT representative drones (§8.9) = 224
        assert len(state["drones"]) == 224

    def test_snapshot_swarms_count(self):
        svc = _svc()
        state = svc.get_full_state()
        # 20 FPV swarms + 100 ALT swarms (§8.9)
        assert len(state["swarms"]) == 120

    def test_snapshot_no_targets_initially(self):
        svc = _svc()
        state = svc.get_full_state()
        # 20 friendly + 90 enemy assets seeded per the initial seeding counts (§8.9)
        assert len(state["targets"]) == 110

    def test_snapshot_includes_added_target(self):
        svc = _svc()
        seeded = len(svc.get_all_targets())
        t = _target()
        svc.upsert_target(t)
        state = svc.get_full_state()
        assert len(state["targets"]) == seeded + 1
        assert any(entry["id"] == t.id for entry in state["targets"])


# ─── Thread Safety ────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_target_upserts(self):
        svc = _empty_svc()
        errors = []

        def insert(i):
            try:
                t = _target()
                t.id = f"target-{i}"
                svc.upsert_target(t)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=insert, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(svc.get_all_targets()) == 50


# ─── Target status serialization ─────────────────────────────────────────────

class TestTargetStatusSerialization:
    def test_active_status_persisted(self):
        svc = _empty_svc()
        svc.upsert_target(_target(status=TargetStatus.ACTIVE))
        data = svc._build_initial_state()
        assert data["targets"][0]["status"] == "active"

    def test_destroyed_status_persisted(self):
        svc = _empty_svc()
        svc.upsert_target(_target(status=TargetStatus.DESTROYED))
        data = svc._build_initial_state()
        assert data["targets"][0]["status"] == "destroyed"

    def test_lost_status_persisted(self):
        svc = _empty_svc()
        svc.upsert_target(_target(status=TargetStatus.LOST))
        data = svc._build_initial_state()
        assert data["targets"][0]["status"] == "lost"

    def test_engaged_status_serialized_as_active(self):
        svc = _empty_svc()
        svc.upsert_target(_target(status=TargetStatus.ENGAGED))
        data = svc._build_initial_state()
        assert data["targets"][0]["status"] == "active"

    def test_tracked_status_serialized_as_active(self):
        svc = _empty_svc()
        svc.upsert_target(_target(status=TargetStatus.TRACKED))
        data = svc._build_initial_state()
        assert data["targets"][0]["status"] == "active"
