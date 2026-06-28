"""API tests for /api/nlp/* endpoints.

The LLMService mock path is used throughout (no OPENAI_API_KEY in test env).
"""
from __future__ import annotations

import pytest

from tests.conftest import make_recon_feed, make_target_report


# ─── POST /api/nlp/command ────────────────────────────────────────────────────

class TestNLPCommand:
    def test_returns_200_for_valid_command(self, client):
        resp = client.post("/api/nlp/command", json={"command": "find all enemies"})
        assert resp.status_code == 200

    def test_response_has_required_fields(self, client):
        resp = client.post("/api/nlp/command", json={"command": "search the area"})
        body = resp.json()
        for key in ("command", "interpretation", "explanation", "action", "execution_result"):
            assert key in body

    def test_command_echoed_in_response(self, client):
        cmd = "locate enemy drones in sector 7"
        resp = client.post("/api/nlp/command", json={"command": cmd})
        assert resp.json()["command"] == cmd

    def test_empty_command_returns_400(self, client):
        resp = client.post("/api/nlp/command", json={"command": ""})
        assert resp.status_code == 400

    def test_whitespace_only_command_returns_400(self, client):
        resp = client.post("/api/nlp/command", json={"command": "   "})
        assert resp.status_code == 400

    def test_attack_command_triggers_approval_request(self, client):
        resp = client.post("/api/nlp/command", json={"command": "attack all targets"})
        body = resp.json()
        assert body["action"]["type"] == "request_approval"

    def test_locate_command_triggers_swarm_assignment(self, client):
        resp = client.post("/api/nlp/command", json={"command": "search for enemy ships"})
        body = resp.json()
        assert body["action"]["type"] == "assign_swarm"
        assert body["action"]["command_type"] == "locate"

    def test_track_command_routes_through_hitl(self, client):
        """Track now routes through HITL with a recon drone (Feature 24)."""
        resp = client.post("/api/nlp/command", json={"command": "track enemy movements"})
        body = resp.json()
        assert body["action"]["type"] == "request_approval"
        assert body["action"]["proposed_action"]["command_type"] == "track"
        assert body["action"]["proposed_action"]["type"] == "assign_drone"

    def test_return_command_triggers_swarm_assignment(self, client):
        resp = client.post("/api/nlp/command", json={"command": "recall all units rtb"})
        body = resp.json()
        assert body["action"]["type"] == "assign_swarm"
        assert body["action"]["command_type"] == "return"

    def test_attack_command_returns_pending_approval(self, client):
        """Attack NLP command now goes through HITL — returns pending approval, not immediate execution."""
        resp = client.post("/api/nlp/command", json={"command": "engage all enemies"})
        body = resp.json()
        assert body["execution_result"] is not None
        assert body["execution_result"]["status"] == "pending"
        assert "approval_id" in body["execution_result"]

    def test_attack_command_does_not_immediately_engage_swarms(self, client):
        """Without approval, no swarm should be set to engaging status."""
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        swarms = client.get("/api/swarm/swarms").json()
        assert not any(s["status"] == "engaging" for s in swarms)

    def test_return_command_changes_swarm_to_returning(self, client):
        client.post("/api/nlp/command", json={"command": "return to base"})
        swarms = client.get("/api/swarm/swarms").json()
        assert any(s["status"] == "returning" for s in swarms)

    def test_attack_with_active_targets_includes_classified_targets(self, client):
        # Seed an active target
        client.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(type="tank"),
        ]))
        resp = client.post("/api/nlp/command", json={"command": "attack all targets"})
        action = resp.json()["action"]
        assert action["type"] == "request_approval"
        assert len(action["classified_targets"]) >= 1

    def test_context_override_replaces_battlefield_state(self, client):
        """context_override lets callers inject custom context for LLM processing."""
        custom_ctx = {
            "swarms": [{"id": "custom-s1", "name": "Custom Swarm", "status": "idle"}],
            "drones": [],
            "targets": [{"id": "custom-t1", "type": "ship", "status": "active",
                         "confidence": 0.9, "position": {"lat": 24.0, "lon": 120.0, "alt": 0}}],
        }
        resp = client.post("/api/nlp/command", json={
            "command": "attack all ships",
            "context_override": custom_ctx,
        })
        assert resp.status_code == 200
        # Attack goes through HITL — proposed_action should reference the custom swarm
        action = resp.json()["action"]
        assert action["type"] == "request_approval"
        assert action["proposed_action"]["swarm_id"] == "custom-s1"

    def test_unknown_command_returns_none_action(self, client):
        resp = client.post("/api/nlp/command", json={"command": "do absolutely nothing"})
        assert resp.status_code == 200
        # Mock returns none for unrecognised commands; no execution
        assert resp.json()["action"]["type"] == "none"
        assert resp.json()["execution_result"] is None


