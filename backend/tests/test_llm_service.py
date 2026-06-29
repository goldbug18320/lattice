"""Unit tests for services/llm_service.py (mock/no-API-key path)"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from services.llm_service import LLMService


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _context(swarms=None, drones=None, targets=None):
    return {
        "swarms": [{"id": "swarm-1", "name": "Alpha Swarm", "status": "idle"}] if swarms is None else swarms,
        "drones": [] if drones is None else drones,
        "targets": [] if targets is None else targets,
    }


def _active_target(tid="t-1", ttype="tank", alt=0):
    return {"id": tid, "type": ttype, "status": "active", "confidence": 0.9,
            "position": {"lat": 24.0, "lon": 120.0, "alt": alt}}


# All tests in this module force the mock path by ensuring OPENAI_API_KEY is absent
@pytest.fixture(autouse=True)
def no_api_key():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENAI_API_KEY", None)
        yield


# ─── Response Structure ───────────────────────────────────────────────────────

class TestMockResponseStructure:
    def test_has_required_keys(self):
        svc = LLMService()
        result = _run(svc.process_command("find enemies", _context()))
        assert "interpretation" in result
        assert "action" in result
        assert "explanation" in result

    def test_action_has_type(self):
        svc = LLMService()
        result = _run(svc.process_command("search area", _context()))
        assert "type" in result["action"]

    def test_action_has_command_type(self):
        svc = LLMService()
        result = _run(svc.process_command("search area", _context()))
        assert "command_type" in result["action"]

    def test_interpretation_references_command(self):
        svc = LLMService()
        cmd = "do something tactical"
        result = _run(svc.process_command(cmd, _context()))
        assert cmd in result["interpretation"]


# ─── Keyword Routing ─────────────────────────────────────────────────────────

class TestMockKeywordRouting:
    @pytest.mark.parametrize("keyword", [
        "attack all ships",
        "engage the enemy",
        "destroy missile launcher",
        "strike the target",
    ])
    def test_attack_keywords_return_request_approval(self, keyword):
        """Attack commands now go through HITL — return request_approval, not assign_swarm."""
        svc = LLMService()
        result = _run(svc.process_command(keyword, _context()))
        assert result["action"]["type"] == "request_approval"
        assert result["action"]["proposed_action"]["command_type"] == "attack"

    @pytest.mark.parametrize("keyword,expected_cmd", [
        ("track the ship",   "track"),
        ("follow enemy tank","track"),
        ("monitor targets",  "track"),
    ])
    def test_track_keywords_route_through_hitl(self, keyword, expected_cmd):
        """Track commands route through HITL with a recon drone (Feature 24)."""
        svc = LLMService()
        recon = {
            "id": "d-mq9", "name": "MQ9-01", "model": "mq9_recon",
            "type": "recon", "status": "patrolling", "battery": 90.0,
            "max_range_km": 1900.0, "swarm_id": None,
            "position": {"lat": 25.0, "lon": 121.5, "alt": 6000},
        }
        ctx = _context(drones=[recon])
        result = _run(svc.process_command(keyword, ctx))
        assert result["action"]["type"] == "request_approval"
        assert result["action"]["proposed_action"]["command_type"] == expected_cmd
        assert result["action"]["proposed_action"]["type"] == "assign_drone"

    @pytest.mark.parametrize("keyword,expected_cmd", [
        ("locate enemy drones", "locate"),
        ("find the missile launchers", "locate"),
        ("search the area",  "locate"),
        ("scout sector 7",   "locate"),
    ])
    def test_locate_keywords(self, keyword, expected_cmd):
        svc = LLMService()
        result = _run(svc.process_command(keyword, _context()))
        assert result["action"]["command_type"] == expected_cmd
        assert result["action"]["type"] == "assign_swarm"

    @pytest.mark.parametrize("keyword,expected_cmd", [
        ("return to base",  "return"),
        ("recall all drones","return"),
        ("all units rtb",   "return"),
    ])
    def test_return_keywords(self, keyword, expected_cmd):
        svc = LLMService()
        result = _run(svc.process_command(keyword, _context()))
        assert result["action"]["command_type"] == expected_cmd
        assert result["action"]["type"] == "assign_swarm"

    def test_unknown_command_action_type_is_none(self):
        svc = LLMService()
        result = _run(svc.process_command("do nothing", _context()))
        assert result["action"]["type"] == "none"


# ─── Swarm Assignment ─────────────────────────────────────────────────────────

class TestMockSwarmAssignment:
    def test_assigns_first_swarm(self):
        svc = LLMService()
        ctx = _context(swarms=[
            {"id": "s-1", "name": "Alpha", "status": "idle"},
            {"id": "s-2", "name": "Bravo", "status": "idle"},
        ])
        result = _run(svc.process_command("attack", ctx))
        # Attack returns request_approval; swarm_id is in proposed_action
        assert result["action"]["proposed_action"]["swarm_id"] == "s-1"

    def test_no_swarms_gives_none_swarm_id(self):
        svc = LLMService()
        ctx = _context(swarms=[])
        result = _run(svc.process_command("attack", ctx))
        assert result["action"]["proposed_action"]["swarm_id"] is None

    def test_attack_includes_only_active_targets(self):
        svc = LLMService()
        ctx = _context(targets=[
            _active_target("t-1"),
            {"id": "t-2", "type": "ship", "status": "destroyed", "confidence": 0.9,
             "position": {"lat": 24.0, "lon": 120.0, "alt": 0}},
            _active_target("t-3"),
        ])
        result = _run(svc.process_command("attack", ctx))
        # classified_targets should only include active ones
        classified_ids = [c["target_id"] for c in result["action"]["classified_targets"]]
        assert "t-1" in classified_ids
        assert "t-3" in classified_ids
        assert "t-2" not in classified_ids

    def test_attack_caps_target_ids_at_six(self):
        svc = LLMService()
        targets = [_active_target(f"t-{i}") for i in range(10)]
        ctx = _context(targets=targets)
        result = _run(svc.process_command("attack everything", ctx))
        assert len(result["action"]["classified_targets"]) <= 6

    def test_non_attack_commands_have_empty_target_ids(self):
        svc = LLMService()
        result = _run(svc.process_command("return to base", _context()))
        assert result["action"]["target_ids"] == []


# ─── Priority ─────────────────────────────────────────────────────────────────

class TestMockPriority:
    def test_attack_command_high_priority(self):
        svc = LLMService()
        result = _run(svc.process_command("attack all targets", _context()))
        # Priority is now in proposed_action (attack goes through HITL)
        assert result["action"]["proposed_action"]["priority"] >= 8

    def test_non_attack_command_medium_priority(self):
        svc = LLMService()
        result = _run(svc.process_command("search the area", _context()))
        assert result["action"]["priority"] == 5


# ─── Objective Passthrough ────────────────────────────────────────────────────

class TestMockObjective:
    def test_objective_equals_original_command(self):
        svc = LLMService()
        cmd = "locate all enemy tanks in sector 4"
        result = _run(svc.process_command(cmd, _context()))
        assert result["action"]["objective"] == cmd


# ─── Drone Model Selection ────────────────────────────────────────────────────

class TestMockDroneModelSelection:
    def test_tactical_response_includes_drone_model(self):
        svc = LLMService()
        result = _run(svc.process_command("attack all targets", _context()))
        # drone_model is now in proposed_action for attack commands
        assert "drone_model" in result["action"]["proposed_action"]

    def test_heavy_target_selects_altius(self):
        svc = LLMService()
        ctx = _context(targets=[_active_target("t-1", ttype="tank")])
        result = _run(svc.process_command("attack enemy tanks", ctx))
        assert result["action"]["proposed_action"]["drone_model"] == "altius_600m"

    def test_light_target_selects_fpv(self):
        svc = LLMService()
        ctx = _context(targets=[_active_target("t-1", ttype="soldier_unit")])
        result = _run(svc.process_command("attack soldiers", ctx))
        assert result["action"]["proposed_action"]["drone_model"] == "fpv_combat"

    def test_tactical_response_includes_swarm_size(self):
        svc = LLMService()
        result = _run(svc.process_command("attack", _context()))
        assert "recommended_swarm_size" in result["action"]["proposed_action"]
        assert result["action"]["proposed_action"]["recommended_swarm_size"] > 0

    def test_prefers_alt_swarm_for_heavy_command(self):
        svc = LLMService()
        ctx = _context(swarms=[
            {"id": "fpv-1", "name": "FPV-Alpha", "status": "idle"},
            {"id": "alt-1", "name": "ALT-Alpha", "status": "idle"},
        ], targets=[_active_target("t-1", ttype="tank")])
        result = _run(svc.process_command("attack tank", ctx))
        assert result["action"]["proposed_action"]["swarm_id"] == "alt-1"

    def test_prefers_fpv_swarm_for_light_command(self):
        svc = LLMService()
        ctx = _context(swarms=[
            {"id": "fpv-1", "name": "FPV-Alpha", "status": "idle"},
            {"id": "alt-1", "name": "ALT-Alpha", "status": "idle"},
        ])
        result = _run(svc.process_command("locate enemy", ctx))
        assert result["action"]["swarm_id"] == "fpv-1"


# ─── Feature 24: TRACK HITL with Recon Drone ─────────────────────────────────

def _recon_drone(did="d-mq9", name="MQ9-01", model="mq9_recon",
                 lat=25.0, lon=121.5, max_range=1900.0, status="patrolling"):
    return {
        "id": did, "name": name, "model": model,
        "type": "recon", "status": status, "battery": 90.0,
        "max_range_km": max_range, "swarm_id": None,
        "position": {"lat": lat, "lon": lon, "alt": 6000},
    }


def _near_target(tid="t-near", lat=25.1, lon=121.5):
    return {"id": tid, "type": "ship", "status": "active", "confidence": 0.9,
            "position": {"lat": lat, "lon": lon, "alt": 0}}


class TestFeature24TrackHITL:
    def test_track_with_recon_returns_request_approval(self):
        svc = LLMService()
        ctx = _context(drones=[_recon_drone()])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["type"] == "request_approval"

    def test_track_proposed_action_is_assign_drone(self):
        svc = LLMService()
        ctx = _context(drones=[_recon_drone()])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["proposed_action"]["type"] == "assign_drone"

    def test_track_proposed_command_type_is_track(self):
        svc = LLMService()
        ctx = _context(drones=[_recon_drone()])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["proposed_action"]["command_type"] == "track"

    def test_track_selects_drone_id(self):
        svc = LLMService()
        recon = _recon_drone(did="d-mq9-001")
        ctx = _context(drones=[recon])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["proposed_action"]["drone_id"] == "d-mq9-001"

    def test_no_recon_drones_returns_no_recon_in_range(self):
        svc = LLMService()
        ctx = _context(drones=[])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["type"] == "no_recon_in_range"

    def test_out_of_range_recon_returns_no_recon_in_range(self):
        svc = LLMService()
        # Recon at lat 25.0 lon 121.5; target ~11 km north; drone max_range = 5 km
        recon = _recon_drone(lat=25.0, lon=121.5, max_range=5.0)
        target = _near_target(tid="t-far", lat=25.1, lon=121.5)
        ctx = _context(drones=[recon], targets=[target])
        result = _run(svc.process_command("track target with id t-far", ctx))
        assert result["action"]["type"] == "no_recon_in_range"

    def test_in_range_recon_returns_request_approval(self):
        svc = LLMService()
        # Recon and target both near lat 25.0 lon 121.5, max_range 100 km
        recon = _recon_drone(lat=25.0, lon=121.5, max_range=100.0)
        target = _near_target(tid="t-near", lat=25.01, lon=121.5)
        ctx = _context(drones=[recon], targets=[target])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["type"] == "request_approval"

    def test_tracking_drone_excluded_from_selection(self):
        svc = LLMService()
        busy = _recon_drone(did="d-busy", status="tracking")
        ctx = _context(drones=[busy])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["type"] == "no_recon_in_range"

    def test_scout_drone_selected_when_mq9_out_of_range(self):
        svc = LLMService()
        mq9 = _recon_drone(did="d-mq9", lat=22.0, lon=119.0, max_range=1.0)
        scout = _recon_drone(did="d-scout", name="SCOUT-001", model="scout_recon",
                             lat=25.0, lon=121.5, max_range=150.0)
        target = _near_target(tid="t-near", lat=25.01, lon=121.5)
        ctx = _context(drones=[mq9, scout], targets=[target])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["type"] == "request_approval"
        assert result["action"]["proposed_action"]["drone_id"] == "d-scout"

    def test_approval_prompt_includes_drone_name(self):
        svc = LLMService()
        recon = _recon_drone(name="MQ9-02")
        ctx = _context(drones=[recon])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert "MQ9-02" in result["action"]["approval_prompt"]

    def test_no_recon_in_range_includes_target_id(self):
        svc = LLMService()
        ctx = _context(drones=[])
        result = _run(svc.process_command("track target with id t-abc", ctx))
        assert result["action"].get("target_id") == "t-abc"

    def test_closest_in_range_drone_selected(self):
        svc = LLMService()
        # Two recon drones both in range; target at lat 25.1; drone at 25.0 is closer
        close_recon = _recon_drone(did="d-close", name="MQ9-01", lat=25.0, lon=121.5, max_range=100.0)
        far_recon = _recon_drone(did="d-far", name="MQ9-02", lat=23.0, lon=120.0, max_range=500.0)
        target = _near_target(tid="t-near", lat=25.1, lon=121.5)
        ctx = _context(drones=[far_recon, close_recon], targets=[target])
        result = _run(svc.process_command("track target with id t-near", ctx))
        assert result["action"]["proposed_action"]["drone_id"] == "d-close"
