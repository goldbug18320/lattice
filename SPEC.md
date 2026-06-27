# Lattice — AI-Enabled Drone Swarm Command & Control Platform
## Technical Specification v2.0

---

## 1. Overview

**Lattice** is an AI-enabled command and control (C2) platform built for a **war game simulator**. It coordinates reconnaissance and combat drone swarms over real-world terrain covering **Taiwan and surrounding waters**. The platform ingests live intelligence feeds from reconnaissance drones, visualizes the battlefield in 3D, and enables operators to issue tactical commands via natural language. An integrated LLM translates operator intent into structured mission objectives — selecting the appropriate drone type, payload, and swarm size based on the threat — and dispatches them to AI-enabled swarms, which self-coordinate to execute missions including in GPS-denied environments. The LLM also handles **UI control commands** (e.g., "show Taiwan on map", "zoom to Fujian") to give the operator a single, unified natural language interface for both combat operations and map navigation.

---

## 2. Goals & Non-Goals

### Goals
- Real-time ingestion of reconnaissance feeds (enemy positions, types, confidence)
- 3D terrain visualization of all friendly and enemy assets over real-world terrain (Taiwan and surrounding sea)
- Natural language operator interface powered by an LLM
- **LLM-driven drone selection**: LLM automatically selects drone type (FPV vs. Altius-600M) and swarm size based on target type, required payload, and range
- **LLM-driven UI control**: operator can navigate and control the 3D map view via natural language (e.g., "show Taiwan on map", "zoom to Fujian", "focus on target alpha")
- **LLM geographic deployment**: LLM understands region-based deployment commands (e.g., "deploy all assets to the west coast", "move recon drones to northern Taiwan") — resolves named regions to bounding boxes and fans out patrol commands to all matching swarms simultaneously
- **LLM-driven grid patrol assignment**: The patrol area covers the **coastal sea within 25 km of the Taiwan coastline** and **city areas** — mountain areas are explicitly excluded; this area is divided into **50×50 km grids** (100 grids total); exactly **20 scout recon drones are in flight at all times**, prioritising the highest-value grids (coastal sea first, then cities); **coastal sea grids take highest priority** and are covered first; if a drone returns, a replacement launches immediately from the nearest base (unless inventory is exhausted)
- **LLM target classification + human approval (HITL)**: LLM classifies every attack target by threat value (high / medium / low) and generates a pending approval request; the operator must explicitly approve before any attack is executed — no autonomous strikes without human confirmation
- **LLM natural language status responses (Feature 14)**: For status queries (e.g., "what is the status of MQ9-01?", "how many drones are engaging?"), the LLM produces a conversational natural language answer instead of a structured action — the platform returns the human-readable response directly in the command log
- **Engage → auto-select combat swarm (Feature 15)**: When the operator clicks the ENGAGE button on a target in the Target List panel, the assigned combat swarm is automatically selected and highlighted in the Swarm & Drone Status panel, and swarms are sorted by activity (engaging first) — giving immediate visual confirmation of which swarm was tasked
- **Hide idle drones from Swarm & Drone Status panel (Feature 16)**: Idle individual drones are suppressed to reduce clutter — swarm cards always show (so the operator can see all swarms), but the expanded drone list within a selected swarm only shows active (non-idle) drones with a summary count of idle ones; idle recon drones are also hidden from the RECONNAISSANCE section
- Swarm-level (not drone-level) task assignment to support autonomous AI swarm coordination
- **Drone movement simulation**: all deployed (non-idle) drones continuously update their position on the server at 1-second intervals; drones return when max range is consumed
- **Live friendly drone telemetry**: drones report position, battery, heading, and speed via a dedicated batch telemetry API endpoint; UI always reflects current positions
- REST APIs for drone integration (recon feeds, drone telemetry, command dispatch)
- WebSocket push for real-time UI updates

### Non-Goals
- Individual flight path planning per drone (handled by the on-drone AI)
- GPS-dependent navigation algorithms (platform is GPS-agnostic by design)
- Authentication/authorization (out of scope for v1)
- Physical drone hardware interface layer (platform is hardware-agnostic via API)

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          LATTICE PLATFORM                           │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────────────────────────────┐  │
│  │   React UI   │◄───│             FastAPI Backend              │  │
│  │  (CesiumJS   │    │                                          │  │
│  │   3D Map)    │    │  ┌─────────┐  ┌──────────┐  ┌────────┐ │  │
│  │              │    │  │  Recon  │  │  Swarm   │  │  NLP   │ │  │
│  │  Command     │    │  │   API   │  │  Control │  │  API   │ │  │
│  │  Panel (NLP) │    │  │         │  │   API    │  │(OpenAI)│ │  │
│  │              │    │  └────┬────┘  └────┬─────┘  └───┬────┘ │  │
│  │  Swarm       │    │       │             │             │      │  │
│  │  Status      │    │  ┌────▼─────────────▼─────────────▼────┐│  │
│  │              │    │  │           State Service              ││  │
│  │  Target List │    │  │     (in-memory battlefield state)    ││  │
│  └──────┬───────┘    │  │  + Movement Simulator (1 Hz tick)   ││  │
│         │ WebSocket  │  └──────────────────────────────────────┘│  │
│         └────────────►  /ws  (1-second broadcast loop)          │  │
│                      └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
         ▲                        ▲
         │ REST (telemetry)       │ REST (recon feeds)
    ┌────┴─────┐            ┌─────┴──────┐
    │  Combat  │            │   Recon    │
    │  Swarm   │            │   Drones   │
    │  Drones  │            │            │
    └──────────┘            └────────────┘
