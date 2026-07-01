"""API tests for /api/recon/* endpoints."""
from __future__ import annotations

import pytest

from tests.conftest import make_recon_feed, make_target_report, make_position


# ─── POST /api/recon/feed ─────────────────────────────────────────────────────

class TestSubmitReconFeed:
    def test_creates_single_target(self, client):
        resp = client.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(type="tank"),
        ]))
        assert resp.status_code == 200
        body = resp.json()
        assert body["received"] == 1
        assert body["created"] == 1
        assert body["updated"] == 0

    def test_creates_multiple_targets(self, client):
        resp = client.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(type="tank"),
            make_target_report(type="ship", lat=34.06, lon=-118.25),
            make_target_report(type="drone", lat=34.07, lon=-118.26),
        ]))
        assert resp.status_code == 200
        body = resp.json()
        assert body["received"] == 3
        assert body["created"] == 3

    def test_target_has_correct_type(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(type="missile_launcher"),
        ]))
        targets = client_empty.get("/api/recon/targets").json()
        assert targets[0]["type"] == "missile_launcher"

    def test_target_has_correct_position(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(lat=10.1234, lon=20.5678),
        ]))
        target = client_empty.get("/api/recon/targets").json()[0]
        assert abs(target["position"]["lat"] - 10.1234) < 1e-6
        assert abs(target["position"]["lon"] - 20.5678) < 1e-6

    def test_target_has_correct_confidence(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(confidence=0.73),
        ]))
        target = client_empty.get("/api/recon/targets").json()[0]
        assert abs(target["confidence"] - 0.73) < 1e-6

    def test_target_reported_by_drone_id(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed(drone_id="R-99", targets=[
            make_target_report(),
        ]))
        target = client_empty.get("/api/recon/targets").json()[0]
        assert target["reported_by"] == "R-99"

    def test_target_has_active_status_by_default(self, client):
        client.post("/api/recon/feed", json=make_recon_feed())
        target = client.get("/api/recon/targets").json()[0]
        assert target["status"] == "active"

    def test_updates_existing_target_by_id(self, client):
        # Create a target first
        client.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(lat=34.05, lon=-118.24),
        ]))
        target_id = client.get("/api/recon/targets").json()[0]["id"]

        # Update it
        resp = client.post("/api/recon/feed", json=make_recon_feed(targets=[{
            "type": "tank",
            "position": make_position(lat=34.99, lon=-119.99),
            "confidence": 0.55,
            "existing_target_id": target_id,
        }]))
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1
        assert resp.json()["created"] == 0

        # Verify updated position
        updated = client.get(f"/api/recon/targets/{target_id}").json()
        assert abs(updated["position"]["lat"] - 34.99) < 1e-4

    def test_update_only_one_target_in_store(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed())
        target_id = client_empty.get("/api/recon/targets").json()[0]["id"]

        client_empty.post("/api/recon/feed", json=make_recon_feed(targets=[{
            "type": "tank",
            "position": make_position(),
            "confidence": 0.5,
            "existing_target_id": target_id,
        }]))
        # Still only one target
        assert len(client_empty.get("/api/recon/targets").json()) == 1

    def test_updates_recon_drone_status_to_patrolling(self, client):
        # MQ9-01 is a seeded recon drone
        client.post("/api/recon/feed", json=make_recon_feed(drone_id="MQ9-01"))
        drones = client.get("/api/swarm/drones").json()
        mq9_01 = next(d for d in drones if d["name"] == "MQ9-01")
        assert mq9_01["status"] == "patrolling"

    def test_unknown_recon_drone_id_still_creates_targets(self, client):
        resp = client.post("/api/recon/feed", json=make_recon_feed(drone_id="UNKNOWN-99"))
        assert resp.status_code == 200
        assert resp.json()["created"] == 1

    def test_target_notes_stored(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed(targets=[
            {**make_target_report(), "notes": "Spotted near bridge"},
        ]))
        target = client_empty.get("/api/recon/targets").json()[0]
        assert target["notes"] == "Spotted near bridge"

    def test_all_target_types_accepted(self, client):
        types = ["drone", "ship", "tank", "missile_launcher", "soldier_unit"]
        for t in types:
            client.post("/api/recon/feed", json=make_recon_feed(targets=[
                make_target_report(type=t),
            ]))
        all_types = {t["type"] for t in client.get("/api/recon/targets").json()}
        assert all_types == set(types)


# ─── GET /api/recon/targets ───────────────────────────────────────────────────

