"""Real coastline polygon land/sea determination (Feature 27).

Loads theater_land.json on import and exposes is_land(lat, lon) for use by the
movement simulator and config loader.  Uses ray-casting with hole support so
lakes inside land polygons are correctly treated as water.
"""
from __future__ import annotations
import json
import os

# Path from backend/services/ up two levels to the project root, then into the
# frontend's public data directory where the GeoJSON is served.
_THEATER_LAND_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "../../frontend/public/data/theater_land.json")
)


def _load_theater_polygons() -> list:
    try:
        with open(_THEATER_LAND_PATH, encoding="utf-8") as f:
            data = json.load(f)
        polygons = data.get("polygons", [])
        print(f"[terrain] Loaded {len(polygons)} polygon(s) from theater_land.json")
        return polygons
    except FileNotFoundError:
        print(f"[terrain] WARNING: {_THEATER_LAND_PATH} not found — terrain checks disabled")
        return []
    except Exception as exc:
        print(f"[terrain] WARNING: Failed to load theater polygons: {exc}")
        return []


_THEATER_POLYGONS: list = _load_theater_polygons()

# Pre-compute outer-ring bounding boxes so we can skip polygons quickly.
def _ring_bbox(ring: list) -> tuple[float, float, float, float]:
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return min(lons), min(lats), max(lons), max(lats)

_POLYGON_BBOXES: list[tuple[float, float, float, float]] = [
    _ring_bbox(rings[0]) for rings in _THEATER_POLYGONS
]

# Cache at 1/200 degree (~555 m) precision — same as the frontend isLand().
_LAND_CACHE: dict[tuple[float, float], bool] = {}


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray-casting point-in-polygon test for a single coordinate ring."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def is_land(lat: float, lon: float) -> bool:
    """Return True if (lat, lon) is over land (Feature 27).

    Uses real GeoJSON coastline polygons with ray-casting + hole support
    covering Taiwan, China, North Korea, South Korea, Japan, and Philippines.
    Returns False when polygon data is unavailable (fail-safe / treat as sea).
    """
    if not _THEATER_POLYGONS:
        return False

    key = (round(lat * 200) / 200.0, round(lon * 200) / 200.0)
    cached = _LAND_CACHE.get(key)
    if cached is not None:
        return cached

    result = False
    for i, rings in enumerate(_THEATER_POLYGONS):
        bbox = _POLYGON_BBOXES[i]
        if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            continue
        if _point_in_ring(lon, lat, rings[0]):
            # A point inside a hole (inner ring) is NOT land.
            in_hole = any(_point_in_ring(lon, lat, rings[h]) for h in range(1, len(rings)))
            if not in_hole:
                result = True
                break

    _LAND_CACHE[key] = result
    return result
