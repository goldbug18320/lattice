#!/usr/bin/env python3
"""
Build frontend/public/data/theater_land.json for the Lattice terrain constraint check.

Downloads Natural Earth 1:10m land polygons from GitHub, clips them to the
Taiwan / China strait theater bounding box, rounds coordinates to 4 decimal
places (~11 m precision at Taiwan latitude), and writes the result as a compact
JSON file consumed by Map3D's isLand() function.

Usage:
    python scripts/build_coastline.py

Requirements: Python 3.6+ standard library only (no external packages needed).
"""

import json
import os
import sys
import urllib.request

# Natural Earth 1:10m physical land (includes all islands)
SRC_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector"
    "/master/geojson/ne_10m_land.geojson"
)

# Taiwan / China strait theater bounding box  [minLon, minLat, maxLon, maxLat]
THEATER_BBOX = (115.0, 19.0, 126.0, 27.5)

# Coordinate decimal places to keep (4 dp ≈ 11 m at Taiwan latitude)
PRECISION = 4

OUT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../frontend/public/data/theater_land.json",
)


# ── helpers ──────────────────────────────────────────────────────────────────

def ring_bbox(ring):
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return min(lons), min(lats), max(lons), max(lats)


def bboxes_overlap(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def round_rings(rings):
    return [
        [[round(c[0], PRECISION), round(c[1], PRECISION)] for c in ring]
        for ring in rings
    ]


def extract_polygons(geojson, bbox):
    """Return list of polygon ring-groups that overlap *bbox*."""
    out = []
    for feature in geojson["features"]:
        geom = feature["geometry"]
        if geom["type"] == "Polygon":
            candidates = [geom["coordinates"]]
        elif geom["type"] == "MultiPolygon":
            candidates = geom["coordinates"]
        else:
            continue

        for rings in candidates:
            if bboxes_overlap(ring_bbox(rings[0]), bbox):
                out.append(round_rings(rings))
    return out


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    print(f"Downloading Natural Earth 1:10m land from GitHub …")
    print(f"  {SRC_URL}")
    try:
        req = urllib.request.Request(SRC_URL, headers={"User-Agent": "lattice-build"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except Exception as exc:
        sys.exit(f"Download failed: {exc}")

    print(f"Parsing {len(raw) / 1e6:.1f} MB …")
    geojson = json.loads(raw)
    print(f"  {len(geojson['features'])} features in source")

    polygons = extract_polygons(geojson, THEATER_BBOX)
    print(f"Extracted {len(polygons)} polygon(s) intersecting theater bbox "
          f"{THEATER_BBOX}")

    payload = json.dumps({"polygons": polygons}, separators=(",", ":"))
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(payload)

    size_kb = len(payload) / 1024
    print(f"Written {size_kb:.1f} KB -> {OUT_PATH}")
    print("Done. Restart the Vite dev server to serve the new file.")


if __name__ == "__main__":
    main()