```

### Components
| Component | Technology | Responsibility |
|---|---|---|
| Backend API | Python, FastAPI | REST endpoints, WebSocket server, business logic |
| State Service | In-memory (Python dict) | Single source of truth for all battlefield state |
| **Movement Simulator** | Python (asyncio task) | Ticks at 1 Hz; advances all non-idle drone positions based on heading/speed/range budget |
| LLM Service | OpenAI GPT-4o | Natural language → structured command translation |
| Swarm Service | Python | Executes swarm commands, updates drone/swarm state |
| Frontend | React 18, Vite | Operator UI |
| 3D Map | CesiumJS | 3D terrain, entity visualization |
| State Management | Zustand | Client-side reactive state |
| Real-time | WebSocket | 1-second state broadcast from backend → UI |

---

## 4. Data Models

### 4.1 Target (Enemy Asset)

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique identifier |
| `type` | enum | `drone` \| `ship` \| `tank` \| `missile_launcher` \| `soldier_unit` |
| `threat_value` | enum | `high` \| `medium` \| `low` — LLM-assigned classification (see §6.8) |
| `position` | Position | `{lat, lon, alt}` in decimal degrees / meters |
| `heading` | float | 0–360 degrees |
| `speed` | float | Meters per second |
| `confidence` | float | 0.0–1.0 detection confidence |
| `status` | enum | `active` \| `tracked` \| `engaged` \| `destroyed` \| `lost` |
| `reported_by` | string | ID of the reporting recon drone |
| `first_seen` | datetime | UTC timestamp |
| `last_seen` | datetime | UTC timestamp (updated on each recon report) |
| `notes` | string? | Free-text intelligence notes |

### 4.2 Drone (Friendly Asset)

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique identifier |
| `name` | string | Human-readable name (e.g. `FPV-42`, `MQ9-02`, `SCOUT-01`) |
| `model` | enum | `mq9_recon` \| `scout_recon` \| `fpv_combat` \| `altius_600m` |
| `type` | enum | `recon` \| `combat` \| `swarm_member` (derived from model) |
| `position` | Position? | Last known position |
| `heading` | float | Current heading in degrees |
| `speed` | float | Current speed in m/s |
| `altitude` | float | Altitude in meters |
| `status` | enum | `idle` \| `patrolling` \| `searching` \| `tracking` \| `engaging` \| `returning` \| `offline` |
| `battery` | float | 0–100% charge level |
| `max_payload_kg` | float | Maximum payload in kilograms |
| `max_range_km` | float | Maximum operational range in kilometres |
| `max_flight_time_hours` | float? | Max endurance in hours (primarily for recon drones) |
| `range_used_km` | float | Distance travelled since launch (accumulates each movement tick) |
| `home_position` | Position | Base/launch position — drone returns here when `returning` |
| `current_task` | string? | Active mission objective description |
| `swarm_id` | UUID? | Parent swarm, if applicable |
| `last_update` | datetime | Last telemetry timestamp |

### 4.3 Swarm

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique identifier |
| `name` | string | Human-readable name (e.g. `Alpha Swarm`) |
| `drone_ids` | UUID[] | Member drone IDs |
| `status` | enum | `idle` \| `searching` \| `tracking` \| `engaging` \| `returning` |
| `objective` | string? | Current mission objective |
| `target_ids` | UUID[] | Enemy targets assigned to this swarm |
| `area_of_interest` | GeoJSON? | Patrol/search bounding box |
| `created_at` | datetime | |
| `last_command` | datetime? | Timestamp of last command issued |

### 4.4 SwarmCommand (API Input)

| Field | Type | Description |
|---|---|---|
| `command_type` | enum | `locate` \| `track` \| `attack` \| `patrol` \| `return` \| `abort` |
| `target_ids` | UUID[] | Enemy targets to engage (for `track`/`attack`) |
| `area_of_interest` | GeoJSON? | Search/patrol area (for `locate`/`patrol`) |
| `priority` | int | 1–10 mission priority |
| `objective` | string? | Human-readable objective string |
| `notes` | string? | Additional mission notes |

### 4.5 ReconFeed (API Input)

| Field | Type | Description |
|---|---|---|
| `recon_drone_id` | string | ID or name of the reporting drone |
| `timestamp` | datetime | Report generation time (UTC) |
| `targets` | TargetReport[] | List of observed targets |

**TargetReport** (item within ReconFeed):

| Field | Type | Description |
|---|---|---|
| `type` | TargetType | Enemy asset type |
| `position` | Position | Observed position |
| `heading` | float | Observed heading |
| `speed` | float | Observed speed |
| `confidence` | float | Detection confidence |
| `notes` | string? | Additional notes |
| `existing_target_id` | UUID? | If updating a known target, its ID |

---

## 5. API Specification

**Base URL:** `http://localhost:8000`  
**Format:** JSON  
**Docs:** `/docs` (Swagger UI auto-generated by FastAPI)

---

### 5.1 Reconnaissance API — `/api/recon`

#### `POST /api/recon/feed`
Submit a batch reconnaissance report from a recon drone.

**Request Body:** `ReconFeed`
```json
{
  "recon_drone_id": "R-01",
  "timestamp": "2024-01-01T12:00:00Z",
  "targets": [
    {
      "type": "tank",
      "position": { "lat": 25.041, "lon": 121.565, "alt": 0 },
      "heading": 270,
      "speed": 8.5,
      "confidence": 0.92
    }
  ]
}
```

**Response:**
```json
{ "received": 1, "created": 1, "updated": 0 }
```

---

#### `GET /api/recon/targets`
List all tracked enemy targets.

**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `type` | string? | Filter by target type |
| `status` | string? | Filter by status |
| `min_confidence` | float? | Minimum confidence threshold (default: 0.0) |

**Response:** `Target[]`

---

#### `GET /api/recon/targets/{target_id}`
Get a specific target by ID.

**Response:** `Target` or `404`

---

#### `PATCH /api/recon/targets/{target_id}/status`
Update a target's status (e.g., mark as destroyed).

**Query Parameter:** `status` (TargetStatus enum value)

**Response:** Updated `Target`

---

#### `DELETE /api/recon/targets/{target_id}`
Remove a target from the state.

**Response:** `{ "removed": "<target_id>" }`

---

### 5.2 Swarm Control API — `/api/swarm`

#### `GET /api/swarm/drones`
List all friendly drones with current telemetry.

**Response:** `Drone[]`

---

#### `POST /api/swarm/drones`
Register a new drone with the platform.

**Request Body:** `Drone`  
**Response:** Registered `Drone`

---

#### `GET /api/swarm/drones/{drone_id}`
Get a specific drone.

**Response:** `Drone` or `404`

---

#### `PATCH /api/swarm/drones/{drone_id}`
Update a drone's telemetry (position, status, battery, etc.).

**Request Body:** `DroneUpdate` (all fields optional)
```json
{
  "position": { "lat": 34.055, "lon": -118.245, "alt": 180 },
  "battery": 87.3,
  "status": "patrolling"
}
```

**Response:** Updated `Drone`

---

#### `POST /api/swarm/drones/{drone_id}/command`
Issue a mission command to a single drone.

**Request Body:** `DroneCommand`
```json
{
  "command_type": "track",
  "target_id": "<target_uuid>",
  "objective": "Track enemy tank until swarm arrives"
}
```

**Response:**
```json
{ "success": true, "drone_id": "...", "command_type": "track", "objective": "..." }
```

---

#### `GET /api/swarm/swarms`
List all swarms with drone counts and status.

**Response:** `Swarm[]` (enriched with `drone_count`, `active_drones`)

---

#### `POST /api/swarm/swarms`
Create a new swarm.

**Request Body:** `Swarm`  
**Response:** Created `Swarm`

---

#### `GET /api/swarm/swarms/{swarm_id}`
Get a swarm with full drone details.

**Response:** `Swarm` + `drones: Drone[]` or `404`

---

#### `POST /api/swarm/swarms/{swarm_id}/command`
**Primary combat endpoint.** Issue a high-level mission objective to a swarm. The AI-enabled swarm drones self-coordinate to execute it.

**Request Body:** `SwarmCommand`
```json
{
  "command_type": "attack",
  "target_ids": ["<target_uuid-1>", "<target_uuid-2>"],
  "priority": 9,
  "objective": "Neutralize enemy missile launcher cluster at grid 7G"
}
```

**Response:**
```json
{
  "success": true,
  "swarm_id": "...",
  "command_type": "attack",
  "drones_tasked": 5,
  "objective": "Neutralize enemy missile launcher cluster at grid 7G"
}
```

> **Design note:** The platform dispatches a single objective to the swarm — NOT individual waypoints. The on-drone AI coordinates internally, enabling resilience in GPS-denied environments.

---

#### `GET /api/swarm/log`
Retrieve the command execution log.

**Query Parameter:** `limit` (default: 50)  
**Response:** `CommandLogEntry[]`

---

#### `POST /api/swarm/telemetry`
**Batch live telemetry endpoint.** Deployed drones call this endpoint (or it is called on their behalf by the simulator) to report current position, battery, heading, and speed. Updates are applied to state immediately and broadcast in the next WebSocket tick.

**Request Body:**
```json
{
  "reports": [
    {
      "drone_id": "MQ9-01",
      "position": { "lat": 25.10, "lon": 121.60, "alt": 6000 },
      "heading": 90.0,
      "speed": 120.0,
      "battery": 92.5,
      "status": "patrolling"
    }
  ]
}
```

