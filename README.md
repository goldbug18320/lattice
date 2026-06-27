# Lattice — AI-Enabled Drone Swarm C2 Platform

A war game simulator for coordinating reconnaissance and combat drone swarms over Taiwan. Operators issue natural language commands; an LLM translates intent into tactical missions, selects the right drone type and swarm size, and enforces human-in-the-loop approval before any attack executes.

---

## Features

- **3D map** — CesiumJS with real-world Taiwan terrain; friendly assets in blue/green, enemy in red
- **Natural language commands** — single text interface for both tactical orders and map navigation
- **LLM drone selection** — automatically picks FPV vs. Altius-600M based on target type, payload, and range
- **Human-in-the-loop (HITL)** — attack commands queue a pending approval; operator must confirm before any swarm fires
- **Target threat classification** — ships/missile launchers = high, tanks/long-range drones = medium, FPVs/soldiers = low
- **Live simulation** — 1 Hz movement ticker advances all drones and enemy assets; WebSocket pushes updates to UI
- **Drag-and-drop asset deployment** — drag any entity on the map to reposition it; drop new assets from the Asset Palette to deploy them; right-click to remove; all changes persist to `assets_config.json`
- **Detected contacts per drone** — clicking a recon drone shows exactly which enemy assets it is currently tracking
- **Configurable scenario** — all asset counts and properties live in `assets_config.json`; no code changes required

---

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # add OPENAI_API_KEY (optional — mock fallback works without it)
uvicorn main:app --reload --port 8000
```

Swagger docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

The Vite dev server proxies `/api/*` and `/ws` to `localhost:8000`.

### Stopping the servers

Press `Ctrl+C` in the terminal where each server is running.

---

## Environment Variables

| Variable | Default | Required |
|---|---|---|
| `OPENAI_API_KEY` | — | No (mock fallback used when absent) |
| `OPENAI_MODEL` | `gpt-4o` | No |
| `ASSETS_CONFIG` | `assets_config.json` | No |

Without an API key the platform uses a keyword-based mock parser. All features including HITL approval and status queries work in mock mode.

---

## Scenario (Default)

### Friendly Assets

| Asset | Count | Notes |
|---|---|---|
| MQ-9 Recon | 4 | 15 km detection radius; 30+ hour endurance; 2 always airborne |
| Scout Recon | 100 | 10 km detection radius; 150 km range |
| FPV Combat | 10,000 | 4 kg payload, 15 km range; 10 swarms of 1,000 |
| Altius-600M | 1,000 | 12 kg payload, 440 km range; 5 swarms of 200 |

60% of assets are based in the Taipei area; 40% across Taichung, Tainan, Kaohsiung, Hualien.

### Enemy Assets

| Asset | Count | Location |
|---|---|---|
| Long-range attack drones | 10,000 | Launched from mainland China |
| FPV drones | 10,000 | Deployed in Taiwan |
| Tanks | 100 | West coast Taiwan |
| Ships | 1,000 | Taiwan Strait |
| Missile launchers | 400 | Fujian |
| Soldiers | 100,000 | Landed in Taiwan |

90% of enemy assets are on the west coast; 10% east coast.

---

## Configuring the Scenario

Edit `backend/assets_config.json` and restart the backend. No code changes needed.

```json
{
  "mq9": { "count": 4, "detection_radius_km": 15.0, "max_flight_time_hours": 30.0 },
  "fpv_combat": { "count": 10000, "swarm_count": 10, "swarm_size": 1000 },
  "enemy": { "ships": { "count": 1000, "speed_knots": 22.0 } },
  "deployment": { "taipei_pct": 0.6 }
}
```

The file is rewritten automatically whenever assets are moved, added, or removed via the map UI. To save a scenario checkpoint manually, call `POST /api/assets/save-config`.

---

## API Overview

| Group | Base Path | Description |
|---|---|---|
| Recon | `/api/recon` | Submit recon feeds; query/filter enemy targets |
| Swarm Control | `/api/swarm` | Manage drones, swarms, telemetry, commands |
| NLP | `/api/nlp` | Natural language commands, HITL approvals |
| Asset Management | `/api/assets` | Create/delete assets, persist scenario to config |
| State | `/api/state` | Full battlefield snapshot |
| WebSocket | `/ws` | 1-second state broadcast |

Notable endpoints:
- `GET /api/recon/targets?reported_by=MQ9-01` — targets detected by a specific recon drone
- `POST /api/nlp/command` — accepts free-text; returns action + execution result
- `POST /api/nlp/approve/{id}` / `deny/{id}` — HITL approval flow
- `POST /api/assets/drone` / `POST /api/assets/target` — spawn a new asset at a given position
- `POST /api/assets/save-config` — flush current positions to `assets_config.json`

---

## Running Tests

```bash
cd backend
pytest tests/ -q
```

324 tests covering state service, movement simulation, all API routes, and LLM mock responses.

---

## Architecture

```
React UI (CesiumJS 3D map)
    ↕ WebSocket (1 s broadcast)   ↕ REST
FastAPI Backend
    ├── State Service (in-memory)
    ├── Movement Simulator (1 Hz asyncio task)
    ├── LLM Service (OpenAI GPT-4o / mock fallback)
    └── Swarm Service (command execution)
```

See [SPEC.md](SPEC.md) for the full technical specification.
