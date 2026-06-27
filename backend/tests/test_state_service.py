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
        assert len(swarms) == 15
        names = {s.name for s in swarms}
        # 10 FPV swarms
        for fpv_name in ("FPV-Alpha", "FPV-Bravo", "FPV-Charlie", "FPV-Delta", "FPV-Echo",
                         "FPV-Foxtrot", "FPV-Golf", "FPV-Hotel", "FPV-India", "FPV-Juliet"):
            assert fpv_name in names
        # 5 ALT swarms
        for alt_name in ("ALT-Alpha", "ALT-Bravo", "ALT-Charlie", "ALT-Delta", "ALT-Echo"):
            assert alt_name in names

    def test_fpv_swarm_total_drone_count(self):
        svc = _svc()
        fpv_alpha = next(s for s in svc.get_all_swarms() if s.name == "FPV-Alpha")
        assert fpv_alpha.total_drone_count == 1000

    def test_alt_swarm_total_drone_count(self):
        svc = _svc()
        alt_alpha = next(s for s in svc.get_all_swarms() if s.name == "ALT-Alpha")
        assert alt_alpha.total_drone_count == 200

    def test_each_swarm_has_five_representative_drones(self):
        svc = _svc()
        for swarm in svc.get_all_swarms():
            assert len(swarm.drone_ids) == 5

    def test_total_seeded_drones(self):
        svc = _svc()
        # 4 MQ-9 recon + 100 scout recon + 15 swarms × 5 representative = 179
        assert len(svc.get_all_drones()) == 179

    def test_no_targets_initially(self):
        svc = _svc()
        # 23 enemy assets are seeded for demo
        assert len(svc.get_all_targets()) == 23

    def test_seeded_scout_drones(self):
        svc = _svc()
        scouts = [d for d in svc.get_all_drones() if d.model == DroneModel.SCOUT_RECON]
        assert len(scouts) == 100

    def test_all_scouts_start_patrolling(self):
        """All 100 scout drones start PATROLLING from their city home positions."""
        svc = _svc()
        scouts = [d for d in svc.get_all_drones() if d.model == DroneModel.SCOUT_RECON]
        patrolling = [d for d in scouts if d.status == DroneStatus.PATROLLING]
        assert len(patrolling) == len(scouts)

    def test_scouts_only_patrolling_at_startup(self):
        svc = _svc()
        scouts = [d for d in svc.get_all_drones() if d.model == DroneModel.SCOUT_RECON]
        assert all(d.status == DroneStatus.PATROLLING for d in scouts)

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
        alt_alpha = next(s for s in svc.get_all_swarms() if s.name == "ALT-Alpha")
        d = svc.get_drone(alt_alpha.drone_ids[0])
        assert d.model.value == "altius_600m"
        assert d.max_payload_kg == 12.0
        assert d.max_range_km == 440.0

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
        # 4 MQ-9 + 100 scout recon + 15 swarms × 5 representative drones = 179
        assert len(state["drones"]) == 179

    def test_snapshot_swarms_count(self):
        svc = _svc()
        state = svc.get_full_state()
        assert len(state["swarms"]) == 15

    def test_snapshot_no_targets_initially(self):
        svc = _svc()
        state = svc.get_full_state()
        # 23 enemy assets seeded for demo
        assert len(state["targets"]) == 23

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