**Response:**
```json
{ "updated": 1, "not_found": [] }
```

> **Design note (Feature 11):** In simulation mode the backend movement simulator calls this internally. When integrated with real hardware, each physical drone POSTs its own telemetry report here at its configured reporting interval.

---

### 5.3 NLP Command API — `/api/nlp`

#### `POST /api/nlp/command`
Process a natural language operator command using the LLM.

**Request Body:**
```json
{ "command": "Send Alpha Swarm to destroy all enemy tanks in the northern sector" }
```

**Response:**
```json
{
  "command": "Send Alpha Swarm to destroy all enemy tanks in the northern sector",
  "interpretation": "Operator wants Alpha Swarm to attack all active tank targets",
  "explanation": "Assigned Alpha Swarm (attack) against 2 active tank targets with priority 9",
  "action": {
    "type": "assign_swarm",
    "swarm_id": "<alpha-swarm-uuid>",
    "command_type": "attack",
    "target_ids": ["<tank-1-uuid>", "<tank-2-uuid>"],
    "objective": "Destroy enemy tanks in northern sector",
    "priority": 9
  },
  "execution_result": {
    "success": true,
    "drones_tasked": 5
  }
}
```

---

#### `GET /api/nlp/history`
Retrieve NLP command history.

**Query Parameter:** `limit` (default: 50)  
**Response:** `NLPLogEntry[]`

---

### 5.4 Attack Approval API — `/api/nlp`

**(Feature 13 — Human-in-the-Loop)**

When the LLM determines that an operator command involves attacking enemy targets, it **does not execute immediately**. Instead it creates a **pending approval request** and waits for explicit operator confirmation.

#### `GET /api/nlp/pending`
List all pending attack approval requests awaiting operator decision.

**Response:** `ApprovalRequest[]`
```json
[{
  "id": "<uuid>",
  "command": "attack all ships in the strait",
  "interpretation": "Operator wants to attack 5 high-value ship targets",
  "proposed_action": { "type": "assign_swarm", "swarm_id": "...", "command_type": "attack", ... },
  "targets": [
    { "id": "...", "type": "ship", "threat_value": "high", "position": {...}, "confidence": 0.92 }
  ],
  "threat_summary": { "high": 5, "medium": 0, "low": 0 },
  "created_at": "2024-01-01T12:00:00Z",
  "expires_at": "2024-01-01T12:05:00Z"
}]
```

---

#### `POST /api/nlp/approve/{approval_id}`
Approve a pending attack request. The platform executes the proposed swarm command immediately.

**Response:**
```json
{ "approved": true, "approval_id": "...", "execution_result": { "success": true, "drones_tasked": 50 } }
```

---

#### `POST /api/nlp/deny/{approval_id}`
Deny a pending attack request. The proposed action is discarded.

**Response:**
```json
{ "denied": true, "approval_id": "..." }
```

---

### 5.5 System API

#### `GET /`
Platform health check and version info.

#### `GET /api/state`
Full battlefield state snapshot (targets, drones, swarms, **pending approvals**).

#### `WebSocket /ws`
Real-time battlefield state broadcast. Pushes the full state JSON every 1 second to all connected clients. **Includes `pending_approvals` array** so the UI can show approval notifications in real time.

**Message format:**
```json
{
  "drones": [...],
  "targets": [...],
  "swarms": [...],
  "pending_approvals": [...],
  "timestamp": "2024-01-01T12:00:00.123456"
}
```

---

## 6. LLM Integration

### 6.1 Role
The LLM acts as a **unified tactical and UI intent translator**. It receives:
- The operator's natural language command
- A snapshot of the current battlefield state (swarms, drones by model, targets with threat classification)
- Current camera/view context (current map center, zoom level)

And returns a structured JSON action that covers five categories:
1. **Tactical commands** — which drone model to use, how large a swarm, and what mission to execute
2. **UI commands** — camera navigation, map focus, and filter/display changes on the 3D map
3. **Geographic deployment commands** — mass redeployment of all or filtered assets to a named region
4. **Attack approval requests (HITL)** — classifies targets by threat value and holds the proposed attack for operator confirmation before any execution
5. **Natural language status responses** — answers status queries in plain English (e.g., drone battery, swarm status, enemy counts) without issuing any command

### 6.2 Drone Selection Rules (LLM Guidance)
The LLM system prompt instructs the model to apply these rules before assigning assets:

1. **Payload match**: FPV drones (4 kg) for light targets (enemy FPVs, soldiers); Altius-600M (12 kg) for heavy targets (tanks, ships, missile launchers, long-range drones).
2. **Range check**: FPV max 15 km — only assign to targets within range. Altius-600M max 440 km — suitable for mainland targets (e.g., Fujian missile launchers).
3. **Swarm size**: Scale swarm size to threat — small swarms (10–20) for single vehicles, large swarms (50–200) for formations or high-value targets.
4. **Inventory awareness**: LLM is given current available drone counts per model and selects realistically.

### 6.3 Model
- Default: `gpt-4o` (configurable via `OPENAI_MODEL` env var)
- Output mode: JSON object (`response_format: { type: "json_object" }`)
- Temperature: `0.2` (low, for deterministic tactical reasoning)

### 6.4 Action Types
| Action | Category | Description |
|---|---|---|
| `assign_swarm` | Tactical | Issue a SwarmCommand to a named swarm (LLM selects model and size) |
| `assign_drone` | Tactical | Issue a DroneCommand to a single drone |
| `mark_target_destroyed` | Tactical | Update target status to `destroyed` |
| `request_approval` | **HITL** | Attack involves classified targets — LLM returns proposed action + threat summary; platform stores as pending approval and waits for operator confirmation before executing |
| `deploy_to_region` | Deployment | Redeploy all (or filtered) swarms to patrol a named geographic region; fans out patrol commands to all matching swarms simultaneously |
| `request_status` | **Info / NL** | No API action; LLM provides a **natural language** status answer (e.g., "MQ9-01 is patrolling at 6,000m altitude, battery 87%, covering the Taipei area") — displayed directly in the command log without executing any command |
| `ui_command` | UI | Pan, zoom, or recenter the 3D map camera; toggle UI layers |
| `none` | — | Command could not be interpreted |

> **Rule:** The LLM MUST return `request_approval` (not `assign_swarm`) whenever the command involves attacking active enemy targets. Non-attack commands (locate, track, patrol, return) execute immediately without approval.

> **Rule (Feature 14):** For any query about current state (battery, status, location, counts, comparisons), the LLM MUST return `request_status` with a `status_text` field containing the full natural language answer. The platform echoes this text to the command log without executing any swarm or drone command.

#### UI Command Sub-types (`ui_command`)
| Sub-type | Example trigger | Description |
|---|---|---|
| `fly_to` | "show Taiwan on map" | Fly camera to a named place or coordinates |
| `fly_to_target` | "focus on target X" | Fly camera to a specific target entity |
| `fly_to_drone` | "show drone R-01" | Fly camera to a specific friendly drone |
| `zoom_in` / `zoom_out` | "zoom in" | Adjust camera altitude |
| `set_view_mode` | "bird's eye view" | Switch between tactical / ground / globe views |
| `toggle_layer` | "hide friendly drones" | Show/hide entity layers (friendly, enemy, swarms) |

#### Geographic Regions (`deploy_to_region`)

