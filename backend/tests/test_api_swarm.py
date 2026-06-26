"""API tests for /api/swarm/* endpoints."""
from __future__ import annotations

import pytest

from tests.conftest import make_position


# ─── GET /api/swarm/drones ────────────────────────────────────────────────────

class TestListDrones:
    def test_returns_seeded_drones(self, client):
        resp = client.get("/api/swarm/drones")
        assert resp.status_code == 200
        drones = resp.json()
        # 4 MQ-9 + 100 scout recon + 15 swarms × 5 representative drones = 179
        assert len(drones) == 179

    def test_drone_has_expected_fields(self, client):
        drone = client.get("/api/swarm/drones").json()[0]
        for field in ("id", "name", "type", "status", "battery"):
            assert field in drone

    def test_seeded_recon_drones_present(self, client):
        names = {d["name"] for d in client.get("/api/swarm/drones").json()}
        assert "MQ9-01" in names
        assert "MQ9-02" in names

    def test_seeded_fpv_drones_present(self, client):
        names = {d["name"] for d in client.get("/api/swarm/drones").json()}
        assert "FPV-Alpha-001" in names
        assert "FPV-Alpha-005" in names


# ─── POST /api/swarm/drones ───────────────────────────────────────────────────

class TestRegisterDrone:
    def test_registers_new_drone(self, client):
        payload = {"name": "Combat-99", "type": "combat"}
        resp = client.post("/api/swarm/drones", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Combat-99"
        assert body["type"] == "combat"
        assert "id" in body

    def test_new_drone_appears_in_list(self, client):
        client.post("/api/swarm/drones", json={"name": "X-1", "type": "recon"})
        names = {d["name"] for d in client.get("/api/swarm/drones").json()}
        assert "X-1" in names

    def test_drone_default_status_is_idle(self, client):
        resp = client.post("/api/swarm/drones", json={"name": "Y-1", "type": "combat"})
        assert resp.json()["status"] == "idle"

    def test_drone_default_battery_is_full(self, client):
        resp = client.post("/api/swarm/drones", json={"name": "Y-2", "type": "combat"})
        assert resp.json()["battery"] == 100.0

    def test_drone_with_position(self, client):
        payload = {
            "name": "Pos-1",
            "type": "recon",
            "position": make_position(lat=35.0, lon=-120.0, alt=300.0),
        }
        resp = client.post("/api/swarm/drones", json=payload)
        assert resp.status_code == 200
        pos = resp.json()["position"]
        assert abs(pos["lat"] - 35.0) < 1e-6


# ─── GET /api/swarm/drones/{id} ───────────────────────────────────────────────

class TestGetDroneById:
    def test_returns_correct_drone(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        resp = client.get(f"/api/swarm/drones/{drone_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == drone_id

    def test_not_found_returns_404(self, client):
        assert client.get("/api/swarm/drones/ghost-id").status_code == 404


# ─── PATCH /api/swarm/drones/{id} ────────────────────────────────────────────

class TestUpdateDroneTelemetry:
    def test_update_battery(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        resp = client.patch(f"/api/swarm/drones/{drone_id}", json={"battery": 42.5})
        assert resp.status_code == 200
        assert abs(resp.json()["battery"] - 42.5) < 1e-6

    def test_update_status(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        resp = client.patch(f"/api/swarm/drones/{drone_id}", json={"status": "patrolling"})
        assert resp.json()["status"] == "patrolling"

    def test_update_position(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        resp = client.patch(f"/api/swarm/drones/{drone_id}", json={
            "position": make_position(lat=50.0, lon=10.0),
        })
        assert abs(resp.json()["position"]["lat"] - 50.0) < 1e-6

    def test_partial_update_preserves_other_fields(self, client):
        drone = client.get("/api/swarm/drones").json()[0]
        original_name = drone["name"]
        client.patch(f"/api/swarm/drones/{drone['id']}", json={"battery": 10.0})
        updated = client.get(f"/api/swarm/drones/{drone['id']}").json()
        assert updated["name"] == original_name

    def test_not_found_returns_404(self, client):
        resp = client.patch("/api/swarm/drones/ghost-id", json={"battery": 50.0})
        assert resp.status_code == 404


# ─── POST /api/swarm/drones/{id}/command ─────────────────────────────────────

class TestCommandDrone:
    @pytest.mark.parametrize("cmd_type,expected_status", [
        ("locate",  "searching"),
        ("track",   "tracking"),
        ("attack",  "engaging"),
        ("patrol",  "patrolling"),
        ("return",  "returning"),
        ("abort",   "idle"),
    ])
    def test_command_updates_drone_status(self, client, cmd_type, expected_status):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        resp = client.post(f"/api/swarm/drones/{drone_id}/command", json={
            "command_type": cmd_type,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Verify via GET
        assert client.get(f"/api/swarm/drones/{drone_id}").json()["status"] == expected_status

    def test_command_with_objective(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        resp = client.post(f"/api/swarm/drones/{drone_id}/command", json={
            "command_type": "track",
            "objective": "Shadow enemy ship",
        })
        assert resp.json()["objective"] == "Shadow enemy ship"

    def test_not_found_returns_404(self, client):
        resp = client.post("/api/swarm/drones/ghost-id/command", json={"command_type": "patrol"})
        assert resp.status_code == 404


# ─── GET /api/swarm/swarms ────────────────────────────────────────────────────

class TestListSwarms:
    def test_returns_two_seeded_swarms(self, client):
        resp = client.get("/api/swarm/swarms")
        assert resp.status_code == 200
        assert len(resp.json()) == 15

    def test_swarm_has_drone_count(self, client):
        swarms = client.get("/api/swarm/swarms").json()
        for s in swarms:
            assert "drone_count" in s
            assert s["drone_count"] > 0

    def test_fpv_alpha_swarm_fleet_size(self, client):
        swarms = {s["name"]: s for s in client.get("/api/swarm/swarms").json()}
        assert swarms["FPV-Alpha"]["fleet_size"] == 1000

    def test_alt_alpha_swarm_fleet_size(self, client):
        swarms = {s["name"]: s for s in client.get("/api/swarm/swarms").json()}
        assert swarms["ALT-Alpha"]["fleet_size"] == 200

    def test_fpv_alpha_has_five_representative_drones(self, client):
        swarms = {s["name"]: s for s in client.get("/api/swarm/swarms").json()}
        assert swarms["FPV-Alpha"]["drone_count"] == 5

    def test_swarms_initially_idle(self, client):
        for s in client.get("/api/swarm/swarms").json():
            assert s["status"] == "idle"


# ─── POST /api/swarm/swarms ───────────────────────────────────────────────────

class TestCreateSwarm:
    def test_creates_new_swarm(self, client):
        resp = client.post("/api/swarm/swarms", json={"name": "Delta Swarm"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Delta Swarm"
        assert "id" in resp.json()

    def test_new_swarm_appears_in_list(self, client):
        client.post("/api/swarm/swarms", json={"name": "Echo Swarm"})
        names = {s["name"] for s in client.get("/api/swarm/swarms").json()}
        assert "Echo Swarm" in names

    def test_new_swarm_default_status_idle(self, client):
        resp = client.post("/api/swarm/swarms", json={"name": "Foxtrot"})
        assert resp.json()["status"] == "idle"


# ─── GET /api/swarm/swarms/{id} ───────────────────────────────────────────────

class TestGetSwarmById:
    def test_returns_swarm_with_drones(self, client, alpha_swarm_id):
        resp = client.get(f"/api/swarm/swarms/{alpha_swarm_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == alpha_swarm_id
        assert "drones" in body
        assert len(body["drones"]) == 5  # 5 representative drones per swarm

    def test_drones_have_full_detail(self, client, alpha_swarm_id):
        drones = client.get(f"/api/swarm/swarms/{alpha_swarm_id}").json()["drones"]
        for d in drones:
            assert "id" in d
            assert "name" in d
            assert "status" in d

    def test_not_found_returns_404(self, client):
        assert client.get("/api/swarm/swarms/ghost-id").status_code == 404


# ─── POST /api/swarm/swarms/{id}/command ─────────────────────────────────────

class TestCommandSwarm:
    @pytest.mark.parametrize("cmd_type,expected_swarm_status", [
        ("locate",  "searching"),
        ("track",   "tracking"),
        ("attack",  "engaging"),
        ("patrol",  "searching"),
        ("return",  "returning"),
        ("abort",   "idle"),
    ])
    def test_all_command_types(self, client, alpha_swarm_id, cmd_type, expected_swarm_status):
        resp = client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": cmd_type,
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Verify swarm status changed
        swarm = client.get(f"/api/swarm/swarms/{alpha_swarm_id}").json()
        assert swarm["status"] == expected_swarm_status

    def test_attack_command_propagates_to_all_drones(self, client, alpha_swarm_id):
        client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "attack",
            "target_ids": ["t-fake-1"],
        })
        drones = client.get(f"/api/swarm/swarms/{alpha_swarm_id}").json()["drones"]
        assert all(d["status"] == "engaging" for d in drones)

    def test_command_response_has_drones_tasked(self, client, alpha_swarm_id):
        resp = client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "locate",
        })
        assert resp.json()["drones_tasked"] == 5

    def test_command_with_objective(self, client, alpha_swarm_id):
        resp = client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "attack",
            "objective": "Destroy missile launchers",
            "priority": 9,
        })
        assert resp.json()["objective"] == "Destroy missile launchers"

    def test_command_sets_objective_on_swarm(self, client, alpha_swarm_id):
        client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "track",
            "objective": "Track enemy ships",
        })
        swarm = client.get(f"/api/swarm/swarms/{alpha_swarm_id}").json()
        assert swarm["objective"] == "Track enemy ships"

    def test_command_appears_in_log(self, client, alpha_swarm_id):
        client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "attack",
        })
        log = client.get("/api/swarm/log").json()
        entries = [e for e in log if e.get("type") == "swarm_command"]
        assert len(entries) >= 1

    def test_not_found_returns_404(self, client):
        resp = client.post("/api/swarm/swarms/ghost-id/command", json={
            "command_type": "attack",
        })
        assert resp.status_code == 404

    def test_priority_bounds_accepted(self, client, alpha_swarm_id):
        for priority in [1, 5, 10]:
            resp = client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
                "command_type": "patrol",
                "priority": priority,
            })
            assert resp.status_code == 200


