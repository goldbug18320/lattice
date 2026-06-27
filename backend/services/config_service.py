"""Loads and exposes the assets configuration (assets_config.json)."""
from __future__ import annotations
import json
import os

# Zero-count defaults: the system deploys NO assets by default.
# The checked-in assets_config.json is the authoritative default scenario.
# If that file is absent or empty, the battlefield starts with no assets.
_DEFAULTS: dict = {
    "mq9": {
        "count": 0,
        "detection_radius_km": 15.0,
        "max_flight_time_hours": 30.0,
        "max_range_km": 1900.0,
        "always_airborne": 2,
    },
    "scout_recon": {
        "count": 0,
        "max_range_km": 150.0,
        "max_speed_kmh": 150.0,
        "detection_radius_km": 10.0,
    },
    "fpv_combat": {
        "count": 0,
        "max_payload_kg": 4.0,
        "max_range_km": 15.0,
        "max_speed_kmh": 150.0,
        "swarm_count": 10,
        "swarm_size": 1000,
    },
    "altius_600m": {
        "count": 0,
        "max_payload_kg": 12.0,
        "max_range_km": 440.0,
        "max_speed_kmh": 180.0,
        "swarm_count": 5,
        "swarm_size": 200,
    },
    "enemy": {
        "long_range_drones": {"count": 0, "max_payload_kg": 50.0, "max_range_km": 400.0, "max_speed_kmh": 150.0},
        "fpv_drones":        {"count": 0, "max_payload_kg": 4.0,  "max_range_km": 15.0,  "max_speed_kmh": 150.0},
        "tanks":             {"count": 0, "speed_kmh": 10.0},
        "ships":             {"count": 0, "speed_knots": 22.0},
        "missile_launchers": {"count": 0, "location": "fujian"},
        "soldiers":          {"count": 0, "speed_kmh": 5.0},
        "distribution":      {"west_coast_pct": 0.9, "east_coast_pct": 0.1},
    },
    "deployment": {
        "taipei_pct": 0.6,
    },
}

CONFIG_PATH: str = os.environ.get("ASSETS_CONFIG", "assets_config.json")


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return _deep_merge(_DEFAULTS, json.load(f))
    except FileNotFoundError:
        return _DEFAULTS.copy()


assets_config: dict = _load()