class TestGetTargets:
    def _seed(self, client, n=3):
        types = ["tank", "ship", "drone"]
        for i in range(n):
            client.post("/api/recon/feed", json=make_recon_feed(targets=[
                make_target_report(type=types[i % len(types)], lat=34.0 + i * 0.01),
            ]))

    def test_returns_empty_initially(self, client_empty):
        assert client_empty.get("/api/recon/targets").json() == []

    def test_returns_all_targets(self, client_empty):
        self._seed(client_empty, 3)
        assert len(client_empty.get("/api/recon/targets").json()) == 3

    def test_filter_by_type(self, client):
        self._seed(client, 3)
        tanks = client.get("/api/recon/targets?type=tank").json()
        assert all(t["type"] == "tank" for t in tanks)

    def test_filter_by_status(self, client):
        self._seed(client, 2)
        first_id = client.get("/api/recon/targets").json()[0]["id"]
        client.patch(f"/api/recon/targets/{first_id}/status?status=destroyed")

        active = client.get("/api/recon/targets?status=active").json()
        assert all(t["status"] == "active" for t in active)
        assert not any(t["id"] == first_id for t in active)

    def test_filter_by_min_confidence(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(confidence=0.95),
            make_target_report(confidence=0.40, lat=34.06),
        ]))
        high = client_empty.get("/api/recon/targets?min_confidence=0.8").json()
        assert len(high) == 1
        assert high[0]["confidence"] >= 0.8

    def test_multiple_filters_combined(self, client_empty):
        client_empty.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(type="tank", confidence=0.9),
            make_target_report(type="ship", confidence=0.3, lat=34.06),
            make_target_report(type="tank", confidence=0.2, lat=34.07),
        ]))
        results = client_empty.get("/api/recon/targets?type=tank&min_confidence=0.8").json()
        assert len(results) == 1
        assert results[0]["type"] == "tank"
        assert results[0]["confidence"] >= 0.8

    def test_excludes_friendly_affiliated_targets(self, client):
        # The seeded scenario includes 1000 friendly soldier_unit Targets; the
        # enemy intel feed endpoint must never surface them.
        results = client.get("/api/recon/targets").json()
        assert len(results) > 0
        assert all(t.get("affiliation", "enemy") == "enemy" for t in results)
        assert not any(t["type"] == "soldier_unit" and t.get("affiliation") == "friendly" for t in results)


# ─── GET /api/recon/targets/{id} ─────────────────────────────────────────────

class TestGetTargetById:
    def test_returns_correct_target(self, client):
        client.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(type="ship"),
        ]))
        # Filter by reported_by so this grabs the target just created, not one
        # of the many enemy assets already present in the seeded scenario.
        target_id = client.get("/api/recon/targets?reported_by=MQ9-01").json()[0]["id"]
        resp = client.get(f"/api/recon/targets/{target_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == target_id
        assert resp.json()["type"] == "ship"

    def test_not_found_returns_404(self, client):
        resp = client.get("/api/recon/targets/does-not-exist")
        assert resp.status_code == 404


# ─── PATCH /api/recon/targets/{id}/status ────────────────────────────────────

class TestUpdateTargetStatus:
    @pytest.mark.parametrize("new_status", ["active", "tracked", "engaged", "destroyed", "lost"])
    def test_all_valid_statuses(self, client, new_status):
        client.post("/api/recon/feed", json=make_recon_feed())
        tid = client.get("/api/recon/targets").json()[0]["id"]
        resp = client.patch(f"/api/recon/targets/{tid}/status?status={new_status}")
        assert resp.status_code == 200
        assert resp.json()["status"] == new_status

    def test_not_found_returns_404(self, client):
        resp = client.patch("/api/recon/targets/ghost/status?status=destroyed")
        assert resp.status_code == 404


# ─── DELETE /api/recon/targets/{id} ──────────────────────────────────────────

class TestDeleteTarget:
    def test_removes_target(self, client):
        client.post("/api/recon/feed", json=make_recon_feed())
        tid = client.get("/api/recon/targets").json()[0]["id"]

        resp = client.delete(f"/api/recon/targets/{tid}")
        assert resp.status_code == 200
        assert resp.json()["removed"] == tid

        # Confirm gone
        assert client.get(f"/api/recon/targets/{tid}").status_code == 404

    def test_not_found_returns_404(self, client):
        resp = client.delete("/api/recon/targets/ghost")
        assert resp.status_code == 404

    def test_delete_reduces_count(self, client):
        before = len(client.get("/api/recon/targets").json())
        client.post("/api/recon/feed", json=make_recon_feed(targets=[
            make_target_report(),
            make_target_report(lat=34.06),
        ]))
        targets = client.get("/api/recon/targets").json()
        assert len(targets) == before + 2
        client.delete(f"/api/recon/targets/{targets[0]['id']}")
        assert len(client.get("/api/recon/targets").json()) == before + 1
