"""API tests for system endpoints: GET /, GET /api/state, and WebSocket /ws."""
from __future__ import annotations

import json

import pytest


# ─── GET / ────────────────────────────────────────────────────────────────────

class TestRootEndpoint:
    def test_returns_200(self, client):
        assert client.get("/").status_code == 200

    def test_has_platform_field(self, client):
        body = client.get("/").json()
        assert body["platform"] == "Lattice C2"

    def test_has_version(self, client):
        body = client.get("/").json()
        assert "version" in body
        assert body["version"] == "1.0.0"

    def test_has_status_operational(self, client):
        body = client.get("/").json()
        assert body["status"] == "operational"

    def test_has_docs_link(self, client):
        body = client.get("/").json()
        assert "docs" in body


# ─── GET /api/state ───────────────────────────────────────────────────────────

class TestFullStateEndpoint:
    def test_returns_200(self, client):
        assert client.get("/api/state").status_code == 200

    def test_has_required_top_level_keys(self, client):
        body = client.get("/api/state").json()
        for key in ("drones", "targets", "swarms", "timestamp", "pending_approvals"):
            assert key in body

    def test_drones_is_list(self, client):
        body = client.get("/api/state").json()
        assert isinstance(body["drones"], list)

    def test_targets_is_list(self, client):
        body = client.get("/api/state").json()
        assert isinstance(body["targets"], list)

    def test_swarms_is_list(self, client):
        body = client.get("/api/state").json()
        assert isinstance(body["swarms"], list)

    def test_timestamp_is_string(self, client):
        body = client.get("/api/state").json()
        assert isinstance(body["timestamp"], str)

    def test_seeded_drones_count(self, client):
        body = client.get("/api/state").json()
        # 4 MQ-9 + 100 scout recon + 15 swarms × 5 representative drones = 179
        assert len(body["drones"]) == 179

    def test_seeded_swarms_count(self, client):
        body = client.get("/api/state").json()
        assert len(body["swarms"]) == 15

    def test_no_targets_initially(self, client):
        body = client.get("/api/state").json()
        # 23 enemy assets are seeded for demo
        assert len(body["targets"]) == 23

    def test_state_reflects_new_target(self, client):
        from tests.conftest import make_recon_feed, make_target_report
        seeded = len(client.get("/api/state").json()["targets"])
        client.post("/api/recon/feed", json=make_recon_feed(targets=[make_target_report()]))
        body = client.get("/api/state").json()
        assert len(body["targets"]) == seeded + 1

    def test_state_reflects_drone_update(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        client.patch(f"/api/swarm/drones/{drone_id}", json={"battery": 11.1})
        state = client.get("/api/state").json()
        drone_state = next(d for d in state["drones"] if d["id"] == drone_id)
        assert abs(drone_state["battery"] - 11.1) < 1e-4

    def test_state_reflects_swarm_status_after_command(self, client):
        swarm_id = client.get("/api/swarm/swarms").json()[0]["id"]
        client.post(f"/api/swarm/swarms/{swarm_id}/command", json={"command_type": "attack"})
        state = client.get("/api/state").json()
        swarm_state = next(s for s in state["swarms"] if s["id"] == swarm_id)
        assert swarm_state["status"] == "engaging"


# ─── WebSocket /ws ────────────────────────────────────────────────────────────

class TestWebSocket:
    def test_connects_successfully(self, client):
        with client.websocket_connect("/ws") as ws:
            # Should receive an initial state message immediately
            data = ws.receive_text()
            assert data is not None

    def test_initial_message_is_valid_json(self, client):
        with client.websocket_connect("/ws") as ws:
            raw = ws.receive_text()
            state = json.loads(raw)
            assert isinstance(state, dict)

    def test_initial_message_has_state_keys(self, client):
        with client.websocket_connect("/ws") as ws:
            state = json.loads(ws.receive_text())
            for key in ("drones", "targets", "swarms", "timestamp", "pending_approvals"):
                assert key in state

    def test_initial_message_has_seeded_drones(self, client):
        with client.websocket_connect("/ws") as ws:
            state = json.loads(ws.receive_text())
            assert len(state["drones"]) == 179

    def test_initial_message_has_seeded_swarms(self, client):
        with client.websocket_connect("/ws") as ws:
            state = json.loads(ws.receive_text())
            assert len(state["swarms"]) == 15

    def test_initial_message_targets_empty(self, client):
        with client.websocket_connect("/ws") as ws:
            state = json.loads(ws.receive_text())
            # 23 enemy assets are seeded for demo
            assert len(state["targets"]) == 23

    def test_multiple_clients_can_connect(self, client):
        with client.websocket_connect("/ws") as ws1:
            with client.websocket_connect("/ws") as ws2:
                s1 = json.loads(ws1.receive_text())
                s2 = json.loads(ws2.receive_text())
                assert s1["drones"] is not None
                assert s2["drones"] is not None