# ─── NLP command is logged ────────────────────────────────────────────────────

class TestNLPCommandLogging:
    def test_command_appears_in_history(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        history = client.get("/api/nlp/history").json()
        assert len(history) == 1
        assert history[0]["type"] == "nlp_command"
        assert history[0]["raw_command"] == "attack all targets"

    def test_multiple_commands_all_logged(self, client):
        for cmd in ["attack", "search the area", "return to base"]:
            client.post("/api/nlp/command", json={"command": cmd})
        history = client.get("/api/nlp/history").json()
        assert len(history) == 3

    def test_log_entry_has_interpretation(self, client):
        client.post("/api/nlp/command", json={"command": "locate enemies"})
        entry = client.get("/api/nlp/history").json()[0]
        assert "interpretation" in entry
        assert entry["interpretation"] is not None

    def test_log_entry_has_timestamp(self, client):
        client.post("/api/nlp/command", json={"command": "search area"})
        entry = client.get("/api/nlp/history").json()[0]
        assert "timestamp" in entry


# ─── GET /api/nlp/history ─────────────────────────────────────────────────────

class TestNLPHistory:
    def test_empty_initially(self, client):
        assert client.get("/api/nlp/history").json() == []

    def test_history_contains_only_nlp_entries(self, client, alpha_swarm_id):
        # Issue a direct swarm command (not NLP)
        client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "locate",
        })
        # Issue an NLP command
        client.post("/api/nlp/command", json={"command": "track targets"})

        history = client.get("/api/nlp/history").json()
        allowed_types = {"nlp_command", "hitl_approved", "hitl_denied"}
        assert all(e["type"] in allowed_types for e in history)
        assert len(history) == 1

    def test_limit_parameter(self, client):
        for i in range(10):
            client.post("/api/nlp/command", json={"command": f"attack target {i}"})
        history = client.get("/api/nlp/history?limit=3").json()
        assert len(history) == 3


# ─── HITL Attack Approval (Feature 13) ───────────────────────────────────────

