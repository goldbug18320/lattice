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
    def test_track_keywords(self, keyword, expected_cmd):
        svc = LLMService()
        result = _run(svc.process_command(keyword, _context()))
        assert result["action"]["command_type"] == expected_cmd
        assert result["action"]["type"] == "assign_swarm"

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


# ─── UI Commands ──────────────────────────────────────────────────────────────

class TestMockUICommands:
    def test_show_map_returns_ui_command(self):
        svc = LLMService()
        result = _run(svc.process_command("show Taiwan on map", _context()))
        assert result["action"]["type"] == "ui_command"

    def test_show_map_has_ui_subtype(self):
        svc = LLMService()
        result = _run(svc.process_command("show Taiwan on map", _context()))
        assert result["action"]["ui_subtype"] == "fly_to"

    def test_show_map_has_destination(self):
        svc = LLMService()
        result = _run(svc.process_command("show Taiwan on map", _context()))
        dest = result["action"]["destination"]
        assert "lat" in dest
        assert "lon" in dest

    def test_taiwan_destination_coords(self):
        svc = LLMService()
        result = _run(svc.process_command("show Taiwan on map", _context()))
        dest = result["action"]["destination"]
        assert abs(dest["lat"] - 23.8) < 1.0
        assert abs(dest["lon"] - 121.0) < 1.0

    def test_taipei_destination_resolved(self):
        svc = LLMService()
        result = _run(svc.process_command("zoom to Taipei", _context()))
        assert result["action"]["type"] == "ui_command"
        assert "taipei" in result["action"]["destination"]["name"].lower()

    def test_zoom_in_keyword(self):
        svc = LLMService()
        result = _run(svc.process_command("zoom in", _context()))
        assert result["action"]["type"] == "ui_command"
        assert result["action"]["ui_subtype"] == "zoom_in"

    def test_zoom_out_keyword(self):
        svc = LLMService()
        result = _run(svc.process_command("zoom out", _context()))
        assert result["action"]["type"] == "ui_command"
        assert result["action"]["ui_subtype"] == "zoom_out"

    def test_focus_keyword(self):
        svc = LLMService()
        result = _run(svc.process_command("focus on Taiwan", _context()))
        assert result["action"]["type"] == "ui_command"

    def test_navigate_keyword(self):
        svc = LLMService()
        result = _run(svc.process_command("navigate to Fujian", _context()))
        assert result["action"]["type"] == "ui_command"

    def test_fujian_destination_resolved(self):
        svc = LLMService()
        result = _run(svc.process_command("fly to Fujian", _context()))
        dest = result["action"]["destination"]
        assert abs(dest["lat"] - 25.9) < 1.0
