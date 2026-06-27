"""
Shared pytest fixtures and helpers for Lattice backend tests.

State isolation strategy
────────────────────────
The production code uses module-level singletons (state_service, swarm_service,
llm_service).  Each test that touches these singletons receives a *fresh*
StateService via the ``client`` fixture, which monkey-patches every import site
so all API routes and service calls operate against isolated, seeded state.
"""
from __future__ import annotations

import sys
import os
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure backend package root is on sys.path so relative imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_position(lat: float = 34.05, lon: float = -118.24, alt: float = 100.0) -> dict:
    return {"lat": lat, "lon": lon, "alt": alt}


def make_target_report(
    type: str = "tank",
    lat: float = 34.05,
    lon: float = -118.24,
    confidence: float = 0.9,
    **kwargs,
) -> dict:
    return {"type": type, "position": make_position(lat, lon), "confidence": confidence, **kwargs}


def make_recon_feed(drone_id: str = "MQ9-01", targets: list[dict] | None = None) -> dict:
    return {
        "recon_drone_id": drone_id,
        "targets": targets if targets is not None else [make_target_report()],
    }


# ─── Fixtures ─────────────────────────────────────────────────────────────────

# All module namespaces that hold a reference to `state_service`
_STATE_PATCH_TARGETS = [
    "api.recon.state_service",
    "api.swarm.state_service",
    "api.nlp.state_service",
    "services.swarm_service.state_service",
    "main.state_service",
]


@pytest.fixture
def fresh_state():
    """A freshly seeded StateService instance (isolated from the singleton)."""
    from services.state_service import StateService
    return StateService()


@pytest.fixture
def empty_state():
    """A StateService with no seeded data — useful for count-sensitive tests."""
    from services.state_service import StateService

    svc = StateService.__new__(StateService)
    import threading
    svc._lock = threading.Lock()
    svc._targets = {}
    svc._drones = {}
    svc._swarms = {}
    svc._approvals = {}
    svc._command_log = []
    return svc


@pytest.fixture
def client(fresh_state) -> Generator[TestClient, None, None]:
    """
    TestClient wired to a fresh, isolated battlefield state.
    OPENAI_API_KEY is unset so LLMService always uses the mock path.
    """
    patches = [patch(target, fresh_state) for target in _STATE_PATCH_TARGETS]
    for p in patches:
        p.start()

    env_patch = patch.dict(os.environ, {}, clear=False)
    env_patch.start()
    os.environ.pop("OPENAI_API_KEY", None)

    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    for p in patches:
        p.stop()
    env_patch.stop()


@pytest.fixture
def client_empty(empty_state) -> Generator[TestClient, None, None]:
    """TestClient with zero seeded drones/swarms (empty slate)."""
    patches = [patch(target, empty_state) for target in _STATE_PATCH_TARGETS]
    for p in patches:
        p.start()

    os.environ.pop("OPENAI_API_KEY", None)

    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    for p in patches:
        p.stop()


@pytest.fixture
def seeded_target(client) -> dict:
    """Post one recon feed and return the created target object."""
    resp = client.post("/api/recon/feed", json=make_recon_feed())
    assert resp.status_code == 200
    # Use reported_by filter so we get only the target we just posted,
    # not the 23 targets seeded at startup (which have reported_by="seed").
    targets = client.get("/api/recon/targets?reported_by=MQ9-01").json()
    assert len(targets) == 1
    return targets[0]


@pytest.fixture
def alpha_swarm_id(client) -> str:
    """Return the ID of the seeded FPV-Alpha swarm."""
    swarms = client.get("/api/swarm/swarms").json()
    alpha = next(s for s in swarms if s["name"] == "FPV-Alpha")
    return alpha["id"]


@pytest.fixture
def bravo_swarm_id(client) -> str:
    """Return the ID of the seeded FPV-Bravo swarm."""
    swarms = client.get("/api/swarm/swarms").json()
    bravo = next(s for s in swarms if s["name"] == "FPV-Bravo")
    return bravo["id"]