class TestHITLApproval:
    """Tests for the human-in-the-loop attack approval flow."""

    # -- request_approval action -------------------------------------------------

    def test_attack_command_returns_request_approval_type(self, client):
        resp = client.post("/api/nlp/command", json={"command": "destroy enemy ships"})
        assert resp.json()["action"]["type"] == "request_approval"

    def test_request_approval_has_approval_prompt(self, client):
        resp = client.post("/api/nlp/command", json={"command": "engage all targets"})
        action = resp.json()["action"]
        assert "approval_prompt" in action
        assert len(action["approval_prompt"]) > 10

    def test_request_approval_has_threat_summary(self, client):
        resp = client.post("/api/nlp/command", json={"command": "strike all enemies"})
        action = resp.json()["action"]
        assert "threat_summary" in action
        summary = action["threat_summary"]
        assert "high" in summary and "medium" in summary and "low" in summary

    def test_request_approval_has_classified_targets(self, client):
        resp = client.post("/api/nlp/command", json={"command": "attack all targets"})
        action = resp.json()["action"]
        assert "classified_targets" in action

    def test_classified_targets_have_threat_value(self, client):
        resp = client.post("/api/nlp/command", json={"command": "attack all targets"})
        targets = resp.json()["action"]["classified_targets"]
        for t in targets:
            assert t["threat_value"] in ("high", "medium", "low")

    def test_request_approval_has_proposed_action(self, client):
        resp = client.post("/api/nlp/command", json={"command": "destroy enemy tanks"})
        action = resp.json()["action"]
        assert "proposed_action" in action
        assert action["proposed_action"]["type"] == "assign_swarm"
        assert action["proposed_action"]["command_type"] == "attack"

    def test_attack_command_creates_pending_approval(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        pending = client.get("/api/nlp/pending").json()
        assert len(pending) == 1

    def test_ship_classified_as_high_threat(self, client):
        custom_ctx = {
            "swarms": [{"id": "s1", "name": "FPV-Alpha", "status": "idle"}],
            "drones": [],
            "targets": [{"id": "t1", "type": "ship", "status": "active",
                         "position": {"lat": 24.0, "lon": 120.0, "alt": 0}}],
        }
        resp = client.post("/api/nlp/command", json={
            "command": "destroy the ship", "context_override": custom_ctx,
        })
        targets = resp.json()["action"]["classified_targets"]
        ship_entry = next((t for t in targets if t["type"] == "ship"), None)
        assert ship_entry is not None
        assert ship_entry["threat_value"] == "high"

    def test_missile_launcher_classified_as_high_threat(self, client):
        custom_ctx = {
            "swarms": [{"id": "s1", "name": "ALT-Alpha", "status": "idle"}],
            "drones": [],
            "targets": [{"id": "t1", "type": "missile_launcher", "status": "active",
                         "position": {"lat": 24.0, "lon": 120.0, "alt": 0}}],
        }
        resp = client.post("/api/nlp/command", json={
            "command": "strike the launcher", "context_override": custom_ctx,
        })
        targets = resp.json()["action"]["classified_targets"]
        assert targets[0]["threat_value"] == "high"

    def test_tank_classified_as_medium_threat(self, client):
        custom_ctx = {
            "swarms": [{"id": "s1", "name": "ALT-Alpha", "status": "idle"}],
            "drones": [],
            "targets": [{"id": "t1", "type": "tank", "status": "active",
                         "position": {"lat": 24.0, "lon": 120.0, "alt": 0}}],
        }
        resp = client.post("/api/nlp/command", json={
            "command": "destroy the tank", "context_override": custom_ctx,
        })
        targets = resp.json()["action"]["classified_targets"]
        assert targets[0]["threat_value"] == "medium"

    def test_high_altitude_drone_classified_as_medium(self, client):
        custom_ctx = {
            "swarms": [{"id": "s1", "name": "ALT-Alpha", "status": "idle"}],
            "drones": [],
            "targets": [{"id": "t1", "type": "drone", "status": "active",
                         "position": {"lat": 24.0, "lon": 120.0, "alt": 2000}}],
        }
        resp = client.post("/api/nlp/command", json={
            "command": "attack the drone", "context_override": custom_ctx,
        })
        targets = resp.json()["action"]["classified_targets"]
        assert targets[0]["threat_value"] == "medium"

    def test_low_altitude_drone_classified_as_low(self, client):
        custom_ctx = {
            "swarms": [{"id": "s1", "name": "FPV-Alpha", "status": "idle"}],
            "drones": [],
            "targets": [{"id": "t1", "type": "drone", "status": "active",
                         "position": {"lat": 24.0, "lon": 120.0, "alt": 50}}],
        }
        resp = client.post("/api/nlp/command", json={
            "command": "destroy the fpv", "context_override": custom_ctx,
        })
        targets = resp.json()["action"]["classified_targets"]
        assert targets[0]["threat_value"] == "low"

    # -- GET /api/nlp/pending ----------------------------------------------------

    def test_get_pending_returns_empty_initially(self, client):
        assert client.get("/api/nlp/pending").json() == []

    def test_get_pending_after_attack_command(self, client):
        client.post("/api/nlp/command", json={"command": "attack enemy ships"})
        pending = client.get("/api/nlp/pending").json()
        assert len(pending) >= 1

    def test_pending_approval_has_required_fields(self, client):
        client.post("/api/nlp/command", json={"command": "engage all targets"})
        approval = client.get("/api/nlp/pending").json()[0]
        for key in ("id", "command", "approval_prompt", "threat_summary",
                    "classified_targets", "proposed_action", "status", "created_at", "expires_at"):
            assert key in approval, f"Missing field: {key}"

    def test_pending_approval_status_is_pending(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval = client.get("/api/nlp/pending").json()[0]
        assert approval["status"] == "pending"

    def test_multiple_attack_commands_create_multiple_approvals(self, client):
        client.post("/api/nlp/command", json={"command": "attack enemy ships"})
        client.post("/api/nlp/command", json={"command": "destroy all tanks"})
        pending = client.get("/api/nlp/pending").json()
        assert len(pending) == 2

    # -- POST /api/nlp/approve/{id} ----------------------------------------------

    def test_approve_returns_200(self, client):
        client.post("/api/nlp/command", json={"command": "attack enemy ships"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        resp = client.post(f"/api/nlp/approve/{approval_id}")
        assert resp.status_code == 200

    def test_approve_executes_proposed_action(self, client):
        client.post("/api/nlp/command", json={"command": "attack enemy ships"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        resp = client.post(f"/api/nlp/approve/{approval_id}")
        assert resp.json()["approved"] is True
        assert resp.json()["execution_result"] is not None

    def test_approve_changes_swarm_status_to_engaging(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        client.post(f"/api/nlp/approve/{approval_id}")
        swarms = client.get("/api/swarm/swarms").json()
        assert any(s["status"] == "engaging" for s in swarms)

    def test_approve_removes_from_pending_list(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        client.post(f"/api/nlp/approve/{approval_id}")
        # approved items should no longer appear in pending list
        pending = client.get("/api/nlp/pending").json()
        assert all(a["id"] != approval_id for a in pending)

    def test_approve_nonexistent_returns_404(self, client):
        resp = client.post("/api/nlp/approve/does-not-exist")
        assert resp.status_code == 404

    def test_double_approve_returns_409(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        client.post(f"/api/nlp/approve/{approval_id}")
        resp = client.post(f"/api/nlp/approve/{approval_id}")
        assert resp.status_code == 409

    # -- POST /api/nlp/deny/{id} -------------------------------------------------

    def test_deny_returns_200(self, client):
        client.post("/api/nlp/command", json={"command": "attack enemy ships"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        resp = client.post(f"/api/nlp/deny/{approval_id}")
        assert resp.status_code == 200

    def test_deny_sets_status_to_denied(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        resp = client.post(f"/api/nlp/deny/{approval_id}")
        assert resp.json()["denied"] is True

    def test_deny_does_not_execute_swarm_command(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        client.post(f"/api/nlp/deny/{approval_id}")
        swarms = client.get("/api/swarm/swarms").json()
        assert not any(s["status"] == "engaging" for s in swarms)

    def test_deny_removes_from_pending_list(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        client.post(f"/api/nlp/deny/{approval_id}")
        pending = client.get("/api/nlp/pending").json()
        assert all(a["id"] != approval_id for a in pending)

    def test_deny_nonexistent_returns_404(self, client):
        resp = client.post("/api/nlp/deny/does-not-exist")
        assert resp.status_code == 404

    def test_deny_is_logged(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        client.post(f"/api/nlp/deny/{approval_id}")
        log = client.get("/api/nlp/history").json()
        deny_entries = [e for e in log if e.get("type") == "hitl_denied"]
        assert len(deny_entries) == 1

    def test_approve_is_logged(self, client):
        client.post("/api/nlp/command", json={"command": "attack all targets"})
        approval_id = client.get("/api/nlp/pending").json()[0]["id"]
        client.post(f"/api/nlp/approve/{approval_id}")
        log = client.get("/api/nlp/history").json()
        approve_entries = [e for e in log if e.get("type") == "hitl_approved"]
        assert len(approve_entries) == 1