The platform maintains a lookup table of named tactical regions covering the Taiwan theater. The LLM resolves natural language region references to these names:

| Region Name | Natural Language Examples | Bounding Box (approx.) |
|---|---|---|
| `west_coast` | "west coast", "western Taiwan", "the strait side" | lat 22.0–26.5, lon 119.5–121.0 |
| `east_coast` | "east coast", "eastern Taiwan", "Pacific side" | lat 22.0–26.5, lon 121.0–122.5 |
| `north_taiwan` | "north", "northern Taiwan", "the north" | lat 24.5–26.5, lon 120.5–122.0 |
| `south_taiwan` | "south", "southern Taiwan", "Kaohsiung area" | lat 22.0–24.0, lon 120.0–121.5 |
| `taipei` | "Taipei", "capital", "Taipei metro" | lat 24.9–25.2, lon 121.3–121.7 |
| `taiwan_strait` | "the strait", "Taiwan Strait", "the channel" | lat 23.0–26.5, lon 118.5–120.5 |
| `fujian` | "Fujian", "mainland China", "the mainland" | lat 23.0–27.0, lon 115.5–120.0 |
| `all_taiwan` | "all of Taiwan", "entire island", "everywhere" | lat 21.5–26.5, lon 119.5–122.5 |

### 6.5 LLM Response Schema
```json
{
  "interpretation": "plain English explanation of what was understood",
  "action": {
    "type": "assign_swarm | assign_drone | mark_target_destroyed | request_approval | deploy_to_region | request_status | ui_command | none",

    // --- Tactical fields (assign_swarm / assign_drone) ---
    "swarm_id": "<uuid>",
    "drone_model": "fpv_combat | altius_600m",
    "recommended_swarm_size": 50,
    "drone_id": "<uuid>",
    "command_type": "locate | track | attack | patrol | return | abort",
    "target_ids": ["<uuid>", ...],
    "objective": "concise mission objective string",
    "priority": 1,
    "notes": "reason for drone model and swarm size selection",

    // --- Natural language status response (request_status — Feature 14) ---
    "status_text": "MQ9-01 is currently patrolling over Taipei at 6,000m altitude. Battery at 87%. Detected 3 enemy targets within 20km radius.",

    // --- HITL approval fields (request_approval) ---
    // (also includes all Tactical fields above for the proposed attack)
    "classified_targets": [
      {
        "target_id": "<uuid>",
        "type": "ship | tank | drone | missile_launcher | soldier_unit",
        "threat_value": "high | medium | low",
        "classification_reason": "Ship — high strategic value, naval blockade capability"
      }
    ],
    "threat_summary": { "high": 2, "medium": 1, "low": 3 },
    "approval_prompt": "Request to attack 2 high-value ships and 1 medium-value tank. Approve?",

    // --- Geographic deployment fields (deploy_to_region) ---
    "region": "west_coast | east_coast | north_taiwan | south_taiwan | taipei | taiwan_strait | fujian | all_taiwan",
    "asset_filter": "all | combat | recon | fpv | altius",

    // --- UI command fields (ui_command) ---
    "ui_subtype": "fly_to | fly_to_target | fly_to_drone | zoom_in | zoom_out | set_view_mode | toggle_layer",
    "destination": {
      "name": "Taiwan",
      "lat": 23.8,
      "lon": 121.0,
      "altitude_km": 300
    },
    "target_id": "<uuid>",
    "drone_id": "<uuid>",
    "layer": "friendly | enemy | swarms | all",
    "visible": true,
    "view_mode": "tactical | ground | globe"
  },
  "explanation": "what action was taken or why no action was possible"
}
```

### 6.6 UI Command Handling (Frontend)
When the NLP API returns `action.type == "ui_command"`, the frontend interprets the action client-side and calls the CesiumJS `camera.flyTo()` / `camera.zoomIn()` / entity visibility APIs directly. **No additional backend endpoint is needed** — the LLM response itself carries all information the frontend needs. The NLP API response includes the full action JSON which the frontend routes to either the swarm command executor or the map controller based on `action.type`.

### 6.7 Fallback (No API Key)
When `OPENAI_API_KEY` is not set, a mock rule-based parser handles commands using keyword matching (`attack`, `track`, `locate`, `return`, etc.) and defaults to FPV swarms for light targets, Altius-600M swarms for heavy targets. UI commands like "show Taiwan" resolve to hardcoded coordinate lookups for common place names. **Attack commands in mock mode go through the same `request_approval` flow** — the mock classifies targets using the static type→value table and generates a pending approval. **Status queries in mock mode** (keywords: `status`, `what is`, `how many`, `battery`, `where is`, etc.) return `request_status` with a synthesised `status_text` answer built directly from the in-memory state.

---

### 6.8 Target Threat Classification (Feature 13)

The LLM (and mock fallback) assigns a `threat_value` to every target before proposing an attack. The classification drives the approval UI and the operator's risk assessment.

#### Classification Rules

| Target Type | Threat Value | Rationale |
|---|---|---|
| `ship` | **high** | High strategic value — naval blockade, amphibious assault capability, hard to replace |
| `missile_launcher` | **high** | High strategic value — land-attack range up to 400 km, significant area denial |
| `tank` | **medium** | Medium value — armored ground threat, significant but replaceable |
| `drone` (long-range) | **medium** | Medium value — significant air threat, large payload capacity |
| `drone` (FPV) | **low** | Low value — individual FPVs are cheap and plentiful |
| `soldier_unit` | **low** | Low value — infantry formations; individual tactical threat |

> **Altitude heuristic (for drones):** If a detected drone target has altitude > 500 m, it is classified as a long-range attack drone (`medium`). If altitude ≤ 500 m, it is an FPV drone (`low`).

#### HITL Approval Flow

```
Operator: "attack all ships in the strait"
          ↓
     LLM classifies targets:
       5× ship → threat_value: "high"
          ↓
  action.type = "request_approval"
  platform stores PendingApproval
          ↓
  UI shows notification:
    "⚠ Attack Request: 5 HIGH-value targets (ships)
     Swarm: ALT-Alpha, 30 Altius-600M drones
     [APPROVE ✓]  [DENY ✗]"
          ↓
    Operator clicks APPROVE
          ↓
  POST /api/nlp/approve/{id}
  → SwarmCommand executed immediately
```

#### Approval Expiry
Pending approvals expire after **5 minutes** if not acted on. Expired requests are removed from the queue and logged as `expired`.

#### PendingApproval Data Model

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique approval ID |
| `command` | string | Original operator command text |
| `interpretation` | string | LLM interpretation |
| `proposed_action` | dict | The full action object to execute if approved |
| `classified_targets` | ClassifiedTarget[] | Each target with its `threat_value` and reason |
| `threat_summary` | dict | `{high: N, medium: N, low: N}` counts |
| `approval_prompt` | string | Human-readable description for the operator |
| `status` | enum | `pending` \| `approved` \| `denied` \| `expired` |
| `created_at` | datetime | When the approval was created |
| `expires_at` | datetime | 5 minutes after `created_at` |
| `decided_at` | datetime? | When the operator made a decision |

---

### 6.9 Natural Language Status Responses (Feature 14)

The LLM (and mock fallback) can answer operator **status queries** in plain conversational English. When the LLM determines the operator is asking for information rather than issuing a command, it returns `action.type = "request_status"` with a `status_text` field containing the full natural language answer.

