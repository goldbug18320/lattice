"""Unit tests for services/swarm_service.py"""
from __future__ import annotations

import threading

import pytest

from models.target import Position, Target, TargetType
from models.drone import (
    CommandType, Drone, DroneStatus, DroneType,
    DroneCommand, Swarm, SwarmCommand, SwarmStatus,
)
from services.state_service import StateService
from services.swarm_service import SwarmService


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_state_with_swarm(n_drones: int = 3):
    """Return (state_svc, swarm_service, swarm_id) with a swarm of n_drones."""
    svc = StateService.__new__(StateService)
    svc._lock = threading.Lock()
    svc._targets = {}
    svc._drones = {}
    svc._swarms = {}
    svc._command_log = []

    swarm = Swarm(name="Test Swarm")
    for i in range(n_drones):
        d = Drone(
            name=f"D-{i+1}",
            type=DroneType.SWARM_MEMBER,
            swarm_id=swarm.id,
        )
        svc._drones[d.id] = d
        swarm.drone_ids.append(d.id)
    svc._swarms[swarm.id] = swarm

    # Inject this state into a dedicated SwarmService
    import services.swarm_service as swarm_module
    original = swarm_module.state_service
    swarm_module.state_service = svc

    service = SwarmService()

    return svc, service, swarm.id, swarm_module, original


def _cmd(cmd_type: CommandType, **kwargs) -> SwarmCommand:
    return SwarmCommand(command_type=cmd_type, **kwargs)


def _drone_cmd(cmd_type: CommandType, **kwargs) -> DroneCommand:
    return DroneCommand(command_type=cmd_type, **kwargs)


# ─── Swarm Command — Status Transitions ───────────────────────────────────────

class TestSwarmCommandStatusTransitions:
    @pytest.mark.parametrize("cmd_type,expected_swarm,expected_drone", [
        (CommandType.LOCATE,  SwarmStatus.SEARCHING, DroneStatus.SEARCHING),
        (CommandType.TRACK,   SwarmStatus.TRACKING,  DroneStatus.TRACKING),
        (CommandType.ATTACK,  SwarmStatus.ENGAGING,  DroneStatus.ENGAGING),
        (CommandType.PATROL,  SwarmStatus.SEARCHING, DroneStatus.PATROLLING),
        (CommandType.RETURN,  SwarmStatus.RETURNING, DroneStatus.RETURNING),
        (CommandType.ABORT,   SwarmStatus.IDLE,      DroneStatus.IDLE),
    ])
    def test_status_transition(self, cmd_type, expected_swarm, expected_drone):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(2)
        try:
            result = service.execute_swarm_command(swarm_id, _cmd(cmd_type))
            assert result["success"] is True
            assert svc.get_swarm(swarm_id).status == expected_swarm
            for did in svc.get_swarm(swarm_id).drone_ids:
                assert svc.get_drone(did).status == expected_drone
        finally:
            mod.state_service = original