# ─── GET /api/swarm/log ───────────────────────────────────────────────────────

class TestCommandLog:
    def test_empty_initially(self, client):
        assert client.get("/api/swarm/log").json() == []

    def test_command_appears_after_issue(self, client, alpha_swarm_id):
        client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "locate",
        })
        log = client.get("/api/swarm/log").json()
        assert len(log) == 1

    def test_limit_parameter(self, client, alpha_swarm_id):
        for _ in range(10):
            client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
                "command_type": "abort",
            })
        log = client.get("/api/swarm/log?limit=3").json()
        assert len(log) == 3

    def test_log_entry_has_timestamp(self, client, alpha_swarm_id):
        client.post(f"/api/swarm/swarms/{alpha_swarm_id}/command", json={
            "command_type": "return",
        })
        entry = client.get("/api/swarm/log").json()[0]
        assert "timestamp" in entry


# ─── POST /api/swarm/telemetry ────────────────────────────────────────────────

class TestBatchTelemetry:
    def test_single_report_updates_drone(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        resp = client.post("/api/swarm/telemetry", json={"reports": [{
            "drone_id": drone_id,
            "position": {"lat": 25.10, "lon": 121.60, "alt": 6500.0},
            "heading": 45.0,
            "speed": 60.0,
            "battery": 88.5,
        }]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["updated"] == 1
        assert body["not_found"] == []

    def test_position_actually_updated(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        client.post("/api/swarm/telemetry", json={"reports": [{
            "drone_id": drone_id,
            "position": {"lat": 24.00, "lon": 121.00, "alt": 3000.0},
            "heading": 90.0,
            "speed": 42.0,
        }]})
        drone = client.get(f"/api/swarm/drones/{drone_id}").json()
        assert abs(drone["position"]["lat"] - 24.00) < 1e-6
        assert abs(drone["position"]["lon"] - 121.00) < 1e-6

    def test_battery_updated_when_provided(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        client.post("/api/swarm/telemetry", json={"reports": [{
            "drone_id": drone_id,
            "position": {"lat": 25.04, "lon": 121.56, "alt": 6000.0},
            "heading": 0.0,
            "speed": 60.0,
            "battery": 55.0,
        }]})
        assert client.get(f"/api/swarm/drones/{drone_id}").json()["battery"] == 55.0

    def test_unknown_drone_goes_to_not_found(self, client):
        resp = client.post("/api/swarm/telemetry", json={"reports": [{
            "drone_id": "ghost-drone",
            "position": {"lat": 25.0, "lon": 121.0, "alt": 100.0},
            "heading": 0.0,
            "speed": 0.0,
        }]})
        body = resp.json()
        assert body["updated"] == 0
        assert "ghost-drone" in body["not_found"]

    def test_batch_of_multiple_reports(self, client):
        drones = client.get("/api/swarm/drones").json()[:3]
        reports = [{
            "drone_id": d["id"],
            "position": {"lat": 25.0, "lon": 121.0, "alt": 100.0},
            "heading": float(i * 30),
            "speed": 42.0,
        } for i, d in enumerate(drones)]
        resp = client.post("/api/swarm/telemetry", json={"reports": reports})
        assert resp.json()["updated"] == 3

    def test_status_override_applied(self, client):
        drone_id = client.get("/api/swarm/drones").json()[0]["id"]
        client.post("/api/swarm/telemetry", json={"reports": [{
            "drone_id": drone_id,
            "position": {"lat": 25.04, "lon": 121.56, "alt": 6000.0},
            "heading": 0.0,
            "speed": 60.0,
            "status": "returning",
        }]})
        assert client.get(f"/api/swarm/drones/{drone_id}").json()["status"] == "returning"