#### Trigger Phrases (examples)
| Query type | Example operator inputs |
|---|---|
| Drone status | "What is the status of MQ9-01?", "Where is MQ9-02 right now?", "How is SCOUT-01 doing?" |
| Battery / range | "What is the battery level of ALT-Alpha?", "How much range does FPV-Bravo have left?" |
| Fleet counts | "How many drones are currently engaging?", "How many scouts are patrolling?" |
| Enemy intel | "How many enemy ships have we detected?", "What targets are currently active?" |
| Tactical summary | "Give me a status report", "What's the current battlefield situation?" |

#### `status_text` Content Rules
- Answer must be **specific and grounded** in the current battlefield state provided in context.
- If a drone/swarm is mentioned by name, look up its actual status, position, battery, and task from context.
- Summarise counts (e.g., "23 active enemy targets: 5 ships, 4 tanks, 3 missile launchers, 11 drones") rather than listing IDs.
- Use natural military communication style ("MQ9-01 is airborne over Taipei at 6,000m, battery 87%, no contacts within 20km").
- Keep responses concise (1–3 sentences for single-entity queries; 3–6 sentences for fleet summaries).

#### Mock Fallback for Status Queries
When no API key is set, the mock parser detects status keywords (`status`, `how many`, `what is`, `where is`, `battery`, `report`, `count`, `tell me`, `how are`) and synthesises a `status_text` answer by reading from the state context:
- Named drone queries → look up the drone by name in context, report status/battery/position.
- Fleet count queries → count drones by status or model from context.
- Enemy queries → count targets by type and status from context.
- General report → combine drone, swarm, and target summary counts.

#### UI Handling
The Command Panel renders `request_status` responses as a **🤖 AI** log entry containing `action.status_text`. No swarm or drone command is executed. The response is also stored in the NLP history log with `action_type = "request_status"`.

---

## 7. Swarm Command Design (GPS-Denial Resilience)

The platform deliberately operates at the **swarm objective level**, not individual drone waypoints:

```
Operator command → LLM → SwarmCommand { objective, targets }
                                    ↓
                        Swarm receives ONE objective
                                    ↓
                    On-drone AI swarm coordination layer
                    (drones negotiate roles, routes, timing)
                                    ↓
                              Mission execution
```

This design means:
- Loss of GPS does not prevent mission execution (drones use relative positioning, optical flow, etc.)
- Loss of the C2 link after command dispatch does not abort the mission
- The platform needs no knowledge of individual drone capabilities or current positions to issue a valid command

---

## 8. Seeded Assets (Startup State)

The platform pre-loads the following friendly and enemy assets on startup for an immediately operational war game scenario over Taiwan.

> **All asset counts and properties (payload, range, speed, detection radius, swarm sizes, initial positions) are configurable — not hard-coded.** The platform reads initial asset definitions from a startup configuration source (JSON file or environment-mapped settings) before seeding the State Service. Default values match the war game scenario defined in this section. See §12 for configuration details.

### 8.1 Friendly — MQ-9 Reconnaissance Drones (4 units)

| Name | Model | Scan Area | Detection Radius | Max Flight Time | Max Range | Status |
|---|---|---|---|---|---|---|
| MQ9-01 | MQ-9 Reaper | 400 km² | **15 km** | 5 hours | 1,900 km | airborne |
| MQ9-02 | MQ-9 Reaper | 400 km² | **15 km** | 5 hours | 1,900 km | airborne |
| MQ9-03 | MQ-9 Reaper | 400 km² | **15 km** | 5 hours | 1,900 km | idle (standby) |
| MQ9-04 | MQ-9 Reaper | 400 km² | **15 km** | 5 hours | 1,900 km | idle (standby) |

**Detection radius:** Each airborne MQ-9 continuously detects all enemy assets within **15 km** of its current position. Detected assets are submitted to `POST /api/recon/feed` automatically by the simulator.

**Rotation policy:** Exactly 2 MQ-9s are always airborne. MQ9-01 and MQ9-02 start airborne (`patrolling`); MQ9-03 and MQ9-04 start on standby (`idle`). When a drone's flight time expires it returns and triggers a standby drone to launch.

**UI requirements:** The operator must be able to view the current status of each MQ-9 — including location, speed, battery, and remaining range — directly on the UI. Clicking or selecting a specific MQ-9 must show the list of enemy assets currently detected by that drone (i.e., targets whose `reported_by` field matches the selected MQ-9 ID), so the operator knows exactly what each MQ-9 is seeing.

---

### 8.2 Friendly — Scout Reconnaissance Drones (100 units)

A fleet of 100 lighter, shorter-range scout reconnaissance drones supplements the 4 MQ-9s, providing grid-based area coverage across the coastal-to-mountain zone.

| Property | Value |
|---|---|
| Model | `scout_recon` |
| Naming | SCOUT-001 … SCOUT-100 |
| Max range | 150 km |
| Max speed | 150 km/h (41.7 m/s) |
| Detection radius | **10 km** |
| Function | Real-time recon feeds: enemy positions, types, confidence |
| Deployment | Grid-based patrol (see below) |
| Status at startup | `patrolling` (up to max_in_flight) or `idle` |

**Grid patrol system:** The patrol area covers two zones: (1) **coastal sea within 25 km of the Taiwan coastline** and (2) **city areas** across Taiwan — mountain areas are explicitly excluded. This area is divided into **50×50 km grids** (100 grids total). Exactly **20 scout drones are in flight at all times**, each assigned to one of the highest-priority grids. **Coastal sea grids receive highest priority** and are always covered first; city grids fill the remaining capacity. When a drone returns due to range exhaustion, a replacement launches immediately from the nearest base. With only 20 of 100 grids covered simultaneously, lower-priority grids are left uncovered until drones rotate in.

Scout drones continuously fly patrol routes within their assigned grid and automatically submit reconnaissance feeds to `POST /api/recon/feed` for any enemy assets they detect within **10 km** of their current position.

**UI requirements:** The operator must be able to view the current status of each Scout drone — including location, speed, battery, and remaining range — directly on the UI. Clicking or selecting a specific Scout drone must show the list of enemy assets currently detected by that drone (i.e., targets whose `reported_by` field matches the selected Scout drone ID), so the operator can see what each scout is covering in real time.

---

### 8.3 Friendly — Combat Drones

#### FPV Combat Drones — 10,000 units

| Property | Value |
|---|---|
| Model | FPV Combat Drone |
| Naming | FPV-00001 … FPV-10000 |
| Max payload | 4 kg |
| Max range | 15 km |
| Best against | FPV drones, soldiers, light vehicles at close range |
| Swarm grouping | 10 swarms of 1,000 drones each (FPV-Alpha … FPV-Juliet) |

#### Altius-600M Drones — 1,000 units

| Property | Value |
|---|---|
| Model | Altius-600M |
| Naming | ALT-0001 … ALT-1000 |
| Max payload | 12 kg |
| Max range | 440 km |
| Best against | Tanks, ships, missile launchers, long-range attack drones |
| Swarm grouping | 5 swarms of 200 drones each (ALT-Alpha … ALT-Echo) |

**Total friendly combat drones: 11,000 (10,000 FPV + 1,000 Altius-600M)**  
**Total friendly assets: 11,104 (4 MQ-9 + 100 Scout Recon + 11,000 combat)**

#### Friendly Asset Deployment

**Scout recon drones** are **home-based in cities** using the same distribution as combat drones (60% Taipei area, 40% rest of Taiwan). Each scout launches from its home city to its assigned 50×50 km patrol grid (§8.2). When a scout exhausts its range and returns to home base, the next available scout at that base launches to re-cover the grid.

