# Lattice C2 — Technical Documentation

A war game simulator modelling a Taiwan Strait scenario. A FastAPI backend maintains a live battlefield state — friendly drone swarms, reconnaissance drones, and enemy assets — and exposes it over WebSocket to a React frontend. An operator issues natural-language commands that an LLM translates into structured swarm actions, subject to a mandatory human-in-the-loop (HITL) approval gate before any attack executes.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Configuration](#configuration)
4. [Drone Fleet](#drone-fleet)
5. [Enemy Assets](#enemy-assets)
6. [Data Models](#data-models)
7. [State Management](#state-management)
8. [Movement Simulation](#movement-simulation)
9. [LLM Command System](#llm-command-system)
   - [How the LLM Selects a Combat Swarm](#how-the-llm-selects-a-combat-swarm)
   - [HITL Approval Gate](#hitl-approval-gate)
   - [Mock Fallback](#mock-fallback)
10. [API Reference](#api-reference)
11. [WebSocket Real-Time Feed](#websocket-real-time-feed)
12. [Terrain Constraints](#terrain-constraints)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│               React Frontend (CesiumJS)                 │
│   3D Map · Swarm Panel · NLP Console · Approval Panel   │
└────────────────────────┬────────────────────────────────┘
                         │  WebSocket /ws  (1 Hz state push)
                         │  REST  /api/*
┌────────────────────────▼────────────────────────────────┐
│                    FastAPI Backend                      │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  /api/nlp    │  │  /api/swarm  │  │  /api/recon  │  │
│  │  LLM + HITL  │  │  Commands    │  │  Target Feed │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │          │
│  ┌──────▼─────────────────▼──────────────────▼───────┐  │
│  │             StateService  (in-memory)              │  │
│  │   drones · swarms · targets · approvals · log      │  │
│  └──────────────────────┬─────────────────────────────┘  │
│                         │ 1 Hz tick                       │
│  ┌──────────────────────▼─────────────────────────────┐  │
│  │      MovementService  ·  TerrainService             │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │  OpenAI API (gpt-4o, optional)
```

The backend runs a 1-second tick loop (`main.py:broadcast_loop`) that advances all drone and enemy positions, checks combat contacts, runs ISR detection, and pushes a full state snapshot to every connected WebSocket client.

---

## Project Structure

```
lattice/
├── backend/
│   ├── main.py                   # FastAPI app, WebSocket manager, tick loop
│   ├── assets_config.json        # Scenario configuration and persisted initial state
│   ├── models/
│   │   ├── drone.py              # Drone, Swarm, SwarmCommand, DroneCommand, enums
│   │   └── target.py             # Target, PendingApproval, Position, enums
│   ├── services/
│   │   ├── state_service.py      # In-memory state store, seeding, persistence
│   │   ├── llm_service.py        # LLM command processor (OpenAI + mock fallback)
│   │   ├── swarm_service.py      # Swarm and drone command execution
│   │   ├── movement_service.py   # 1 Hz position simulation, ISR detection, combat
│   │   ├── terrain_service.py    # GeoJSON coastline polygon queries
│   │   └── config_service.py     # Loads and deep-merges assets_config.json
│   ├── api/
│   │   ├── nlp.py                # POST /api/nlp/command, approve, deny
│   │   ├── swarm.py              # Drone/swarm CRUD and command endpoints
│   │   ├── recon.py              # Recon feed submission and target queries
│   │   └── assets.py             # Create/delete assets, save-config
│   └── tests/                    # 324 tests covering all services and endpoints
└── frontend/
    └── src/
        └── services/
            └── websocket.js      # WebSocket connect/reconnect/dispatch
```

---

## Configuration

`backend/assets_config.json` is the single source of truth for fleet sizes, performance parameters, and the persisted battlefield snapshot. Values are loaded once on server start via `config_service.py` and deep-merged over zero-count safe defaults.

### Fleet Parameters

| Key | Description |
|-----|-------------|
| `mq9.count` | Number of MQ-9 recon drones to seed |
| `mq9.always_airborne` | Minimum MQ-9s that must be patrolling; standby units auto-launch each tick |
| `mq9.detection_radius_km` | Radius within which a patrolling MQ-9 detects enemy targets |
| `mq9.max_range_km` | Max operational range (km) |
| `mq9.max_flight_time_hours` | Endurance |
| `scout_recon.count` | Number of scout recon drones |
| `scout_recon.detection_radius_km` | Scout ISR detection radius |
| `fpv_combat.swarm_count` | Number of FPV combat swarms |
| `fpv_combat.swarm_size` | Simulated total fleet size per FPV swarm |
| `fpv_combat.max_range_km` | FPV combat range (km) |
| `fpv_combat.max_payload_kg` | FPV payload capacity |
| `altius_600m.swarm_count` | Number of Altius-600M swarms |
| `altius_600m.swarm_size` | Simulated total fleet size per Altius swarm |
| `altius_600m.max_range_km` | Altius operational range (km) |
| `altius_600m.max_payload_kg` | Altius payload capacity |
| `deployment.taipei_pct` | Fraction of FPV swarms based in the Taipei area (default 0.6) |
| `combat.contact_radius_m` | Engagement contact radius in metres (default 500 m) |

### Persisted State

When assets are moved on the map or `POST /api/assets/save-config` is called, the current drone positions, swarm definitions, and target list are written back into `assets_config.initial_state`. On next server start, `StateService._load_from_initial_state()` restores exactly that snapshot instead of re-seeding from counts.

---

## Drone Fleet

### MQ-9 Recon (`mq9_recon`)

- **Role**: Long-endurance ISR — Intelligence, Surveillance, Reconnaissance
- **Max range**: 1,900 km · **Endurance**: 30+ hours · **Payload**: 1.7 kg
- **Detection radius**: 15 km (configurable)
- **Orbit behaviour**: Clockwise circular orbit around home position while patrolling. Each tick the heading is set perpendicular to the inward radial, which keeps the orbit radius constant.
- **Auto-launch**: If fewer than `always_airborne` MQ-9s are airborne, the next idle unit launches automatically on the next tick.
- **Not assignable to attack missions.** The system prompt and mock logic both enforce this hard constraint.

### Scout Recon (`scout_recon`)

- **Role**: Tactical ISR, closer-range persistent surveillance
- **Max range**: 150 km · **Max speed**: 150 km/h
- **Detection radius**: 10 km (configurable)
- **Behaviour**: Slow heading rotation (+2°/tick) for area patrol.
- **Tracking**: Can be tasked to follow a specific target via the HITL track flow (Feature 24). Holds at 10 km standoff from the target (Feature 28).
- **Not assignable to attack missions.**

### FPV Combat Swarms (`fpv_combat`)

- **Role**: Lethal kamikaze strike against light/close-range targets
- **Max range**: 15 km · **Payload**: 4 kg · **Simulated fleet size**: up to 1,000 per swarm
- **Named**: FPV-Alpha through FPV-Juliet (10 swarms)
- **Home bases**: 60% Taipei area, 40% other Taiwan cities (Taichung, Tainan, Kaohsiung, Hualien, Taoyuan, Keelung)
- **One-way strike**: Drones go `offline` after expending their range while `engaging` — no return flight.

### Altius-600M Combat Swarms (`altius_600m`)

- **Role**: Heavy strike against armoured, naval, and mainland targets
- **Max range**: 440 km · **Payload**: 12 kg · **Endurance**: 4 hours · **Simulated fleet size**: up to 200 per swarm
- **Named**: ALT-Alpha through ALT-Echo (5 swarms)
- **Home bases**: Taipei, Taichung, Tainan, Kaohsiung, Hsinchu
- **Required for**: tanks, ships, missile launchers, long-range drones, and any target in Fujian / mainland China (range constraint).

### Drone Statuses

| Status | Meaning |
|--------|---------|
| `idle` | On the ground, awaiting orders |
| `patrolling` | Airborne, executing orbit or area patrol |
| `searching` | Moving toward an area of interest |
| `tracking` | Following a specific target (recon drone) |
| `engaging` | Flying toward a target for strike |
| `returning` | Heading back to home position |
| `offline` | Expended (FPV one-way strike) or destroyed |

---

## Enemy Assets

Seeded from `assets_config.enemy` and `StateService._enemy_seed` in `state_service.py`:

| Type | Seeded count | Speed | Threat value |
|------|-------------|-------|--------------|
| `ship` | 5 | 22 knots heading east | **high** |
| `tank` | 4 | 10 km/h heading inland | **medium** |
| `missile_launcher` | 3 | stationary (Fujian) | **high** |
| `drone` (long-range, alt > 500 m) | 4 | 150 km/h heading east | **medium** |
| `drone` (FPV, alt ≤ 500 m) | 3 | 150 km/h, heading rotates | **low** |
| `soldier_unit` | 4 | 5 km/h heading inland | **low** |

Enemy targets move every simulation tick. Ground assets (tanks, soldiers, missile launchers) halt if their next position would be over water. Ships halt if over land (terrain constraint, Feature 21).

### Target Statuses

| Status | Meaning |
|--------|---------|
| `active` | Detected and unengaged |
| `tracked` | A recon drone is following this target |
| `engaged` | A combat swarm has been assigned to it |
| `destroyed` | Combat contact made; removed from play |
| `lost` | Confidence dropped below usable threshold |

---

## Data Models

### `Drone` (`models/drone.py`)

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Auto-generated |
| `name` | str | Human-readable identifier (e.g. `ALT-Alpha-001`) |
| `type` | `DroneType` | `recon`, `combat`, `swarm_member` |
| `model` | `DroneModel` | `mq9_recon`, `scout_recon`, `fpv_combat`, `altius_600m` |
| `position` | `Position` | Current lat/lon/alt |
| `home_position` | `Position` | Launch/base position used for return navigation |
| `heading` | float | Degrees 0–360 |
| `speed` | float | m/s |
| `status` | `DroneStatus` | See statuses above |
| `battery` | float | 0–100; drains 0.002% per tick |
| `max_range_km` | float | Hard range limit |
| `range_used_km` | float | Distance flown since launch |
| `swarm_id` | UUID | Parent swarm; null for standalone recon drones |
| `tracking_target_id` | UUID | Set on recon drones during HITL track missions (Feature 24) |

### `Swarm` (`models/drone.py`)

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Auto-generated |
| `name` | str | E.g. `ALT-Alpha`, `FPV-Bravo` |
| `drone_model` | `DroneModel` | Model shared by all members |
| `drone_ids` | list[UUID] | IDs of representative member drones |
| `total_drone_count` | int | Full simulated fleet size (may exceed `len(drone_ids)`) |
| `status` | `SwarmStatus` | `idle`, `searching`, `tracking`, `engaging`, `returning` |
| `objective` | str | Current mission description |
| `target_ids` | list[UUID] | Targets currently assigned to this swarm |

### `Target` (`models/target.py`)

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Auto-generated |
| `type` | `TargetType` | `drone`, `ship`, `tank`, `missile_launcher`, `soldier_unit` |
| `position` | `Position` | Current lat/lon/alt |
| `heading` | float | Movement direction in degrees |
| `speed` | float | m/s |
| `confidence` | float | 0–1; increases as recon drones observe |
| `status` | `TargetStatus` | See statuses above |
| `threat_value` | `ThreatValue` | `high`, `medium`, `low` |
| `reported_by` | str | Name of the recon drone that last observed this target |

### `PendingApproval` (`models/target.py`)

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Auto-generated |
| `command` | str | Original natural language command |
| `interpretation` | str | LLM plain-English interpretation |
| `approval_prompt` | str | LLM-generated summary presented to the operator |
| `threat_summary` | dict | `{"high": N, "medium": N, "low": N}` |
| `classified_targets` | list | Each entry: `{target_id, type, threat_value, position}` |
| `proposed_action` | dict | The `assign_swarm` or `assign_drone` to execute on approval |
| `status` | str | `pending`, `approved`, `denied`, `expired` |
| `expires_at` | datetime | Auto-expires 5 minutes after creation |

---

## State Management

`StateService` (`services/state_service.py`) holds all in-memory state in four dictionaries protected by a single `threading.Lock`:

- `_targets` — all known enemy targets
- `_drones` — all friendly drones
- `_swarms` — all swarm groupings
- `_approvals` — pending/decided HITL approvals

`get_full_state()` serialises everything into one JSON snapshot broadcast over WebSocket every second. The command log retains the last 200 entries.

---

## Movement Simulation

`MovementService.tick()` (`services/movement_service.py`) is called once per second by `main.py:broadcast_loop` and executes five sub-steps in order.

### 1. Friendly drone movement (`_tick_friendly_drones`)

Each non-idle drone advances using a flat-earth position update:

```
delta_lat = speed_ms × dt × cos(heading_rad) / 111,320
delta_lon = speed_ms × dt × sin(heading_rad) / (111,320 × cos(lat_rad))
```

Heading logic per status:

| Status | Heading logic |
|--------|--------------|
| `returning` | Bearing toward `home_position`; transitions to `idle` on arrival (≤ 500 m) |
| `patrolling` (MQ-9) | Perpendicular to inward radial → stable clockwise circular orbit |
| `patrolling` (Scout) | +2°/tick slow rotation |
| `searching` | Fixed heading; switches to `patrolling` once inside the area of interest |
| `engaging` / `tracking` (swarm) | Live bearing recalculated toward swarm's first `target_id` each tick |
| `tracking` (standalone recon) | Live bearing toward `tracking_target_id`; holds position at 10 km standoff (Feature 28) |

Speed is modulated by a per-status multiplier: `engaging`/`returning` = 1.0×, `tracking` = 0.8×, `searching` = 0.5×.

Range budget: when `range_used_km ≥ max_range_km`, FPV drones in `engaging` go `offline` (one-way strike); all other models transition to `returning`.

Battery drains 0.002% per tick regardless of motion.

### 2. Enemy asset movement (`_tick_enemy_assets`)

All `active`, `tracked`, and `engaged` targets with `speed > 0` advance along their heading each tick. Movement is blocked at terrain boundaries (Feature 21). Enemy FPV drones at ≤ 500 m altitude rotate heading +3°/tick for a patrol pattern.

### 3. Combat contact detection (`_check_combat_contacts`, Feature 23)

For every `ENGAGING` swarm, if any member drone is within `contact_radius_m` (default 500 m) of the swarm's primary target:

- The target is marked `destroyed`
- Every drone in the swarm is set `offline` (kamikaze strike — entire swarm is expended)
- The swarm returns to `idle` with its target list cleared
- Any recon drone tracking the destroyed target is released back to patrolling (Feature 26)

### 4. ISR detection

Each patrolling recon drone increments `confidence` for every target within its detection radius:

- MQ-9: +0.05 per tick within 15 km
- Scout: +0.03 per tick within 10 km

`reported_by` and `last_seen` are updated on each detection event.

### 5. MQ-9 auto-launch (`_maybe_launch_standby_mq9`)

If fewer than `always_airborne` MQ-9s are airborne (patrolling or returning), the next idle MQ-9 transitions to `patrolling`. This maintains persistent ISR coverage.

---

## LLM Command System

The operator sends free-text to `POST /api/nlp/command`. The backend builds a live battlefield context and calls `LLMService.process_command()` (`services/llm_service.py`), which uses **OpenAI GPT-4o** or falls back to a pure-Python mock when no API key is present.

### System Prompt

`LLMService` uses a detailed system prompt (`llm_service.py:SYSTEM_PROMPT`) that defines:

- The four drone models and their capabilities and hard constraints
- The target threat classification table
- All available action types with exact required JSON schemas
- Hard rules: attack commands must always route through `request_approval`; recon drones must never be assigned to attacks
- Priority conventions: attack = 8–10, patrol/search = 3–6, track = 6

The LLM is required to respond with a JSON object containing three fields: `interpretation` (plain English), `action` (structured), and `explanation`.

### Battlefield Context

Every call to the LLM includes a live snapshot of all swarms (with `representative_position` and `max_range_km`), all drones, and all targets. The `representative_position` of each swarm is computed in `nlp.py:_swarm_representative_position` as the centroid (average lat/lon) of its current member drones. This is the position the LLM and mock fallback use to check whether a swarm can reach a target.

---

### How the LLM Selects a Combat Swarm

When the operator issues an attack or engage command, the LLM follows a deterministic three-step process. The Python mock fallback in `LLMService._mock_response()` (`llm_service.py:131`) replicates this exact logic.

#### Step 1 — Target classification

Each target in scope is assigned a threat value based on type and altitude:

| Target type | Condition | Threat value |
|-------------|-----------|--------------|
| `ship` | any | **high** |
| `missile_launcher` | any | **high** |
| `tank` | any | **medium** |
| `drone` | altitude > 500 m | **medium** |
| `drone` | altitude ≤ 500 m | **low** |
| `soldier_unit` | any | **low** |

For a broad attack command (no specific target ID), up to six `active` targets are classified. For a single-target engage command (Feature 22 — command contains `target with id <uuid>`), only that one target is classified.

#### Step 2 — Drone model selection (payload match)

The LLM determines which drone model is appropriate based on the heaviest target in scope:

```
if any target type is: tank, ship, missile_launcher, or drone (long-range)
    → select altius_600m  (12 kg payload, 440 km range)
else
    → select fpv_combat   (4 kg payload, 15 km range)
```

This prevents light FPV drones from being assigned to armoured or naval targets (insufficient payload), and avoids wasting Altius munitions on targets FPVs can engage at close range. The rule is hardcoded in both the system prompt and the mock (`llm_service.py:171-174`).

#### Step 3 — Range-aware swarm selection

The LLM filters all swarms whose name prefix matches the selected model (`ALT-*` for Altius, `FPV-*` for FPV) and applies two criteria:

1. **Status check**: swarms currently in `engaging` status are excluded
2. **Range feasibility**: flat-earth distance from the swarm's `representative_position` to the target must be ≤ the swarm's `max_range_km`

Distance is computed with a flat-earth approximation (`llm_service.py:195-203`):

```python
dlat = (target.lat - swarm.lat) * 111.32
dlon = (target.lon - swarm.lon) * 111.32 * cos(radians(swarm.lat))
dist_km = sqrt(dlat² + dlon²)

if dist_km <= swarm.max_range_km:
    swarm is a candidate
```

Among all candidates, the **closest swarm** is selected. Its name and distance are embedded in the `approval_prompt` so the operator can verify feasibility before approving.

If no swarm of the correct model can physically reach the target, the action type is set to `no_swarm_in_range` and no approval is created.

**Example decision trace — "engage the ship at 24.5°N, 119.5°E":**

```
Target: ship → threat: HIGH → model needed: altius_600m

Candidate ALT swarms (not engaging):
  ALT-Alpha  @ (25.04, 121.56) → dist ≈ 212 km  ≤ 440 km  ✓
  ALT-Bravo  @ (24.15, 120.68) → dist ≈ 114 km  ≤ 440 km  ✓  ← closest
  ALT-Charlie@ (23.00, 120.21) → dist ≈ 202 km  ≤ 440 km  ✓
  ALT-Delta  @ (22.63, 120.30) → dist ≈ 298 km  ≤ 440 km  ✓
  ALT-Echo   @ (24.80, 120.97) → dist ≈ 163 km  ≤ 440 km  ✓

Selected: ALT-Bravo (closest at 114 km)

Action returned:
  type: request_approval
  classified_targets: [{type: "ship", threat_value: "high", ...}]
  approval_prompt: "Requesting approval to engage 1 high-value ship using ALT-Bravo (114 km away)."
  proposed_action: {type: "assign_swarm", swarm_id: <ALT-Bravo id>, command_type: "attack", ...}
```

**Example — target out of FPV range:**

```
Target: soldier_unit at (24.0, 119.0) → model needed: fpv_combat (max 15 km)

FPV-Alpha  @ (25.04, 121.56) → dist ≈ 283 km  >  15 km  ✗
FPV-Bravo  @ (25.00, 121.47) → dist ≈ 278 km  >  15 km  ✗
... (all 10 FPV swarms exceed 15 km range)

Action returned: no_swarm_in_range
  explanation: "No FPV combat swarm can physically reach this target."
```

#### Special Cases

| Scenario | Trigger | Behaviour |
|----------|---------|-----------|
| **Single-target engage (Feature 22)** | Command contains `target with id <uuid>` | Only that target classified; closest in-range swarm named in approval prompt |
| **No swarm in range** | All matching-model swarms exceed `max_range_km` | Returns `no_swarm_in_range`; no approval created |
| **Track command (Feature 24)** | Command contains "track", "follow", or "monitor" | Routes through `request_approval` with an `assign_drone` proposed action; selects the nearest MQ-9 or Scout recon drone within range of the target |
| **No recon in range** | No recon drone can reach the target | Returns `no_recon_in_range` |
| **Non-attack commands** | "locate", "patrol", "return", "abort" | Bypasses approval gate entirely; executes `assign_swarm` directly |

---

### HITL Approval Gate

**No attack ever executes without explicit operator approval.**

When the LLM returns `request_approval`, `nlp.py` creates a `PendingApproval` with a 5-minute TTL and stores it in `StateService._approvals`. It is included in the next WebSocket broadcast, surfacing in the UI approval panel.

The operator has three options:

| Action | Endpoint | Effect |
|--------|----------|--------|
| **Approve** | `POST /api/nlp/approve/{id}` | Executes `proposed_action` via `SwarmService`; marks approval `approved` |
| **Deny** | `POST /api/nlp/deny/{id}` | Marks approval `denied`; no action taken |
| **Let expire** | automatic after 5 min | Marked `expired` by `state_service.expire_approvals()` on each tick |

On approval, `SwarmService.execute_swarm_command()` (`services/swarm_service.py`):

1. Sets the swarm status to `ENGAGING`
2. Sets every member drone status to `ENGAGING`
3. Records the target IDs on the swarm
4. Marks each target as `engaged`

From that point `MovementService` flies the drones toward the target on every tick until a combat contact is detected.

---

### Mock Fallback

When `OPENAI_API_KEY` is absent, `LLMService._mock_response()` (`llm_service.py:131`) runs the same selection logic in pure Python — same payload-match rule, same flat-earth range check, same HITL routing — without any external API call. All responses are prefixed with `[MOCK]` in the `interpretation` field. All features including HITL approval, tracking, and status queries work in mock mode.

---

## API Reference

### NLP Commands (`/api/nlp`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/nlp/command` | Submit a natural-language operator command |
| `GET` | `/api/nlp/pending` | List all pending HITL approval requests |
| `POST` | `/api/nlp/approve/{id}` | Approve a pending attack and execute it |
| `POST` | `/api/nlp/deny/{id}` | Deny a pending attack |

**Request body for `/command`:**
```json
{
  "command": "Attack the enemy ships in the strait",
  "context_override": null
}
```

**Response:**
```json
{
  "command": "Attack the enemy ships in the strait",
  "interpretation": "Attack command targeting 5 ships — routing through HITL approval",
  "explanation": "Attack classified and queued for operator approval.",
  "action": {
    "type": "request_approval",
    "classified_targets": [...],
    "threat_summary": {"high": 5, "medium": 0, "low": 0},
    "approval_prompt": "Requesting approval to attack 5 targets: 5 high-value ships.",
    "proposed_action": {"type": "assign_swarm", "swarm_id": "...", "command_type": "attack", ...}
  },
  "execution_result": {"approval_id": "<uuid>", "status": "pending"}
}
```

### Swarm Control (`/api/swarm`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/swarm/drones` | List all drones |
| `POST` | `/api/swarm/drones` | Register a drone |
| `GET` | `/api/swarm/drones/{id}` | Get drone details |
| `PATCH` | `/api/swarm/drones/{id}` | Update drone telemetry/status |
| `POST` | `/api/swarm/drones/{id}/command` | Issue command to a single drone |
| `GET` | `/api/swarm/swarms` | List all swarms with active drone counts |
| `POST` | `/api/swarm/swarms` | Create a new swarm |
| `GET` | `/api/swarm/swarms/{id}` | Get swarm details with member drones |
| `POST` | `/api/swarm/swarms/{id}/command` | Issue a mission command to a swarm |
| `GET` | `/api/swarm/log` | Get last 50 command log entries |
| `POST` | `/api/swarm/telemetry` | Batch live telemetry from one or more drones |

Command types: `locate`, `track`, `attack`, `patrol`, `return`, `abort`

### Reconnaissance (`/api/recon`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/recon/feed` | Submit target reports from a recon drone |
| `GET` | `/api/recon/targets` | List targets (filter by `type`, `status`, `min_confidence`, `reported_by`) |
| `GET` | `/api/recon/targets/{id}` | Get a specific target |
| `PATCH` | `/api/recon/targets/{id}` | Update target fields (position, status, confidence, etc.) |
| `PATCH` | `/api/recon/targets/{id}/status` | Update target status only |
| `DELETE` | `/api/recon/targets/{id}` | Remove a target |

Notable filter: `GET /api/recon/targets?reported_by=MQ9-01` returns only targets detected by that recon drone.

### Asset Management (`/api/assets`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/assets/drone` | Create a drone at a given position (auto-saves config) |
| `DELETE` | `/api/assets/drone/{id}` | Delete a drone (auto-saves config) |
| `POST` | `/api/assets/target` | Create an enemy target at a given position (auto-saves config) |
| `DELETE` | `/api/assets/target/{id}` | Delete a target (auto-saves config) |
| `POST` | `/api/assets/save-config` | Flush current positions to `assets_config.json` |

### Global State

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/state` | Full battlefield snapshot (same payload as WebSocket push) |

Interactive API docs available at `/docs` (Swagger UI) and `/redoc`.

---

## WebSocket Real-Time Feed

Connect to `ws://<host>/ws`.

On connect, the server immediately sends the full current state. Thereafter a new snapshot is pushed every second:

```json
{
  "targets": [...],
  "drones": [...],
  "swarms": [...],
  "pending_approvals": [...],
  "timestamp": "2026-06-29T10:00:00.000000"
}
```

The frontend (`frontend/src/services/websocket.js`) reconnects automatically after a 3-second delay on disconnect.

---

## Terrain Constraints

`TerrainService` loads real GeoJSON coastline polygons covering Taiwan, China, Japan, South Korea, North Korea, and the Philippines.

Rules enforced on every movement tick (Feature 21):

| Asset type | Constraint |
|------------|------------|
| `tank`, `missile_launcher`, `soldier_unit` | Must remain on land; movement halts at water boundary |
| `ship` | Must remain at sea; movement halts at coastline |
| `drone` | Unconstrained (air asset) |

Terrain is also validated when targets are created or loaded from config — a console warning is logged if a land-type target is placed in water or vice versa (Feature 27).