class TestSwarmCommandDronePropagation:
    def test_all_drones_updated(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(5)
        try:
            result = service.execute_swarm_command(swarm_id, _cmd(CommandType.ATTACK))
            assert result["drones_tasked"] == 5
            for did in svc.get_swarm(swarm_id).drone_ids:
                assert svc.get_drone(did).status == DroneStatus.ENGAGING
        finally:
            mod.state_service = original

    def test_objective_propagated_to_drones(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(3)
        try:
            service.execute_swarm_command(
                swarm_id, _cmd(CommandType.ATTACK, objective="Destroy missile launcher")
            )
            for did in svc.get_swarm(swarm_id).drone_ids:
                assert svc.get_drone(did).current_task == "Destroy missile launcher"
        finally:
            mod.state_service = original

    def test_command_type_used_as_task_when_no_objective(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(2)
        try:
            service.execute_swarm_command(swarm_id, _cmd(CommandType.PATROL))
            for did in svc.get_swarm(swarm_id).drone_ids:
                assert svc.get_drone(did).current_task == "patrol"
        finally:
            mod.state_service = original


class TestSwarmCommandTargetIds:
    def test_target_ids_stored_on_swarm(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(2)
        try:
            service.execute_swarm_command(
                swarm_id,
                _cmd(CommandType.ATTACK, target_ids=["t-1", "t-2"]),
            )
            assert svc.get_swarm(swarm_id).target_ids == ["t-1", "t-2"]
        finally:
            mod.state_service = original

    def test_empty_target_ids_leaves_existing(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(2)
        try:
            # First command sets targets
            service.execute_swarm_command(
                swarm_id, _cmd(CommandType.TRACK, target_ids=["t-1"])
            )
            # Second command with no target_ids should not overwrite
            service.execute_swarm_command(
                swarm_id, _cmd(CommandType.RETURN, target_ids=[])
            )
            # RETURN does not set target_ids, so existing list remains
            assert svc.get_swarm(swarm_id).target_ids == ["t-1"]
        finally:
            mod.state_service = original


class TestSwarmCommandNonexistent:
    def test_nonexistent_swarm_returns_failure(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm()
        try:
            result = service.execute_swarm_command("ghost-id", _cmd(CommandType.ATTACK))
            assert result["success"] is False
            assert "error" in result
        finally:
            mod.state_service = original


class TestSwarmCommandLogging:
    def test_command_logged(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(2)
        try:
            service.execute_swarm_command(
                swarm_id, _cmd(CommandType.ATTACK, objective="Strike ships")
            )
            log = svc.get_command_log()
            assert len(log) == 1
            entry = log[0]
            assert entry["type"] == "swarm_command"
            assert entry["command"] == "attack"
            assert entry["objective"] == "Strike ships"
            assert entry["swarm_id"] == swarm_id
        finally:
            mod.state_service = original

    def test_log_includes_drones_tasked(self):
        svc, service, swarm_id, mod, original = _make_state_with_swarm(4)
        try:
            service.execute_swarm_command(swarm_id, _cmd(CommandType.LOCATE))
            entry = svc.get_command_log()[0]
            assert entry["drones_tasked"] == 4
        finally:
            mod.state_service = original


# ─── Drone Command ────────────────────────────────────────────────────────────

class TestDroneCommand:
    def _setup(self):
        svc = StateService.__new__(StateService)
        svc._lock = threading.Lock()
        svc._targets = {}
        svc._drones = {}
        svc._swarms = {}
        svc._command_log = []
        drone = Drone(name="Solo-1", type=DroneType.RECON)
        svc._drones[drone.id] = drone

        import services.swarm_service as mod
        original = mod.state_service
        mod.state_service = svc
        service = SwarmService()
        return svc, service, drone.id, mod, original

    @pytest.mark.parametrize("cmd_type,expected_status", [
        (CommandType.LOCATE,  DroneStatus.SEARCHING),
        (CommandType.TRACK,   DroneStatus.TRACKING),
        (CommandType.ATTACK,  DroneStatus.ENGAGING),
        (CommandType.PATROL,  DroneStatus.PATROLLING),
        (CommandType.RETURN,  DroneStatus.RETURNING),
        (CommandType.ABORT,   DroneStatus.IDLE),
    ])
    def test_drone_status_transition(self, cmd_type, expected_status):
        svc, service, drone_id, mod, original = self._setup()
        try:
            result = service.execute_drone_command(drone_id, _drone_cmd(cmd_type))
            assert result["success"] is True
            assert svc.get_drone(drone_id).status == expected_status
        finally:
            mod.state_service = original

    def test_drone_command_sets_objective(self):
        svc, service, drone_id, mod, original = self._setup()
        try:
            service.execute_drone_command(
                drone_id, _drone_cmd(CommandType.TRACK, objective="Shadow enemy ship")
            )
            assert svc.get_drone(drone_id).current_task == "Shadow enemy ship"
        finally:
            mod.state_service = original

    def test_drone_command_uses_cmd_type_as_fallback_task(self):
        svc, service, drone_id, mod, original = self._setup()
        try:
            service.execute_drone_command(drone_id, _drone_cmd(CommandType.PATROL))
            assert svc.get_drone(drone_id).current_task == "patrol"
        finally:
            mod.state_service = original

    def test_drone_command_nonexistent_returns_failure(self):
        svc, service, drone_id, mod, original = self._setup()
        try:
            result = service.execute_drone_command("ghost", _drone_cmd(CommandType.LOCATE))
            assert result["success"] is False
            assert "error" in result
        finally:
            mod.state_service = original

    def test_drone_command_logged(self):
        svc, service, drone_id, mod, original = self._setup()
        try:
            service.execute_drone_command(
                drone_id, _drone_cmd(CommandType.ATTACK, objective="Intercept drone")
            )
            log = svc.get_command_log()
            assert len(log) == 1
            entry = log[0]
            assert entry["type"] == "drone_command"
            assert entry["drone_id"] == drone_id
            assert entry["command"] == "attack"
            assert entry["objective"] == "Intercept drone"
        finally:
            mod.state_service = original

    def test_result_contains_expected_fields(self):
        svc, service, drone_id, mod, original = self._setup()
        try:
            result = service.execute_drone_command(
                drone_id, _drone_cmd(CommandType.RETURN)
            )
            assert set(result.keys()) >= {"success", "drone_id", "command_type", "objective"}
        finally:
            mod.state_service = original


# ─── Feature 28: already-tracked notification (no replacement) ───────────────

class TestTrackingNotification:
    """Feature 28: re-clicking TRACK on an already-tracked target must NOT replace
    the existing drone — the API layer intercepts and returns already_tracked instead."""

    def _setup_two_recon(self):
        """Return state with two recon drones and one target; wire swarm_service to use it."""
        from models.target import TargetType, TargetStatus, Position

        svc = StateService.__new__(StateService)
        svc._lock = threading.Lock()
        svc._targets = {}
        svc._drones = {}
        svc._swarms = {}
        svc._command_log = []

        target = Target(
            type=TargetType.SHIP,
            position=Position(lat=24.0, lon=119.8, alt=0.0),
            confidence=0.9,
            status=TargetStatus.ACTIVE,
            speed=0.0,
            heading=0.0,
        )
        svc._targets[target.id] = target

        d1 = Drone(name="SCOUT-001", type=DroneType.RECON)
        d2 = Drone(name="SCOUT-002", type=DroneType.RECON)
        svc._drones[d1.id] = d1
        svc._drones[d2.id] = d2

        import services.swarm_service as mod
        original = mod.state_service
        mod.state_service = svc
        service = SwarmService()
        return svc, service, d1.id, d2.id, target.id, mod, original

    def test_first_track_assigns_drone(self):
        """First-time TRACK assignment must succeed and set tracking state."""
        svc, service, d1_id, d2_id, target_id, mod, original = self._setup_two_recon()
        try:
            result = service.execute_drone_command(d1_id, _drone_cmd(CommandType.TRACK, target_id=target_id))
            assert result["success"] is True
            assert svc.get_drone(d1_id).status == DroneStatus.TRACKING
            assert svc.get_drone(d1_id).tracking_target_id == target_id
        finally:
            mod.state_service = original

    def test_existing_tracker_not_replaced_when_second_track_executed(self):
        """Feature 28: execute_drone_command no longer releases the previous tracking drone.
        The API layer (nlp.py) prevents re-assignment via the already_tracked check,
        so this lower-level path should leave d1 unchanged if somehow called."""
        svc, service, d1_id, d2_id, target_id, mod, original = self._setup_two_recon()
        try:
            service.execute_drone_command(d1_id, _drone_cmd(CommandType.TRACK, target_id=target_id))
            assert svc.get_drone(d1_id).status == DroneStatus.TRACKING

            # Direct lower-level call (bypassing the nlp.py already_tracked guard):
            # d1 must remain TRACKING — no replacement occurs at this layer.
            service.execute_drone_command(d2_id, _drone_cmd(CommandType.TRACK, target_id=target_id))
            assert svc.get_drone(d1_id).status == DroneStatus.TRACKING
            assert svc.get_drone(d1_id).tracking_target_id == target_id
        finally:
            mod.state_service = original