**Combat drones** are distributed across **major cities in Taiwan** at startup:

| Region | Allocation | Cities |
|---|---|---|
| Taipei area | **60%** | Taipei, New Taipei, Keelung, Taoyuan |
| Rest of Taiwan | **40%** | Taichung, Tainan, Kaohsiung, Hualien, and others |

MQ-9 recon drones patrol from high altitude and are not city-bound. The 60% Taipei concentration for combat drones reflects the political/military priority of the capital region.

---

### 8.4 Enemy Assets (Threat Baseline)

| Asset | Count | Location | Max Payload | Max Range | Max Speed | Notes |
|---|---|---|---|---|---|---|
| Long-range attack drones | 10,000 | Airborne / mainland China | 50 kg | 400 km | 150 km/h | Primary air threat; launched from mainland |
| FPV drones | 10,000 | Airborne over Taiwan | 4 kg | 15 km | 150 km/h | Deployed by PLA soldiers already landed in Taiwan |
| Tanks | 100 | Taiwan (west coast / inland) | — | — | 10 km/h | Armoured ground threat |
| Ships | 1,000 | **Taiwan Strait** | — | — | 22 knots (~41 km/h) | Naval blockade / amphibious assault from mainland |
| Missile launchers | **400** | Fujian, mainland China | — | — | stationary | Long-range land-attack; requires Altius-600M counter-strike |
| Soldiers | 100,000 | Landed in Taiwan | — | — | ~5 km/h | Ground invasion force; `soldier_unit` target type |

Enemy assets are registered in the platform via reconnaissance drone feeds (`POST /api/recon/feed`). The `soldier_unit` target type is used for soldier formations.

#### Enemy Asset Distribution
- **90% of enemy assets** are concentrated on the **west coast** of Taiwan and the Taiwan Strait (ships, FPV drones, tanks, soldiers operating from west-coast landing zones).
- **10% of enemy assets** are on the **east coast** (secondary assault force, flanking manoeuvres).
- Missile launchers remain in **Fujian, mainland China** (range: up to 400 km — Altius-600M required for counter-strike).
- Long-range attack drones **launch from mainland China** and travel east toward Taiwan.
- Enemy FPV drones are **deployed by PLA soldiers already landed in Taiwan** — short-range, high-density urban threat.

---

### 8.5 Drone Movement Simulation (Feature 10)

All deployed (non-`idle`) drones **continuously move** during the simulation. The backend runs a **Movement Simulator** as an asyncio background task that ticks at **1 Hz** alongside the WebSocket broadcast loop.

#### Movement Rules

| Status | Behaviour |
|---|---|
| `idle` | Stationary. No position update. |
| `patrolling` | MQ-9 and Scout recon drones orbit their assigned area at cruise speed. Heading rotates slowly (+2°/tick). |
| `searching` | Combat drones advance in current heading direction at 50% of max speed. |
| `tracking` | Combat drones converge toward their assigned target's last known position at 80% of max speed. |
| `engaging` | Combat drones close on target at 100% max speed. |
| `returning` | Drone reverses heading toward `home_position` at 100% max speed. |
| `offline` | Stationary. Drone has expended its range budget. |

#### Speed Reference

| Model | Cruise Speed | Max Speed |
|---|---|---|
| MQ-9 Recon | 60 m/s (216 km/h) | 90 m/s |
| Scout Recon | 42 m/s (150 km/h) | 42 m/s |
| FPV Combat | 42 m/s (150 km/h) | 42 m/s |
| Altius-600M | 50 m/s (180 km/h) | 50 m/s |

#### Range Budget

Each movement tick advances the drone by `speed × Δt` metres. The distance is accumulated in `range_used_km`. When `range_used_km ≥ max_range_km`:
- Status → `returning` (drone turns back toward `home_position`)
- When the drone reaches `home_position` (within 500 m): status → `idle`, `range_used_km` reset to 0

For **FPV combat drones** in `engaging` status, reaching max range while closing on a target means the drone is expended (one-way strike): status → `offline`.

#### Position Update Formula (per tick)

```
Δlat = speed * Δt * cos(heading_rad) / 111_320
Δlon = speed * Δt * sin(heading_rad) / (111_320 * cos(lat_rad))
position.lat += Δlat
position.lon += Δlon
range_used_km += speed * Δt / 1000
```

#### MQ-9 Patrol Orbits

Each airborne MQ-9 is assigned a patrol centre (its initial position). It orbits at a radius of ~10 km, adjusting heading by +2° per tick. This ensures it scans its 400 km² area continuously.

---

### 8.6 Friendly Drone Live Telemetry (Feature 11)

All deployed drones report their live position, heading, speed, and battery to Lattice continuously.

#### In Simulation Mode
The Movement Simulator updates drone state directly in the State Service each tick. Positions are immediately reflected in the next WebSocket broadcast — no explicit API call required.

#### In Hardware Integration Mode
Each physical drone calls `POST /api/swarm/telemetry` at its configured reporting interval (recommended: 1–5 seconds). The request carries a batch of position/battery/heading/speed reports. The State Service applies updates immediately; the next WebSocket tick pushes the new positions to all UI clients.

#### Telemetry Data Fields

| Field | Required | Description |
|---|---|---|
| `drone_id` | ✓ | Must match a registered drone ID |
| `position` | ✓ | `{lat, lon, alt}` in decimal degrees / metres |
| `heading` | ✓ | 0–360° |
| `speed` | ✓ | Current speed in m/s |
| `battery` | ✓ | 0–100% remaining charge — required per Feature 11 |
| `status` | ✗ | Override status if changed on-drone |

---

### 8.7 LLM Drone Selection Logic

When the LLM receives an attack command, it selects drone type and swarm size using these rules:

| Target Type | Required Payload | Recommended Drone | Min Swarm Size |
|---|---|---|---|
| FPV drone / soldier_unit | ≤4 kg, range ≤15 km | FPV Combat | 10–50 |
| Tank / missile_launcher | >4 kg, range varies | Altius-600M | 3–20 |
| Ship | >4 kg, range up to 400 km | Altius-600M | 5–30 |
| Long-range attack drone | >4 kg, long range | Altius-600M | 5–20 |

The LLM evaluates target count, confidence level, and available drone inventory before assigning a swarm.

---

### 8.8 Enemy Asset Movement Simulation

Mobile enemy assets also move during the simulation. The Movement Simulator updates enemy positions each tick alongside friendly drone movement. Updated positions are reflected in the State Service immediately; the next WebSocket broadcast delivers new coordinates to the UI and triggers recon detection checks.

#### Enemy Movement Rules

| Asset Type | Movement Behaviour | Speed |
|---|---|---|
| Ships | Advance eastward from mainland China across the Taiwan Strait toward Taiwan | 22 knots (~41 km/h / 11.3 m/s) |
| Tanks | Advance at constant heading from landing zones inland | 10 km/h (2.78 m/s) |
| Soldiers | Move slowly across terrain toward objectives | ~5 km/h (1.39 m/s) |
| Long-range attack drones | Fly eastward toward Taiwan from mainland launch points | 150 km/h (41.7 m/s) |
| FPV drones (enemy) | Roam in random patrol patterns within their deployment zone in Taiwan | 150 km/h (41.7 m/s) |
| Missile launchers | Stationary | 0 |

#### Position Update (per tick)

The same formula as friendly drones (§8.5) applies:

```
Δlat = speed * Δt * cos(heading_rad) / 111_320
Δlon = speed * Δt * sin(heading_rad) / (111_320 * cos(lat_rad))
```

#### Recon Detection Trigger

After each movement tick, the simulator checks all airborne recon drones against all active enemy targets. If an enemy target falls within the recon drone's detection radius (40 km for MQ-9, 10 km for Scout), the simulator automatically submits a `POST /api/recon/feed` report — updating that target's last-known position and confidence in the State Service.

---

## 9. Frontend UI

### 9.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  ⬡ LATTICE   [DRONES: 12,004] [SWARMS: 15] [TARGETS: —]  ● WS│  ← Header
├───────────┬─────────────────────────────┬───────────────┤
│           │                             │               │
│  SWARM &  │       CesiumJS 3D Map       │    ENEMY      │
│  DRONE    │      (terrain + entities)   │   TARGETS     │
│  STATUS   │                             │  (with threat │
│           │                             │   value badge)│
├───────────┴─────────────────────────────┴───────────────┤
│  ⚠ PENDING APPROVALS  [attack 5 high-value ships] [✓][✗]│  ← Approval bar
├─────────────────────────────────────────────────────────┤
│              OPERATOR COMMAND INTERFACE                  │  ← Footer
│  [Quick Actions]  [Direct Swarm Controls]               │
│  [Command log]                                          │
│  [NLP text input _______________________] [▶ SEND]      │
└─────────────────────────────────────────────────────────┘
```

### 9.2 3D Map (CesiumJS)

- **Terrain:** Cesium World Terrain covering **Taiwan and surrounding waters** (default camera: lat 23.8°N, lon 121.0°E, altitude 300 km for island-wide view) — falls back to WGS84 ellipsoid if no Cesium Ion token is provided
- **Color scheme overview:**
  - **Friendly assets → blue or green** (recon = blue shades; combat = green shades)
  - **Enemy assets → red** (all enemy targets rendered in red shades by type)
- **Friendly drones:** Colored by model and status
  - Idle → gray, Patrolling → model color (blue/green), Searching → yellow, Tracking → orange, Engaging → red, Returning → green
- **Friendly drones distinguished by model:**
  - MQ-9 Recon → large **cyan/blue** icon (14 px), label shown, patrolling orbit shown
  - Scout Recon → medium **blue** icon (10 px), label shown
  - FPV combat → small **green** dot (8 px, clustered by swarm)
  - Altius-600M → medium **green/cyan** icon (8 px)
- **Enemy targets → red shades by type:**
  - Drone (✈, **dark red**), Ship (⚓, **red-orange**), Tank (⊞, **bright red**), Missile Launcher (↑, **magenta-red**), Soldier Unit (◉, **crimson**)
  - Color alpha (opacity) reflects detection confidence
- **Labels:** Floating text labels above each entity
- **Interaction:** Click an entity to select it (populates target/drone ID in selection state)
- **Camera:** Default bird's-eye tactical view; free navigation

### 9.3 Command Panel

- **Quick Actions:** Pre-set NLP command buttons (Scout, Attack All, Track, RTB, Status)
- **Direct Swarm Control:** Per-swarm buttons for `🔍 locate`, `👁 track`, `⚡ attack`, `↩ return`
- **NLP Command Log:** Scrolling log of operator commands and LLM responses
- **NLP Input:** Free-text input field; submits on Enter or button click
  - Accepts both **tactical commands** ("attack all ships with altius swarm"), **UI/map commands** ("show Taiwan on map"), **deployment commands** ("deploy all assets to the west coast"), and **status queries** ("what is the status of MQ9-01?")
  - LLM response routing:
    - `ui_command` → CesiumJS camera/layer controller
    - `request_approval` → approval bar (HITL) + ⚠ log entry
    - `request_status` → 🤖 conversational answer in log, no command executed (Feature 14)
    - all others → swarm/drone command executor

### 9.3.1 Approval Bar (HITL — Feature 13)

A persistent **approval notification bar** appears above the command panel whenever there are pending attack approvals. Each pending item shows:
- Threat summary badge (e.g., `⚠ 5 HIGH  1 MEDIUM`)
- Target types and proposed swarm
- **[✓ APPROVE]** and **[✗ DENY]** buttons
- Countdown timer (5-minute expiry)

Approved actions execute immediately; denied actions are logged and discarded. The bar disappears when the queue is empty. Pending approvals are also broadcast via WebSocket so the bar updates in real time.

### 9.4 Swarm Status Panel

- Lists all swarms as cards, sorted by urgency: `engaging` → `tracking` → `searching` → `returning` → `patrolling` → `idle` — most critical assets always visible at top
- Status color-coded (idle/searching/tracking/engaging/returning)
- Expandable per-swarm to show individual drone status, battery, **remaining range** (`max_range_km − range_used_km`), and current task
- **Feature 16 — hide idle drones**: The expanded drone list within a swarm only shows non-idle drones; a summary line shows the idle count (e.g., "3 drones idle")
- **Engage auto-select (Feature 15)**: When the operator clicks the ENGAGE button in the Target List panel, the assigned combat swarm is immediately selected in this panel (expanding its drone list) and floats to the top of the sorted list
- For **recon drones** (MQ-9 and Scout), clicking an individual drone entry opens a **Detected Contacts** sub-panel listing every enemy target whose `reported_by` matches that drone — showing target type, position, confidence, and last-seen time. This satisfies the requirement that the operator can see what each recon drone is currently detecting.

### 9.5 Target List Panel

- Enemy targets grouped by type (drones, ships, tanks, missile launchers)
- Per-target: coordinates, status badge, confidence bar, speed/heading
- Click to expand: shows **ENGAGE** and **TRACK** quick-action buttons
- Destroyed/lost targets are hidden

---

## 10. Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Backend language | Python | 3.11+ |
| Backend framework | FastAPI | 0.111+ |
| ASGI server | Uvicorn (with `uvicorn[standard]`) | 0.29+ |
| Data validation | Pydantic v2 | 2.7+ |
| LLM client | openai (Python SDK) | 1.30+ |
| Env config | python-dotenv | 1.0+ |
| Frontend framework | React | 18.3+ |
| Frontend build | Vite | 5.2+ |
| 3D visualization | CesiumJS | 1.117+ |
| Frontend state | Zustand | 4.5+ |
| Cesium Vite plugin | vite-plugin-cesium | 1.3+ |

---

## 11. Project Structure

```
lattice/
├── SPEC.md                      ← This document
├── lattice_requirements.txt
│
├── backend/
│   ├── main.py                  ← FastAPI app, CORS, WebSocket, lifespan
│   ├── pytest.ini
│   ├── requirements.txt
│   ├── .env.example
│   ├── models/
│   │   ├── __init__.py
│   │   ├── target.py            ← Target, TargetType, TargetStatus, ReconFeed, Position
│   │   └── drone.py             ← Drone, Swarm, SwarmCommand, DroneCommand, enums
│   ├── services/
│   │   ├── __init__.py
│   │   ├── state_service.py     ← In-memory state store (singleton)
│   │   ├── llm_service.py       ← OpenAI integration + mock fallback
│   │   └── swarm_service.py     ← Swarm/drone command execution logic
│   └── api/
│       ├── __init__.py
│       ├── recon.py             ← /api/recon/* routes
│       ├── swarm.py             ← /api/swarm/* routes
│       └── nlp.py               ← /api/nlp/* routes
│   └── tests/
│       ├── conftest.py          ← Fixtures: fresh state, patched TestClient, helpers
│       ├── test_state_service.py
│       ├── test_swarm_service.py
│       ├── test_llm_service.py
│       ├── test_api_recon.py
│       ├── test_api_swarm.py
│       ├── test_api_nlp.py
│       └── test_api_system.py
│
└── frontend/
    ├── package.json
    ├── vite.config.js           ← Vite + React + CesiumJS plugin + dev proxy
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx              ← Root layout, header, WebSocket init
        ├── App.css              ← Global dark military theme
        ├── store/
        │   └── index.js         ← Zustand store (drones, targets, swarms, UI state)
        ├── services/
        │   ├── api.js           ← REST API client (recon, swarm, nlp, state)
        │   └── websocket.js     ← WebSocket client with auto-reconnect
        └── components/
            ├── Map3D/
            │   └── index.jsx    ← CesiumJS viewer, entity management
            ├── CommandPanel/
            │   └── index.jsx    ← NLP input, quick actions, command log
            ├── ApprovalBar/
            │   └── index.jsx    ← HITL approval bar (Feature 13)
            ├── SwarmStatus/
            │   └── index.jsx    ← Swarm/drone status cards
            └── TargetList/
                └── index.jsx    ← Enemy target list with engage actions
```

---

## 12. Configuration

### Backend Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required for LLM)* | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model name |
| `ASSETS_CONFIG` | `assets_config.json` | Path to the asset configuration file (see below) |

### Asset Configuration (`assets_config.json`)

Friendly and enemy asset counts and properties are **not hard-coded** — they are loaded at startup from `assets_config.json` (path overridable via `ASSETS_CONFIG` env var). Modifying this file and restarting the backend changes the war game scenario without any code changes.

**Configurable properties per asset type:**

| Section | Configurable Fields |
|---|---|
| `mq9` | `count`, `scan_area_km2`, `detection_radius_km`, `max_flight_time_hours`, `max_range_km`, `always_airborne` |
| `scout_recon` | `count`, `max_range_km`, `max_speed_kmh`, `detection_radius_km`, `grid_size_km`, `max_in_flight`, `patrol_priority` |
| `fpv_combat` | `count`, `max_payload_kg`, `max_range_km`, `max_speed_kmh`, `swarm_count`, `swarm_size` |
| `altius_600m` | `count`, `max_payload_kg`, `max_range_km`, `swarm_count`, `swarm_size` |
| `enemy.long_range_drones` | `count`, `max_payload_kg`, `max_range_km`, `max_speed_kmh` |
| `enemy.fpv_drones` | `count`, `max_payload_kg`, `max_range_km`, `max_speed_kmh` |
| `enemy.tanks` | `count`, `speed_kmh` |
| `enemy.ships` | `count`, `speed_knots` |
| `enemy.missile_launchers` | `count`, `location` |
| `enemy.soldiers` | `count`, `speed_kmh` |
| `enemy.distribution` | `west_coast_pct`, `east_coast_pct` |
| `deployment.taipei_pct` | Fraction of combat + scout drones based in the Taipei area |

Default values in `assets_config.json` match the war game scenario defined in §8.

### Frontend Dev Server Proxy (`vite.config.js`)

| Path | Proxied To |
|---|---|
| `/api/*` | `http://localhost:8000` |
| `/ws` | `ws://localhost:8000` (WebSocket) |

---

## 13. Startup

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env          # then fill in OPENAI_API_KEY
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev                   # starts at http://localhost:5173
```

---

## 14. Key Design Decisions

| Decision | Rationale |
|---|---|
| War game simulator framing | Platform is designed for simulation/training scenarios; all assets and terrain are virtual representations |
| Swarm-level (not drone-level) commands | Enables GPS-denial resilience; drones self-coordinate using on-board AI |
| **LLM selects drone model + swarm size** | Removes manual resource allocation burden; LLM reasons over payload, range, and target type to pick optimal assets |
| **Unified NLP for tactical + UI commands** | Single natural language interface for both combat ops and map navigation; operator never needs separate controls |
| `ui_command` handled client-side only | No backend state change needed for camera moves; keeps backend API clean and stateless for map operations |
| **Human-in-the-Loop (HITL) for attack commands** | No autonomous strikes — LLM classifies target threat value and holds proposed attack as a pending approval; operator must explicitly approve before any swarm executes an attack mission; prevents accidental or unintended kinetic action |
| **LLM natural language status responses (Feature 14)** | Status queries ("what is the battery of MQ9-01?") return a conversational `status_text` answer built from live state context — operator gets a human-readable briefing, not raw JSON; `request_status` action type routes responses to the command log without executing any command |
| **Blue/green for friendly, red for enemy** | Universal military UI convention; operators instantly distinguish IFF (Identification Friend or Foe) at a glance; recon drones = blue shades, combat drones = green shades, all enemy = red shades |
| Two drone models (FPV + Altius-600M) | Covers full threat spectrum: FPV for close swarm/infantry, Altius-600M for armoured/naval/long-range targets |
| **Three recon tiers (MQ-9, Scout, none)** | MQ-9 for high-altitude wide-area ISR with 15 km detection radius; 100 Scout drones for grid-based tactical coverage (20 drones in flight at all times, rotating across 100 × 50×50 km cells, coastal sea priority over cities, mountains excluded); all submit feeds to same `/api/recon/feed` endpoint |
| **Movement simulator as 1 Hz asyncio task** | Co-located with broadcast loop; avoids additional threads; position updates are always consistent with the state broadcast that follows immediately |
| **`range_used_km` range budget per drone** | Enforces FPV 15 km and Altius-600M 440 km range limits; FPV automatically expend on contact; Altius return to base when range consumed |
| **Batch telemetry endpoint (`POST /api/swarm/telemetry`)** | Hardware drones and the simulator share a single interface; decouples position reporting from command execution |
| **Configurable assets via `assets_config.json`** | Requirements specify assets must not be hard-coded; all drone counts, speeds, ranges, and enemy force sizes are read from a config file at startup so scenarios can be adjusted without code changes |
| **Enemy asset movement simulation** | Enemy ships, tanks, soldiers, and drones move each tick via the same 1 Hz simulator as friendly drones; recon detection is re-evaluated after each tick, keeping enemy contact positions accurate as they advance |
| **Engage auto-selects swarm in status panel (Feature 15)** | After clicking ENGAGE on a target, the frontend immediately calls `selectSwarm(assignedSwarm.id)` — the Swarm Status panel expands the tasked swarm so the operator can see its drones responding without having to manually locate it among 15 swarms |
| **Idle drones hidden inside swarm cards (Feature 16)** | Swarm cards always render so the operator can see all 15 swarms; but the expanded drone list within a selected swarm hides idle members and shows a count instead — prevents clutter from 5 idle representative drones per swarm while preserving the at-a-glance swarm overview |
| In-memory state (no database) | Simplicity for v1; easily replaced with Redis or PostgreSQL |
| WebSocket broadcast (not on-change) | 1-second polling avoids complex change-tracking; sufficient for tactical update rate |
| LLM JSON mode + low temperature | Deterministic structured output; safe for tactical command execution |
| CesiumJS for 3D map | Best-in-class geospatial 3D library; supports real terrain, globe, and entity rendering |
| Taiwan + surrounding waters as default terrain | Matches the war game scenario; provides realistic coastline, strait, and mainland context |
| Mock LLM fallback | Platform is functional without an OpenAI key for development/demo use |

---

*End of Specification*
