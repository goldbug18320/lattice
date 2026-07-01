# Lattice — AI-Enabled Drone Swarm Command & Control Platform
## Technical Specification v2.0

---

## 1. Overview

**Lattice** is an AI-enabled command and control (C2) platform built for a **war game simulator**. It coordinates reconnaissance and combat drone swarms over real-world terrain covering **Taiwan and surrounding waters**. The platform ingests live intelligence feeds from reconnaissance drones, visualizes the battlefield in 3D, and enables operators to issue tactical commands via panel controls. An integrated LLM selects the appropriate drone type, swarm size, and classifies targets when the operator clicks ENGAGE or TRACK — dispatching missions to AI-enabled swarms, which self-coordinate to execute them including in GPS-denied environments.

---

## 2. Goals & Non-Goals

### Goals
- Real-time ingestion of reconnaissance feeds (enemy positions, types, confidence)
- 3D terrain visualization of all friendly and enemy assets over real-world terrain (Taiwan and surrounding sea)
- **LLM-driven drone selection**: LLM automatically selects drone type (FPV vs. Altius-600M) and swarm size based on target type, required payload, and range
- **LLM target classification + human approval (HITL) (Feature 13)**: LLM classifies every attack target by threat value (high / medium / low) and generates a pending approval request; the operator must explicitly approve before any attack is executed — no autonomous strikes without human confirmation
- **Engage → auto-select combat swarm (Feature 15)**: When the operator clicks the ENGAGE button on a target in the Target List panel, the assigned combat swarm is automatically selected and highlighted in the Swarm & Drone Status panel, and swarms are sorted by activity (engaging first) — giving immediate visual confirmation of which swarm was tasked
- **Hide idle drones from Swarm & Drone Status panel (Feature 16)**: Idle individual drones are suppressed to reduce clutter — swarm cards always show (so the operator can see all swarms), but the expanded drone list within a selected swarm only shows active (non-idle) drones with a summary count of idle ones; idle recon drones are also hidden from the RECONNAISSANCE section
- **Drag-and-drop asset deployment (Feature 17)**: Both friendly and enemy assets can be dragged to new positions on the 3D map; new assets can be dragged from an Asset Palette onto the map to deploy them; every position change is immediately persisted to `assets_config.json` so the scenario layout survives restarts; when a combat drone swarm is deployed via drag-and-drop it immediately appears in the Swarm & Drone Status panel; when an enemy asset is deployed via drag-and-drop it immediately appears in the Enemy Targets panel
- **Stationary-by-default with asset context menu (Feature 33)**: All deployed assets are stationary at spawn by default — no automatic movement on placement. Right-clicking any asset on the 3D map (drone or non-drone, friendly or enemy) opens a unified five-item context menu: **Current Speed** (read-only km/h), **Current Direction** (read-only degrees), **Set Speed** (clamped to the asset's `max_speed_kmh`; speed must not exceed the asset's max capability), **Set Destination** (operator right-clicks on the map to pick a destination; the asset then moves toward that destination at the configured speed), **Remove**; for enemy assets, speed, heading, and destination are persisted to `assets_config.json` so they survive a restart; once a destination is set, the Movement Simulator advances the asset each 1 Hz tick toward the destination under the normal movement rules; terrain-stop rules (Feature 21) apply to non-drone assets — ground assets halt at water, ships halt at shore; drones are unrestricted
- **Type-specific map icons (Feature 18)**: Every asset type on the 3D map is rendered with a representative, type-appropriate icon — drone/UAV icon for all drone types (friendly and enemy), ship icon for ships, tank icon for tanks, rocket/launcher icon for missile launchers, person icon for soldier units — so operators can visually distinguish asset type at a glance without reading labels; icons are colored per the IFF scheme (blue for friendly, red for enemy)
- **Click-to-highlight enemy asset from Target List (Feature 19)**: When the operator clicks an enemy asset in the Enemy Targets panel, that entity is visually highlighted on the 3D map (enlarged point, yellow outline) and the camera flies to center on it — giving instant spatial context for any listed threat without requiring the operator to manually locate it on the map
- **Click-to-highlight asset from Swarm & Drone Status panel (Feature 20)**: When the operator clicks an asset (swarm card or individual drone) in the Swarm & Drone Status panel, the corresponding entity is highlighted on the 3D map and the camera flies to show it — lets the operator instantly locate any friendly asset in the scene
- **Terrain-constrained asset placement and movement (Feature 21)**: Ground assets (soldiers, tanks, missile launchers) must always be positioned on land and must stop when their simulated movement reaches a water boundary; ships must always be in the sea and must stop when their simulated movement reaches a shoreline; drones (friendly and enemy) are unconstrained and may be on land, at sea, or airborne — enforced both during initial config load, during drag-and-drop repositioning on the map, and at every 1 Hz movement tick
- **Real coastline polygon land/sea determination (Feature 27)**: All terrain checks use actual GeoJSON coastline polygons loaded from `/data/theater_land.json` via a standard ray-casting point-in-polygon algorithm (with correct hole handling); coverage spans the full theater — Taiwan (including Penghu, Kinmen, Matsu, Green Island, Orchid Island), China, North Korea, South Korea, Japan, and Philippines, each with their full irregular coastlines and offshore islands — no heuristics or elevation sampling
- **Single-target engage with range-aware swarm selection (Feature 22)**: When the operator clicks ENGAGE on a specific enemy asset in the Target List panel, the LLM selects a combat swarm that can physically reach that target (range check against swarm position and target position), displays the proposed swarm name in the approval prompt, and routes the request through HITL approval — only the single selected target is included in the attack; no other active targets are swept in automatically; if no swarm can reach the target, the operator is notified ("No combat swarm in range") instead of silently falling back; once approved, the platform displays a message **directly beneath the engage/disengage button** naming which drone swarm is engaging the target — this message stays **always visible** for as long as the target remains engaged (not a one-time toast), the **ENGAGE button on that target changes to DISENGAGE**, and the tasked swarm is removed from the available pool — it cannot be assigned to a second target simultaneously (one swarm per active engagement); clicking DISENGAGE prompts the operator to confirm before releasing the target and recalling the swarm to base (Feature 32)
- **Combat-on-contact destruction (Feature 23)**: When an engaging combat swarm reaches its assigned target (within contact proximity), the Movement Simulator automatically marks the target `destroyed` and the **entire combat drone swarm destroyed** (all member drones set to `offline`); the complete swarm is expended on contact — no drones survive or return. When a combat drone is in `engaging` status, its row in the Swarm & Drone Status panel always displays the **enemy target type and short ID** it is closing on — inline, without requiring the operator to click on the drone, mirroring the tracking drone disclosure in Feature 28
- **Track-on-target with HITL and recon-drone exclusivity (Feature 24)**: When the operator clicks the TRACK button on a specific enemy asset in the Target List panel, the LLM selects a reconnaissance drone (MQ-9 or Scout) that can physically reach that target (range check), displays the proposed drone name in a HITL approval prompt, and routes the request through HITL approval — only the single selected target is tracked; if no reconnaissance drone is in range, the operator is notified ("No reconnaissance drone in range") instead of silently failing; once approved, the platform displays a message **directly beneath the track/stop-tracking button** naming which drone is tracking the target — this message stays **always visible** for as long as the target remains tracked, the **TRACK button on that target changes to STOP TRACKING**, and the tasked recon drone is dedicated to that target and removed from the available pool; re-clicking TRACK on an already-tracked target displays a message identifying which drone is already tracking that target (Feature 28) — no replacement flow is triggered; clicking STOP TRACKING prompts the operator to confirm before releasing the target and recalling the recon drone (Feature 37)
- **Engaged/tracked target counts in status bar (Feature 25)**: The top status bar continuously displays two live counters derived from the WebSocket state: the number of enemy targets currently in `engaged` status and the number currently in `tracked` status — giving the operator an immediate at-a-glance summary of active engagements and active tracking assignments without opening any panel
- **Continuous target-position tracking for assigned drones (Feature 26)**: Combat drone swarms in `engaging` status and reconnaissance drones in `tracking` status must continuously recalculate their heading toward the target's **current position** at every Movement Simulator tick — not just the position the target occupied when the assignment was made; as enemy targets move (ships advancing, tanks rolling, airborne drones flying), the assigned friendly drones course-correct each second to intercept or shadow the moving target in real time
- **Recon drone 10 km standoff orbit + already-tracking notification (Feature 28)**: When a tracking reconnaissance drone closes to within **10 km** of its assigned target, it stops closing and instead maintains exactly a 10 km standoff distance — orbiting at that radius rather than continuing toward the target; if the target moves and the drone's range to it exceeds 10 km, the drone resumes advancing until it is within 10 km again. Additionally, if the operator clicks the TRACK button again on a target that is already being tracked, the platform displays a message identifying which drone is currently tracking that target — no replacement or re-assignment occurs. When a recon drone is in `tracking` status, its row in the Swarm & Drone Status panel always displays the **target type and short ID** it is shadowing — inline, without requiring the operator to click on the drone
- **Enemy target type and short ID in Target Panel (Feature 29)**: Each enemy target card in the Enemy Targets panel always displays the target type and short ID as a subtitle line directly beneath the target's primary label — visible at all times without requiring the operator to click or expand the entry, giving immediate at-a-glance identity for every listed threat
- **Hide DETECTED CONTACTS for recon drones in Swarm & Drone Status panel (Feature 30)**: Reconnaissance drone rows (MQ-9 and Scout) in the Swarm & Drone Status panel do not display a DETECTED CONTACTS sub-panel — the contacts list is suppressed entirely for recon drones; detection data is surfaced through the Enemy Targets panel instead, keeping the Swarm & Drone Status panel focused on mission and movement state
- **Idle combat and recon drone suppression (Feature 34)**: Both idle combat drones and idle reconnaissance drones are never shown on the Swarm & Drone Status panel — this rule applies continuously at all times (not only during active engagements); a swarm card is only rendered when at least one of its member drones is non-idle; idle recon drone rows are fully hidden from the RECONNAISSANCE section; no idle-drone count summary is displayed
- **Swarm displayed as single unit, no member sub-panel (Feature 35)**: In the Swarm & Drone Status panel, each swarm is rendered as a single card — like a single drone row — with no expandable sub-panel listing individual member drones; swarm-level status, assigned target type, short ID, and mission details are shown directly on the swarm card; per-drone telemetry within a swarm is not exposed in the panel
- **Combat swarm stored as single config entry with type `combat_swarm` (Feature 36)**: In `assets_config.json`, a combat swarm is persisted as one drone-shaped entry with `"type": "combat_swarm"` — carrying the swarm's collective position, battery, range, speed, heading, and capability fields; there are no separate swarm-group objects and no individual `swarm_member` drone entries in the config file; on load the backend reconstructs an in-memory `Swarm` object and a single representative drone from this entry
- **Confirmed disengage releases target and recalls swarm (Feature 32)**: When the operator clicks the DISENGAGE button on a target currently in `engaged` status, the platform displays a **confirmation prompt in the same bottom approval area used for HITL attack approvals (§9.3.1)**, asking the operator to confirm the disengagement — no swarm recall happens until the operator confirms; once confirmed, the target is released back to `active` status and the combat swarm that was engaging it is recalled — the swarm's status transitions to `returning` and it flies back to its `home_position` under the normal Movement Simulator rules (§8.5); on arrival the swarm resets to `idle` and rejoins the available pool for future ENGAGE assignments; a confirmation message is displayed beneath the button and **the button reverts from DISENGAGE to ENGAGE**; declining the prompt leaves the target engaged and the button unchanged; no LLM call is involved — the confirmation reuses the same PendingApproval/approve/deny mechanism as Feature 13
- **Confirmed stop-tracking releases target and recalls recon drone (Feature 37)**: When the operator clicks the STOP TRACKING button on a target currently in `tracked` status, the platform displays a **confirmation prompt in the same bottom approval area used for HITL attack approvals (§9.3.1)**, asking the operator to confirm the stop-tracking request — no drone recall happens until the operator confirms; once confirmed, the target is released back to `active` status and the reconnaissance drone that was tracking it is recalled — the drone's status transitions to `returning` and it flies back to its `home_position` under the normal Movement Simulator rules (§8.5); on arrival the drone resets to `idle` and rejoins the available pool for future TRACK assignments; a confirmation message is displayed beneath the button and **the button reverts from STOP TRACKING to TRACK**; declining the prompt leaves the target tracked and the button unchanged; no LLM call is involved — the confirmation reuses the same PendingApproval/approve/deny mechanism as Feature 13 and mirrors Feature 32's disengage flow
- Swarm-level (not drone-level) task assignment to support autonomous AI swarm coordination
- **Drone movement simulation (Feature 10)**: all deployed (non-idle) drones continuously update their position on the server at 1-second intervals; drones return when max range is consumed
- **Live friendly drone telemetry (Feature 11)**: drones report position, battery, heading, and speed via a dedicated batch telemetry API endpoint; UI always reflects current positions
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
│  │  Panel       │    │  │         │  │   API    │  │(OpenAI)│ │  │
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

> **Note:** `soldier_unit` is no longer enemy-exclusive — the friendly Soldier Units (§8.3.1) use the same `soldier_unit` type, distinguished by IFF affiliation (blue vs. red) rather than by a separate type value.

### 4.2 Drone (Friendly Asset)

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Unique identifier |
| `name` | string | Human-readable name (e.g. `FPV-42`, `MQ9-02`, `SCOUT-01`) |
| `model` | enum | `mq9_recon` \| `scout_recon` \| `fpv_combat` \| `altius_600m` |
| `type` | enum | `recon` \| `combat` \| `combat_swarm` (derived from model; `combat_swarm` is used for swarms loaded from config as a single entry — see Feature 36) |
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
Internal endpoint called by the ENGAGE, TRACK, DISENGAGE, and STOP TRACKING button handlers. Sends a structured command string to the LLM, which selects the appropriate drone/swarm and routes the result through the HITL approval flow. **Disengage (Feature 32)** and **Stop Tracking (Feature 37)** are each handled as an immediate pre-check — like the `already_tracked` pre-check (Feature 28) — that never reaches the LLM, but unlike a plain informational pre-check they create a **pending confirmation** rather than executing directly (see below).

**Request Body:**
```json
{ "command": "engage and attack target with id <target-uuid>" }
```

**Response:**
```json
{
  "command": "engage and attack target with id <target-uuid>",
  "interpretation": "Single-target engage — routing through HITL approval",
  "action": {
    "type": "request_approval",
    "approval_prompt": "Requesting approval to engage 1 high-value ship using ALT-Alpha (212 km away).",
    "proposed_action": { "type": "assign_swarm", "swarm_id": "...", "command_type": "attack", ... }
  },
  "execution_result": { "approval_id": "...", "status": "pending" }
}
```

**Disengage confirmation request/response (Feature 32):**
```json
{ "command": "disengage target with id <target-uuid>" }
```
```json
{
  "command": "disengage target with id <target-uuid>",
  "interpretation": "Confirm disengage — the swarm will return to base.",
  "action": {
    "type": "request_disengage_confirmation",
    "approval_prompt": "Disengage this ship from ALT-Alpha? ALT-Alpha will return to base.",
    "proposed_action": { "type": "disengage", "target_id": "...", "swarm_id": "...", "swarm_name": "ALT-Alpha" }
  },
  "execution_result": { "approval_id": "...", "status": "pending" }
}
```
No swarm recall happens yet — clicking DISENGAGE only queues this confirmation in the same pending-approval bar used for HITL attack approvals (§9.3.1). The disengage only executes once the operator confirms via `POST /api/nlp/approve/{approval_id}` (§5.4).

**Stop-tracking confirmation request/response (Feature 37):**
```json
{ "command": "stop tracking target with id <target-uuid>" }
```
```json
{
  "command": "stop tracking target with id <target-uuid>",
  "interpretation": "Confirm stop tracking — the drone will return to base.",
  "action": {
    "type": "request_stop_tracking_confirmation",
    "approval_prompt": "Stop tracking this tank from MQ9-02? MQ9-02 will return to base.",
    "proposed_action": { "type": "stop_tracking", "target_id": "...", "drone_id": "...", "drone_name": "MQ9-02" }
  },
  "execution_result": { "approval_id": "...", "status": "pending" }
}
```
No drone recall happens yet — clicking STOP TRACKING only queues this confirmation in the same pending-approval bar used for HITL attack approvals (§9.3.1). The stop-tracking request only executes once the operator confirms via `POST /api/nlp/approve/{approval_id}` (§5.4).

---

### 5.4 Attack, Disengage & Stop-Tracking Confirmation API — `/api/nlp`

**(Feature 13 — Human-in-the-Loop; Feature 32 — Disengage confirmation; Feature 37 — Stop-tracking confirmation)**

When the LLM determines that an operator command involves attacking enemy targets, it **does not execute immediately**. Instead it creates a **pending approval request** and waits for explicit operator confirmation. **Feature 32** and **Feature 37** reuse this same pending-request / approve / deny mechanism for disengage and stop-tracking confirmations respectively — a `PendingApproval` entry's `proposed_action.type` distinguishes an attack (`assign_swarm` / `assign_drone`) from a disengage (`disengage`) or a stop-tracking request (`stop_tracking`).

#### `GET /api/nlp/pending`
List all pending approval requests awaiting operator decision — HITL attack approvals, Feature 32 disengage confirmations, and Feature 37 stop-tracking confirmations.

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

A Feature 32 disengage confirmation entry carries the same envelope with `proposed_action: { "type": "disengage", "target_id": "...", "swarm_id": "...", "swarm_name": "ALT-Alpha" }` and an empty `threat_summary`/`targets` (threat classification does not apply to disengage). A Feature 37 stop-tracking confirmation entry similarly carries `proposed_action: { "type": "stop_tracking", "target_id": "...", "drone_id": "...", "drone_name": "MQ9-02" }` with an empty `threat_summary`/`targets`.

---

#### `POST /api/nlp/approve/{approval_id}`
Approve a pending request. If `proposed_action.type` is `assign_swarm`/`assign_drone`, the platform executes the proposed swarm/drone command immediately. If `proposed_action.type` is `disengage` (Feature 32), the platform instead releases the target back to `active` and recalls the named swarm (status → `returning`, heads to `home_position`) — no drones are destroyed. If `proposed_action.type` is `stop_tracking` (Feature 37), the platform releases the target back to `active` and recalls the named recon drone (status → `returning`, heads to `home_position`). A confirmation message naming the recalled swarm/drone is returned for the UI to display beneath the (now reverted) ENGAGE/TRACK button.

**Response (attack):**
```json
{ "approved": true, "approval_id": "...", "execution_result": { "success": true, "drones_tasked": 50 } }
```

**Response (disengage confirmation, Feature 32):**
```json
{
  "approved": true,
  "approval_id": "...",
  "execution_result": {
    "target_id": "...", "target_status": "active",
    "swarm_id": "...", "swarm_status": "returning",
    "explanation": "ALT-Alpha is returning to base; target is no longer engaged."
  }
}
```

**Response (stop-tracking confirmation, Feature 37):**
```json
{
  "approved": true,
  "approval_id": "...",
  "execution_result": {
    "target_id": "...", "target_status": "active",
    "drone_id": "...", "drone_status": "returning",
    "explanation": "MQ9-02 is returning to base; target is no longer tracked."
  }
}
```

---

#### `POST /api/nlp/deny/{approval_id}`
Deny a pending request. The proposed action is discarded. For an attack approval, the target is never engaged. For a Feature 32 disengage confirmation, the target **remains engaged** and the DISENGAGE button stays as-is — the swarm is not recalled. For a Feature 37 stop-tracking confirmation, the target **remains tracked** and the STOP TRACKING button stays as-is — the recon drone is not recalled.

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

#### `POST /api/assets/save-config`
Flush current in-memory asset positions and counts to `assets_config.json`. Called automatically by the backend after every drag-and-drop position update or new-asset spawn. Can also be called explicitly to checkpoint a manually edited scenario.

**Response:** `{ "saved": true, "path": "assets_config.json" }`

#### `DELETE /api/assets/drone/{drone_id}`
Remove a friendly drone from state and from `assets_config.json`.

**Response:** `{ "removed": "<drone_id>" }`

#### `DELETE /api/assets/target/{target_id}`
Remove an enemy target from state and from `assets_config.json`.

**Response:** `{ "removed": "<target_id>" }`

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
The LLM acts as a **tactical decision engine** invoked by button actions (ENGAGE, TRACK). It receives:
- A structured command string generated by the button handler (e.g., `"engage and attack target with id <id>"`)
- A snapshot of the current battlefield state (swarms, drones by model, targets with threat classification)

And returns a structured JSON action that covers two categories:
1. **Tactical commands** — which drone model to use, how large a swarm, and what mission to execute
2. **Attack approval requests (HITL)** — classifies targets by threat value and holds the proposed attack for operator confirmation before any execution

### 6.2 Drone Selection Rules (LLM Guidance)
The LLM system prompt instructs the model to apply these rules before assigning assets:

1. **Payload match**: FPV drones (4 kg) for light targets (enemy FPVs, soldiers); Altius-600M (12 kg) for heavy targets (tanks, ships, missile launchers, long-range drones).
2. **Range check**: FPV max 15 km — only assign to targets within range. Altius-600M max 160 km — range-check required before assignment.
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
| `no_swarm_in_range` | **HITL** | Returned only for single-target ENGAGE (Feature 22) when no combat swarm can physically reach the target; carries an `explanation` string the UI shows inline; no approval is created |
| `no_recon_in_range` | **HITL** | Returned only for single-target TRACK (Feature 24) when no reconnaissance drone can physically reach the target; carries an `explanation` string the UI shows inline; no approval is created |
| `request_disengage_confirmation` | **HITL-style** | Returned by the API pre-check (Feature 32) when the operator clicks DISENGAGE on a target in `engaged` status; the LLM is NOT called, but a `PendingApproval` IS created (proposed_action.type = `disengage`) so the operator must explicitly confirm in the bottom approval bar before the swarm is recalled — see §5.4 |
| `request_stop_tracking_confirmation` | **HITL-style** | Returned by the API pre-check (Feature 37) when the operator clicks STOP TRACKING on a target in `tracked` status; the LLM is NOT called, but a `PendingApproval` IS created (proposed_action.type = `stop_tracking`) so the operator must explicitly confirm in the bottom approval bar before the recon drone is recalled — see §5.4 |
| `already_tracked` | **HITL** | Returned by the API pre-check (Feature 28) when the operator clicks TRACK on a target already in `tracked` status; carries `drone_name`, `drone_id`, and `explanation`; the LLM is not called and no approval is created |
| `none` | — | Command could not be interpreted |

> **Rule:** The LLM MUST return `request_approval` (not `assign_swarm`) whenever the command involves attacking active enemy targets. Non-attack commands (locate, patrol, return) execute immediately without approval. The `track` command routes through HITL approval (Feature 24) — see Rule below.

> **Rule (Feature 22):** When the engage command originates from a single-target ENGAGE button click (i.e., the command text references a specific target ID), the LLM MUST: (1) include only that single target in `target_ids`; (2) select only a swarm whose drones can physically reach the target (haversine distance from swarm representative position to target ≤ swarm `max_range_km`); (3) display the selected swarm name in `approval_prompt`; (4) if no swarm is in range, return `action.type = "no_swarm_in_range"` with an `explanation` the UI can display to the operator ("No combat swarm can reach this target") — do NOT fall back to an out-of-range swarm. Other active targets must NOT be included. Once an approval is confirmed by the operator, the target's button changes from ENGAGE to DISENGAGE and the tasked swarm is considered committed and must be excluded from future `request_approval` responses until it returns to idle.
>
> **Rule (Feature 32):** When the operator clicks DISENGAGE on a target in `engaged` status (i.e., the command text references a specific target ID as a disengage command), the API handles this as a pre-check — the LLM is NOT called. Unlike the informational `already_engaged`/`already_tracked` pre-checks, this pre-check MUST create a `PendingApproval` (proposed_action.type = `disengage`, carrying `target_id`, `swarm_id`, and `swarm_name` of the swarm currently engaging the target) and return `action.type = "request_disengage_confirmation"` — no state changes happen yet. Only when the operator confirms via `POST /api/nlp/approve/{approval_id}` does the platform: (1) set the target's status back to `active`; (2) set the swarm's status to `returning` so it flies back to its `home_position` under the normal Movement Simulator rules (§8.5) — no drones are destroyed; (3) return a confirmation message naming the recalled swarm for the UI to display beneath the button. If the operator instead denies via `POST /api/nlp/deny/{approval_id}`, the target remains `engaged` and nothing changes. Once a confirmed swarm reaches `home_position` it resets to `idle` and rejoins the available pool for future ENGAGE assignments.

> **Rule (Feature 24):** When the track command originates from a single-target TRACK button click (i.e., the command text references a specific target ID), the LLM MUST: (1) select only a reconnaissance drone (MQ-9 or Scout) that can physically reach the target (haversine distance from drone position to target ≤ drone `max_range_km`); (2) return `action.type = "request_approval"` with `assign_drone` as the proposed action and the selected drone name in `approval_prompt`; (3) if no recon drone is in range, return `action.type = "no_recon_in_range"` with an `explanation` — do NOT fall back to an out-of-range drone. Only the single selected target is included. Once approved, the target's button changes from TRACK to STOP TRACKING and the tasked recon drone is considered committed and must be excluded from future track assignments until it returns to idle.
>
> **Rule (Feature 37):** When the operator clicks STOP TRACKING on a target in `tracked` status (i.e., the command text references a specific target ID as a stop-tracking command), the API handles this as a pre-check — the LLM is NOT called. This pre-check MUST create a `PendingApproval` (proposed_action.type = `stop_tracking`, carrying `target_id`, `drone_id`, and `drone_name` of the recon drone currently tracking the target) and return `action.type = "request_stop_tracking_confirmation"` — no state changes happen yet. Only when the operator confirms via `POST /api/nlp/approve/{approval_id}` does the platform: (1) set the target's status back to `active`; (2) set the drone's status to `returning` so it flies back to its `home_position` under the normal Movement Simulator rules (§8.5); (3) return a confirmation message naming the recalled drone for the UI to display beneath the button. If the operator instead denies via `POST /api/nlp/deny/{approval_id}`, the target remains `tracked` and nothing changes. Once a confirmed drone reaches `home_position` it resets to `idle` and rejoins the available pool for future TRACK assignments. This mirrors Feature 32's disengage rule.

### 6.5 LLM Response Schema
```json
{
  "interpretation": "plain English explanation of what was understood",
  "action": {
    "type": "assign_swarm | assign_drone | mark_target_destroyed | request_approval | none",

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
    "approval_prompt": "Request to attack 2 high-value ships and 1 medium-value tank. Approve?"
  },
  "explanation": "what action was taken or why no action was possible"
}
```

### 6.6 Fallback (No API Key)
When `OPENAI_API_KEY` is not set, a mock rule-based parser handles commands using keyword matching (`attack`, `track`, `locate`, `return`, etc.) and defaults to FPV swarms for light targets, Altius-600M swarms for heavy targets. **Attack commands in mock mode go through the same `request_approval` flow** — the mock classifies targets using the static type→value table and generates a pending approval.

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

## 8. Asset Configuration (Startup State)

The platform loads all friendly and enemy assets **exclusively from `assets_config.json`** at startup — **the system has no built-in default deployments**. If the config file is absent or empty, the battlefield starts with no assets. The values described in this section are the **default contents of `assets_config.json`** (shipped with the project for the Taiwan war game scenario); operators can modify the file directly or use drag-and-drop on the map (see §9.2) to adjust the scenario. See §12 for the full configuration schema.

> **All asset counts and properties (payload, range, speed, detection radius, swarm sizes, initial positions) are configurable — not hard-coded.** The platform reads all asset definitions from `assets_config.json` before seeding the State Service. If the file contains no assets, no drones or targets are deployed.

> **Drone status is always `idle` in `assets_config.json`.** Runtime statuses (`tracking`, `engaging`, `searching`, `returning`, `patrolling`) exist only in the in-memory State Service and are **never written back to the config file**. A system restart always brings all drones up in `idle` state, regardless of what they were doing before the reset.

> **Enemy target status is partially persisted to `assets_config.json`.** Mid-operation statuses (`engaged`, `tracked`) are never written to the config file — targets with these statuses are reloaded as `active` on startup. The statuses `active`, `destroyed`, and `lost` **are** persisted and survive a restart unchanged.

### 8.1 Friendly — MQ-9 Reconnaissance Drones

| Property | Value |
|---|---|
| Model | MQ-9 Reaper |
| Naming convention | MQ9-{N} |
| Detection radius | **15 km** |
| Max flight time | **30+ hours** |
| Max range | 1,900 km |

**Detection radius:** Each airborne MQ-9 continuously detects all enemy assets within **15 km** of its current position. Detected assets are submitted to `POST /api/recon/feed` automatically by the simulator.

**UI requirements:** The operator must be able to view the current status of each MQ-9 — including location, speed, battery, and remaining range — directly on the UI. Clicking or selecting a specific MQ-9 must show the list of enemy assets currently detected by that drone (i.e., targets whose `reported_by` field matches the selected MQ-9 ID), so the operator knows exactly what each MQ-9 is seeing.

---

### 8.2 Friendly — Scout Reconnaissance Drones

A configurable fleet of lighter, shorter-range scout reconnaissance drones supplements the MQ-9s, providing tactical area coverage across Taiwan.

| Property | Value |
|---|---|
| Model | `scout_recon` |
| Naming | SCOUT-{N} |
| Max range | 150 km |
| Max speed | 150 km/h (41.7 m/s) |
| Detection radius | **10 km** |
| Function | Real-time recon feeds: enemy positions, types, confidence |

Scout drones continuously fly patrol routes and automatically submit reconnaissance feeds to `POST /api/recon/feed` for any enemy assets they detect within **10 km** of their current position. When a scout exhausts its range it returns to home base.

**UI requirements:** The operator must be able to view the current status of each Scout drone — including location, speed, battery, and remaining range — directly on the UI. Clicking or selecting a specific Scout drone must show the list of enemy assets currently detected by that drone (i.e., targets whose `reported_by` field matches the selected Scout drone ID), so the operator can see what each scout is covering in real time.

---

### 8.3 Friendly — Combat Drones & Soldier Units

#### FPV Combat Drones

| Property | Value |
|---|---|
| Model | FPV Combat Drone |
| Naming | FPV-{N} |
| Max payload | 4 kg |
| Max range | 15 km |
| Max speed | 60 km/h |
| Best against | FPV drones, soldiers, light vehicles at close range |
| Swarm grouping | Multiple swarms (count configurable in `assets_config.json`) |

#### Altius-600M Drones

| Property | Value |
|---|---|
| Model | Altius-600M |
| Naming | ALT-{N} |
| Max payload | 12 kg |
| Max range | 160 km |
| Max speed | 90 km/h |
| Best against | Tanks, ships, missile launchers, long-range attack drones |
| Swarm grouping | Multiple swarms (count configurable in `assets_config.json`) |

#### 8.3.1 Friendly — Soldier Units

| Property | Value |
|---|---|
| Type | `soldier_unit` (friendly) |
| Count | Configurable in `assets_config.json` (default scenario: 1,000) |
| Max speed | ~5 km/h |
| IFF | Blue |
| Terrain constraint | Land only (Feature 21) — stationary by default (Feature 33); halts if movement would cross onto water |

Friendly soldier units are a ground formation, not a drone — they are deployed and persisted the same way as other non-drone assets (right-click context menu for speed/destination, Feature 33). They mirror the enemy `soldier_unit` asset type but with friendly (blue) IFF. In the default seeded scenario, friendly FPV combat swarms are collocated with the friendly Soldier Units (§8.9); this is a seeding-time convenience, not a hard constraint — either asset can be repositioned independently via drag-and-drop or the right-click context menu.

#### Friendly Asset Deployment

**Scout recon drones** are home-based and, once launched, patrol the surrounding area. They are seeded `idle` at startup (Feature 33) — the operator initiates patrol via the right-click context menu. When a scout exhausts its range it returns to home base.

**Combat drones** are distributed across major cities in Taiwan at startup; FPV combat swarms are collocated with the friendly Soldier Units in the default seeded scenario (§8.9). Exact counts and city distributions are configured in `assets_config.json`.

**Soldier units** are seeded in Taiwan (§8.9), with their own positions configured in `assets_config.json`.

MQ-9 recon drones patrol from high altitude and are not city-bound.

---

### 8.4 Enemy Assets (Threat Baseline)

| Asset | Location | Max Payload | Max Range | Max Speed | Notes |
|---|---|---|---|---|---|
| Long-range attack drones | Airborne / mainland China | 50 kg | 400 km | 150 km/h | Primary air threat; launched from mainland; organized into swarms for the default seeded scenario (§8.9) |
| FPV drones | Airborne over Taiwan | 4 kg | 15 km | 60 km/h | Organized into swarms (swarm count/size configurable, default scenario: swarm count 2,000, swarm size 5) |
| Tanks | Taiwan | — | 400 km | 30 km/h | Armoured ground threat |
| Ships | Taiwan Strait | — | 8,000 km | 55 km/h | Naval blockade / amphibious assault from mainland |
| Missile launchers | Mainland China | — | 400 km | 40 km/h | Mobile land-attack launchers; ground-constrained |
| Soldiers | Landed in Taiwan | — | — | ~5 km/h | Ground invasion force; `soldier_unit` target type (default scenario: 1,000 units, down from a prior 100,000-unit baseline) |

All enemy asset counts are configurable in `assets_config.json`. Enemy assets are registered in the platform via reconnaissance drone feeds (`POST /api/recon/feed`). The `soldier_unit` type is used for soldier formations on both sides — it is no longer enemy-exclusive (§8.3.1 introduces the friendly `soldier_unit`).

#### Enemy Asset Distribution
- Missile launchers are **mobile ground assets** (max speed 40 km/h, max range 400 km) — terrain-constrained to land; operator sets heading and speed via the right-click context menu.
- Long-range attack drones **launch from mainland China** and travel east toward Taiwan; the default scenario seeds them as swarms (§8.9), mirroring the FPV swarm structure.
- Enemy FPV drones are organized into swarms (mirroring the friendly FPV swarm structure, Feature 36) — short-range, high-density urban threat. In the default seeded scenario they are collocated with the enemy Soldier Units (§8.9).
- Enemy asset distribution across the west and east coasts of Taiwan is configurable in `assets_config.json`.

#### Terrain Placement Constraints (Feature 21)
Ground assets and ships are constrained to geographically correct terrain:

| Asset Type | Required Terrain |
|---|---|
| Soldiers (`soldier_unit`) | Land only |
| Tanks | Land only |
| Missile launchers | Land only |
| Ships | Sea / water only |
| Drones (all types, friendly and enemy) | Unconstrained — valid on land, at sea, or airborne |

These constraints apply at three points: (1) during initial load from `assets_config.json` — positions that violate the constraint are flagged/rejected; (2) during drag-and-drop repositioning on the map — the drop is snapped to a valid terrain type or rejected with a visual indicator if the operator drops a land unit in water or a ship on land; (3) during the 1 Hz Movement Simulator ticks — ground assets (soldiers, tanks, missile launchers) that would advance into a water tile are halted at the land/water boundary and stop moving; ships that would advance into a land tile are halted at the water/shore boundary and stop moving. Drones are exempt from all terrain stopping — they may cross land, sea, or airborne boundaries freely.

#### Coastline Polygon Implementation (Feature 27)
Land/sea determination for Features 21 uses **real coastline polygons** — not a heuristic or Cesium terrain elevation sample:

- **Data source**: The frontend loads `/data/theater_land.json` on first mount (a GeoJSON FeatureCollection of polygon/multipolygon land features).
- **Point-in-polygon algorithm**: Standard ray-casting algorithm, correctly handling **holes** (e.g., lakes inside land polygons) — a point is land only if it is inside an outer ring and outside all inner rings.
- **Geographic coverage** (full theater — all countries and their offshore islands):
  - **Taiwan**: full irregular coastline + Penghu, Kinmen, Matsu, Green Island, Orchid Island
  - **China**: full irregular coastline and offshore islands (including Fujian's indented coast and Xiamen Bay — needed for missile launcher and ship placement)
  - **North Korea**: full irregular coastline and offshore islands
  - **South Korea**: full irregular coastline and offshore islands
  - **Japan**: full irregular coastline and offshore islands
  - **Philippines**: full irregular coastline and offshore islands
- **Usage**: Every terrain check — at config load, at drag-and-drop drop time, and at every 1 Hz Movement Simulator tick — calls the point-in-polygon function against this dataset rather than relying on Cesium terrain sampling or bounding-box approximations.

---

### 8.5 Drone Movement Simulation (Feature 10)

All deployed (non-`idle`) drones **continuously move** during the simulation. The backend runs a **Movement Simulator** as an asyncio background task that ticks at **1 Hz** alongside the WebSocket broadcast loop.

#### Movement Rules

| Status | Behaviour |
|---|---|
| `idle` | Stationary. No position update. |
| `patrolling` | MQ-9 and Scout recon drones orbit their assigned area at cruise speed. Heading rotates slowly (+2°/tick). |
| `searching` | Combat drones advance in current heading direction at 50% of max speed. |
| `tracking` | Recon drones recalculate heading toward the assigned target's **current position** each tick and advance at 80% of max speed — target movement is followed continuously, not just aimed at the initial assignment position (Feature 26). When the drone closes to within **10 km** of the target, it stops advancing and maintains a 10 km standoff orbit instead; if the target moves farther away the drone resumes advancing (Feature 28). Re-clicking TRACK on a target already tracked by this drone displays an informational message identifying the drone — no replacement occurs (Feature 28). The target's TRACK button reads STOP TRACKING while in this status; confirming STOP TRACKING releases the target and recalls the drone (Feature 37). |
| `engaging` | Combat drones recalculate heading toward the assigned target's **current position** each tick and close at 100% max speed — course-corrects each second as the target moves (Feature 26). |
| `returning` | Drone reverses heading toward `home_position` at 100% max speed. |
| `offline` | Stationary. Drone has expended its range budget. |

#### Speed Reference

| Model | Cruise Speed | Max Speed |
|---|---|---|
| MQ-9 Recon | 60 m/s (216 km/h) | 90 m/s |
| Scout Recon | 42 m/s (150 km/h) | 42 m/s |
| FPV Combat | 16.7 m/s (60 km/h) | 16.7 m/s |
| Altius-600M | 50 m/s (180 km/h) | 50 m/s |

#### Range Budget

Each movement tick advances the drone by `speed × Δt` metres. The distance is accumulated in `range_used_km`. When `range_used_km ≥ max_range_km`:
- Status → `returning` (drone turns back toward `home_position`)
- When the drone reaches `home_position` (within 500 m): status → `idle`, `range_used_km` reset to 0

For **FPV combat drones** in `engaging` status, reaching max range while closing on a target means the drone is expended (one-way strike): status → `offline`.

#### Target Contact Detection (Feature 23)

Each tick, after updating drone positions, the Movement Simulator checks every `engaging` combat swarm against its assigned target. When **any member drone** is within **500 m** of the target:

1. **Target → `destroyed`**: the target's `status` is set to `destroyed` in the State Service; it disappears from the active target list on the next WebSocket broadcast
2. **Entire combat drone swarm → `offline`**: **every** member drone in the swarm is marked `offline` (destroyed/expended); the swarm `status` is reset to `idle` with no objective and empty `target_ids`

This applies to both FPV and Altius-600M swarms. The entire combat drone swarm is destroyed on contact — no drones survive or return after engaging a target.

The 500 m contact radius is the default; it is configurable in `assets_config.json` via `combat.contact_radius_m`.

#### Manual Disengage (Feature 32)

Before contact is made, the operator may click **DISENGAGE** on the target being engaged. Unlike Feature 23's destroy-on-contact path, disengage is a **confirmation-gated** graceful recall:

0. **Confirm**: clicking DISENGAGE does not recall the swarm immediately — it queues a confirmation prompt in the bottom approval bar (§9.3.1), the same UI area used for HITL attack approvals. Only once the operator confirms does the recall below execute; declining leaves the target `engaged` and the swarm untouched.
1. **Target → `active`**: the target's `status` reverts to `active` (it is not destroyed) and its `target_ids` reference is cleared from the swarm
2. **Swarm → `returning`**: the swarm's status is set to `returning`; it turns back toward its `home_position` under the standard `returning` movement rule (100% max speed) — no member drones are marked `offline`
3. **Swarm → `idle`**: once the swarm reaches `home_position` (within 500 m), its status resets to `idle`, `range_used_km` resets to 0, and it rejoins the available pool for future ENGAGE assignments

Disengage is available only while the target is `engaged`. Clicking DISENGAGE is handled as an immediate API pre-check (no LLM call) that creates a pending confirmation rather than executing directly; the actual recall only happens once the operator confirms — see §6.4 Rule (Feature 32) and §5.4.

#### Manual Stop Tracking (Feature 37)

Before the operator wishes to end an active tracking assignment, they may click **STOP TRACKING** on the target being tracked. This mirrors Feature 32's disengage flow but for reconnaissance drones:

0. **Confirm**: clicking STOP TRACKING does not recall the drone immediately — it queues a confirmation prompt in the bottom approval bar (§9.3.1), the same UI area used for HITL attack approvals and disengage confirmations. Only once the operator confirms does the recall below execute; declining leaves the target `tracked` and the drone untouched.
1. **Target → `active`**: the target's `status` reverts to `active` and it is no longer referenced by the tracking drone.
2. **Drone → `returning`**: the recon drone's status is set to `returning`; it turns back toward its `home_position` under the standard `returning` movement rule (100% max speed).
3. **Drone → `idle`**: once the drone reaches `home_position` (within 500 m), its status resets to `idle`, `range_used_km` resets to 0, and it rejoins the available pool for future TRACK assignments.

Stop tracking is available only while the target is `tracked`. Clicking STOP TRACKING is handled as an immediate API pre-check (no LLM call) that creates a pending confirmation rather than executing directly; the actual recall only happens once the operator confirms — see §6.4 Rule (Feature 37) and §5.4.

#### Position Update Formula (per tick)

```
Δlat = speed * Δt * cos(heading_rad) / 111_320
Δlon = speed * Δt * sin(heading_rad) / (111_320 * cos(lat_rad))
position.lat += Δlat
position.lon += Δlon
range_used_km += speed * Δt / 1000
```

#### MQ-9 Patrol Orbits

Each airborne MQ-9 is assigned a patrol centre (its initial position). It orbits around that centre, adjusting heading by +2° per tick.

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

**Enemy assets are stationary by default (Feature 33).** Movement is initiated by the operator via the unified right-click context menu on the map, which is the same for all asset types (drone and non-drone alike):

- Operator sets **speed** (km/h); clamped to asset `max_speed_kmh` (tank ≤30, ship ≤55, missile launcher ≤40, soldier ≤5, drones ≤150); speed must not exceed the asset's max capability.
- Operator sets **destination** by right-clicking on the map; the asset then moves toward that destination at the configured speed.
- Speed, heading, and destination are persisted to `assets_config.json` immediately so they survive a restart.
- Once a destination is set, the Movement Simulator advances the asset each tick toward it; terrain-stop rules apply — ground assets halt at water, ships halt at shore; drones are unrestricted.

Updated positions are reflected in the State Service immediately; the next WebSocket broadcast delivers new coordinates to the UI and triggers recon detection checks.

#### Enemy Movement Rules

The values below are the typical scenario speeds for reference; the actual speed and heading in use are whatever the operator has configured via the context menu.

| Asset Type | Movement Behaviour | Typical Speed |
|---|---|---|
| Ships | Advance at operator-set heading; **halt when reaching shore** (land boundary) | up to 55 km/h (15.3 m/s); range 8,000 km |
| Tanks | Advance at operator-set heading; **halt when reaching water** (land/sea boundary) | up to 30 km/h (8.33 m/s); range 400 km |
| Soldiers | Move at operator-set heading; **halt when reaching water** (land/sea boundary) | ~5 km/h (1.39 m/s) |
| Long-range attack drones | Fly at operator-set heading | 150 km/h (41.7 m/s) |
| FPV drones (enemy) | Fly at operator-set heading, as a swarm | 60 km/h (16.7 m/s) |
| Missile launchers | Advance at operator-set heading; **halt when reaching water** (land boundary) | up to 40 km/h (11.1 m/s); range 400 km |

#### Position Update (per tick)

The same formula as friendly drones (§8.5) applies:

```
Δlat = speed * Δt * cos(heading_rad) / 111_320
Δlon = speed * Δt * sin(heading_rad) / (111_320 * cos(lat_rad))
```

#### Recon Detection Trigger

After each movement tick, the simulator checks all airborne recon drones against all active enemy targets. If an enemy target falls within the recon drone's detection radius (15 km for MQ-9, 10 km for Scout), the simulator automatically submits a `POST /api/recon/feed` report — updating that target's last-known position and confidence in the State Service.

---

### 8.9 Initial Seeding (Startup Deployment Counts)

§§8.1–8.4 define each asset type's **capability/pool spec** — payload, range, speed, and (for combat drones) the overall fleet composition (`swarm_count` × `swarm_size`). These are the maximums the platform is configured to know about, not necessarily how many entries are actually placed on the map when the platform boots.

**Initial seeding** is a separate, smaller set of counts that governs how many entries the default `assets_config.json` scenario actually instantiates at startup. This keeps the default demo scenario manageable while still allowing the full asset pool to be dialed up via configuration.

| Side | Asset | Initial Seed Count | Location | Notes |
|---|---|---|---|---|
| Friendly | FPV combat drone swarms | 20 | Taiwan | Collocated with the friendly Soldier Units seeded below |
| Friendly | Altius-600M combat drone swarms | 100 | Taiwan | |
| Friendly | Reconnaissance (Scout) drones | 100 | Taiwan | |
| Friendly | Soldier Units | 20 | Taiwan | |
| Enemy | Long-range attack drone swarms | 20 | Mainland China | Stationary at spawn (Feature 33) |
| Enemy | FPV combat drone swarms | 10 | Taiwan | Collocated with the enemy Soldier Units seeded below |
| Enemy | Tanks | 10 | Taiwan | |
| Enemy | Ships | 20 | Taiwan Strait (water) | |
| Enemy | Missile launchers | 20 | Mainland China | |
| Enemy | Soldier Units | 10 | Taiwan | |

> **Enemy long-range attack drones are now organized into swarms for seeding purposes (mirroring Feature 36 and the enemy FPV swarm reorg in §8.4)** — the default scenario seeds 20 long-range attack drone swarm entries rather than 20 individual drones. As with enemy FPV swarms, each swarm entry is a single `Target`-shaped record carrying a `swarm_size` (member count), not one entry per individual drone. Like all seeded assets, they are stationary at spawn (Feature 33) — the operator sets heading/destination via the right-click context menu.

> **FPV combat swarms are collocated with their side's own Soldier Units** — friendly FPV swarms spawn at the same positions as the friendly Soldier Units (both seeded in Taiwan); enemy FPV swarms spawn at the same positions as the enemy Soldier Units (also Taiwan). This mirrors the "infantry-supported drone launch point" framing used elsewhere in this scenario — each side's drone swarms are never collocated with the opposing side's ground troops.

MQ-9 reconnaissance drones are unaffected by this section — their seed count remains the fixed 4-drone patrol group described in §8.1.

---

## 9. Frontend UI

### 9.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  ⬡ LATTICE  [DRONES: 12,004] [SWARMS: 15] [TARGETS: —] [ENGAGED: 2] [TRACKED: 3]  ● WS│  ← Header
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
│  [Direct Swarm Controls]                                │
└─────────────────────────────────────────────────────────┘
```

### 9.2 3D Map (CesiumJS)

- **Terrain:** Cesium World Terrain covering **Taiwan and surrounding waters** (default camera: lat 23.8°N, lon 121.0°E, altitude 300 km for island-wide view) — falls back to WGS84 ellipsoid if no Cesium Ion token is provided
- **Icon scheme (Feature 18):** Each asset type is rendered with a type-appropriate icon so operators can identify asset class at a glance:
  - Drones (all types) → UAV/drone silhouette icon
  - Ships → ship icon
  - Tanks → tank icon
  - Missile launchers → rocket/launcher icon
  - Soldier units → person icon
- **Color scheme overview:**
  - **Friendly assets → blue** (all friendly assets use blue shades regardless of role)
  - **Enemy assets → red** (all enemy targets rendered in red shades by type)
- **Friendly drones:** Colored by model and status
  - Idle → gray, Patrolling → model color (blue), Searching → yellow, Tracking → orange, Engaging → bright blue, Returning → blue
- **Friendly drones distinguished by model:**
  - MQ-9 Recon → large **cyan/blue** drone icon (14 px), label shown, patrolling orbit shown
  - Scout Recon → medium **blue** drone icon (10 px), label shown
  - FPV combat → small **blue** drone icon (8 px, clustered by swarm; swarm represented by a cluster marker when zoomed out)
  - Altius-600M → medium **blue/cyan** drone icon (8 px)
- **Enemy targets → red shades by type:**
  - Drone (UAV icon, **dark red**), Ship (ship icon, **red-orange**), Tank (tank icon, **bright red**), Missile Launcher (rocket icon, **magenta-red**), Soldier Unit (person icon, **crimson**)
  - Color alpha (opacity) reflects detection confidence
- **Labels:** Floating text labels above each entity
- **Interaction:** Click an entity to select it (populates target/drone ID in selection state)
- **Drag-and-drop deployment (Feature 17):**
  - **Reposition existing asset**: drag any entity on the map to a new location; on drop the frontend calls the appropriate PATCH endpoint (`PATCH /api/swarm/drones/{id}` for friendly, `PATCH /api/recon/targets/{id}` for enemy); the backend applies the update to in-memory state and immediately writes the new position to `assets_config.json`.
  - **Deploy new asset**: an **Asset Palette** panel (collapsible, docked to the left map edge) lists all available asset types (MQ-9, Scout, FPV, Altius-600M, enemy drone, ship, tank, missile launcher, soldier unit); drag a type from the palette and drop it on the map to spawn a new instance at that location; the backend registers the new asset and persists it to `assets_config.json`; a newly deployed combat drone swarm immediately appears in the Swarm & Drone Status panel and a newly deployed enemy asset immediately appears in the Enemy Targets panel.
  - **Asset context menu (Feature 33)**: right-click any asset (friendly or enemy, drone or non-drone) on the map to open a unified five-item context menu: **Current Speed** — read-only km/h; **Current Direction** — read-only degrees; **Set Speed** — enter km/h; backend clamps to asset `max_speed_kmh` (≤55 ships, ≤30 tanks, ≤40 missile launchers, ≤5 soldiers, ≤150 drones); speed must not exceed the asset's max capability; **Set Destination** — operator right-clicks on the map to pick a destination position; the asset then moves toward that destination at the configured speed; for enemy assets, speed, heading, and destination are persisted to `assets_config.json`; **Remove** — deletes asset from state and `assets_config.json`.
    - Terrain-stop rules (Feature 21) apply during movement — ground assets halt at water, ships halt at shore, drones are unrestricted.
  - **Terrain validation (Feature 21)**: when dropping a ground asset (soldier, tank, missile launcher), the system checks that the drop position is on land; when dropping a ship, it checks for water; drone drops are accepted anywhere (land, sea, or air); invalid drops are rejected with a visual indicator and the asset stays at its previous position; ground assets and ships that reach a terrain boundary during movement simulation are also halted in place rather than crossing it
- **Camera:** Default bird's-eye tactical view; free navigation

### 9.3 Command Panel

- **Direct Swarm Control:** Per-swarm buttons for `🔍 locate`, `👁 track`, `⚡ attack`, `↩ return`; clicking attack routes through the HITL approval flow

### 9.3.1 Approval Bar (HITL — Feature 13; also hosts Feature 32 disengage and Feature 37 stop-tracking confirmations)

A persistent **approval notification bar** appears above the command panel whenever there are pending attack approvals **or pending disengage/stop-tracking confirmations**. Each pending attack item shows:
- Threat summary badge (e.g., `⚠ 5 HIGH  1 MEDIUM`)
- Target types and proposed swarm
- **[✓ APPROVE]** and **[✗ DENY]** buttons
- Countdown timer (5-minute expiry)

A **Feature 32 disengage confirmation** entry appears in the same bar and uses the same **[✓ APPROVE]** / **[✗ DENY]** controls, but shows the `approval_prompt` text (e.g., "Disengage this ship from ALT-Alpha? ALT-Alpha will return to base.") in place of a threat summary badge, since threat classification does not apply to disengage. A **Feature 37 stop-tracking confirmation** entry behaves identically, showing an `approval_prompt` such as "Stop tracking this tank from MQ9-02? MQ9-02 will return to base."

Approved attack actions execute immediately; approving a disengage confirmation recalls the swarm (§8.5 Manual Disengage) and approving a stop-tracking confirmation recalls the recon drone (§8.5 Manual Stop Tracking). Denied actions are logged and discarded — a denied disengage confirmation leaves the target `engaged` and the swarm untouched, and a denied stop-tracking confirmation leaves the target `tracked` and the drone untouched. The bar disappears when the queue is empty. Pending approvals and confirmations are also broadcast via WebSocket so the bar updates in real time.

### 9.4 Swarm Status Panel

- Lists all swarms as cards, sorted by urgency: `engaging` → `tracking` → `searching` → `returning` → `patrolling` → `idle` — most critical assets always visible at top
- Status color-coded (idle/searching/tracking/engaging/returning)
- Expandable per-swarm to show individual drone status, battery, **remaining range** (`max_range_km − range_used_km`), and current task
- **Feature 16 — hide idle drones**: The expanded drone list within a swarm only shows non-idle drones; a summary line shows the idle count (e.g., "3 drones idle")
- **Feature 34 — idle combat and recon drones never shown**: A swarm card is only rendered when at least one member drone is non-idle — swarms where every drone is idle are fully hidden from the panel; idle reconnaissance drone rows are completely suppressed from the RECONNAISSANCE section; no idle-drone count summary is displayed; this applies at all times, not just during engagements
- **Feature 35 — swarm displayed as single unit, no member sub-panel**: Each swarm is rendered as a single card with no expandable member drone list — the swarm card shows collective status, assigned target type and short ID, and mission objective directly on the card face; individual member drone telemetry (battery, speed, remaining range per drone) is not exposed in the panel; this supersedes the expandable sub-panel behavior described under Features 16 and 34
- **Engage auto-select (Feature 15)**: When the operator clicks the ENGAGE button in the Target List panel, the assigned combat swarm is immediately selected in this panel (expanding its drone list) and floats to the top of the sorted list
- **Engaging drone → always show target (Feature 23)**: When a swarm is in `engaging` status, the target type and short ID is shown directly on the swarm card — always visible without requiring the operator to expand the card, consistent with how tracking drones display their target in the RECONNAISSANCE section
- **Click-to-highlight on map (Feature 20)**: clicking a swarm card or individual drone entry selects that asset — the corresponding entity (or all drones in the swarm) is highlighted on the 3D map (yellow outline, enlarged point) and the camera flies to center on it; a second click deselects
- **Feature 30 — no DETECTED CONTACTS for recon drones**: Reconnaissance drone rows (MQ-9 and Scout) do not display a DETECTED CONTACTS sub-panel. Detection data is surfaced through the Enemy Targets panel, not the Swarm & Drone Status panel.
- **Tracking drone → show target inline (Feature 28)**: When a recon drone is in `tracking` status, its row in the Swarm & Drone Status panel always shows the **target type and short ID** it is shadowing — displayed directly on the drone row without requiring a click, so the operator can see all tracking assignments at a glance; re-clicking TRACK on a target that is already being tracked shows a message naming the current tracking drone rather than triggering a replacement

### 9.5 Target List Panel

- Enemy targets grouped by type (drones, ships, tanks, missile launchers)
- Per-target: coordinates, status badge, confidence bar, speed/heading
- **Click to select (Feature 19)**: clicking a target entry selects it — the entity on the 3D map is immediately highlighted (enlarged point, yellow outline) and the camera flies to center on it; a second click deselects
- While selected: shows an **ENGAGE**/**DISENGAGE** toggle button and a **TRACK** quick-action button
- **ENGAGE button (Feature 22)**: while a target is `active`, its action button reads **ENGAGE**; clicking it sends `"engage and attack target with id <id>"` to the NLP endpoint; the LLM performs a range check and selects the best-fit combat swarm that can reach that specific target; the approval prompt names the proposed swarm and distance (e.g., "Requesting approval to engage 1 high-value ship using ALT-Alpha swarm (212 km away)."); only the one selected target is included in the attack; after receiving `request_approval`, the frontend pre-selects the proposed swarm in the Swarm & Drone Status panel (Feature 15); if the LLM returns `no_swarm_in_range`, the UI displays an inline error on the target entry ("No combat swarm in range") instead of creating an approval; once an approval is confirmed, the target transitions to `engaged` status, the tasked swarm is marked as committed and removed from the available pool for subsequent targets (one swarm per active engagement), **the button changes from ENGAGE to DISENGAGE**, and a message naming the engaging swarm is displayed **directly beneath the button** — this message stays **always visible** for as long as the target remains engaged, not just immediately after the click
- **DISENGAGE button (Feature 32)**: while a target is `engaged`, its action button reads **DISENGAGE**; clicking it sends `"disengage target with id <id>"` to the NLP endpoint, handled as an immediate pre-check with no LLM call — but instead of executing right away, this queues a **confirmation prompt in the bottom Approval Bar** (§9.3.1, the same area used for HITL attack approvals), asking the operator to confirm the disengagement; **no swarm recall happens until the operator confirms**; once confirmed via the Approval Bar, the target reverts to `active` status, the engaging swarm's status is set to `returning` and it flies back to its `home_position` (§8.5) — the swarm is not destroyed, only recalled — a confirmation message is displayed beneath the button, and **the button reverts from DISENGAGE to ENGAGE**; declining the prompt leaves the target `engaged` and the button unchanged; the swarm resets to `idle` and rejoins the available pool once it reaches `home_position`
- **TRACK button (Feature 24 + 28)**: clicking TRACK on a single target sends `"track target with id <id>"` to the NLP endpoint; the LLM performs a range check and selects the best-fit reconnaissance drone (MQ-9 or Scout) that can reach that specific target; the approval prompt names the proposed drone (e.g., "Requesting approval to track enemy ship using MQ9-02 (45 km away)."); only the one selected target is included; after receiving `request_approval`, the frontend pre-selects the proposed drone in the Swarm & Drone Status panel; if the LLM returns `no_recon_in_range`, the UI displays an inline error on the target entry ("No reconnaissance drone in range") instead of creating an approval; once an approval is confirmed, the target transitions to `tracked` status, the tasked recon drone is committed and removed from the available pool, **the button changes from TRACK to STOP TRACKING**, and a message naming the tracking drone is displayed **directly beneath the button** — this message stays **always visible** for as long as the target remains tracked. **Re-clicking TRACK on an already-tracked target (Feature 28)**: the platform displays an informational message identifying which drone is currently tracking that target — no new assignment, no approval flow, and no replacement of the existing tracking drone
- **STOP TRACKING button (Feature 37)**: while a target is `tracked`, its action button reads **STOP TRACKING**; clicking it sends `"stop tracking target with id <id>"` to the NLP endpoint, handled as an immediate pre-check with no LLM call — but instead of executing right away, this queues a **confirmation prompt in the bottom Approval Bar** (§9.3.1, the same area used for HITL attack approvals and disengage confirmations), asking the operator to confirm the stop-tracking request; **no drone recall happens until the operator confirms**; once confirmed via the Approval Bar, the target reverts to `active` status, the tracking drone's status is set to `returning` and it flies back to its `home_position` (§8.5) — a confirmation message is displayed beneath the button, and **the button reverts from STOP TRACKING to TRACK**; declining the prompt leaves the target `tracked` and the button unchanged; the drone resets to `idle` and rejoins the available pool once it reaches `home_position`
- **Target type and short ID subtitle (Feature 29)**: Every enemy target card always shows the target type and short ID as a subtitle line directly beneath the target name — permanently visible without clicking or expanding, so the operator can read asset type and identity at a glance across all listed threats
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
            │   └── index.jsx    ← Direct swarm controls
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

Friendly and enemy asset counts and properties are **not hard-coded** — they are loaded at startup from `assets_config.json` (path overridable via `ASSETS_CONFIG` env var). If the file is absent or contains no assets, the platform starts with an empty battlefield.

The file is the **single source of truth** for the scenario layout. It is written back automatically by the backend whenever:
- An operator drags and drops an asset to a new position (via `PATCH` endpoints)
- An operator drops a new asset from the Asset Palette onto the map
- An operator removes an asset via right-click
- `POST /api/assets/save-config` is called explicitly

**Drone status is always persisted as `idle`** in this file — runtime statuses (`tracking`, `engaging`, `searching`, `returning`, `patrolling`) are held exclusively in the in-memory State Service and are never written to `assets_config.json`. A restart resets all drones to `idle`.

**Enemy target status is partially written to this file** — mid-operation statuses (`engaged`, `tracked`) are never persisted; targets with these statuses are reloaded as `active` on restart. The statuses `active`, `destroyed`, and `lost` are persisted and survive a restart unchanged.

Modifying this file and restarting the backend changes the war game scenario without any code changes.

**Configurable properties per asset type:**

| Section | Configurable Fields |
|---|---|
| `mq9` | `count`, `detection_radius_km`, `max_flight_time_hours` (default: 30), `max_range_km`, `always_airborne` |
| `scout_recon` | `count`, `max_range_km`, `max_speed_kmh`, `detection_radius_km` |
| `fpv_combat` | `count`, `max_payload_kg`, `max_range_km`, `max_speed_kmh`, `swarm_count`, `swarm_size` |
| `altius_600m` | `count`, `max_payload_kg`, `max_range_km`, `swarm_count`, `swarm_size` |
| `enemy.long_range_drones` | `count`, `max_payload_kg`, `max_range_km`, `max_speed_kmh`, `swarm_count`, `swarm_size` |
| `enemy.fpv_drones` | `count`, `max_payload_kg`, `max_range_km`, `max_speed_kmh`, `swarm_count`, `swarm_size` |
| `enemy.tanks` | `count`, `speed_kmh` |
| `enemy.ships` | `count`, `speed_knots` |
| `enemy.missile_launchers` | `count`, `location` |
| `enemy.soldiers` | `count`, `speed_kmh` |
| `soldier_unit` | `count`, `max_speed_kmh` (friendly soldier units; flat top-level key, matching `mq9`/`scout_recon`/`fpv_combat`/`altius_600m`) |
| `enemy.distribution` | `west_coast_pct`, `east_coast_pct` (optional; controls initial spawn distribution) |
| `deployment.city_distribution` | Per-city fraction of combat + scout drones (optional; controls initial spawn distribution) |
| `initial_seed.friendly` | `fpv_swarms`, `altius_swarms`, `scout_recon`, `soldier_units` — how many entries of each friendly type the default scenario actually instantiates at startup (§8.9), independent of each type's pool/capability `count` above |
| `initial_seed.enemy` | `long_range_swarms`, `fpv_swarms`, `tanks`, `ships`, `missile_launchers`, `soldier_units` — same, for the enemy side (§8.9) |

Default values in `assets_config.json` match the war game scenario defined in §8.

### Combat Swarm Config Entry (Feature 36)

**(Feature 36)** Each combat swarm is persisted in `assets_config.json` as a **single drone-shaped entry** with `"type": "combat_swarm"`. There are no separate swarm-group objects and no individual `swarm_member` drone entries. The entry carries the swarm's collective state — position, battery, range budget, heading, speed, and capability fields — exactly like a single drone record.

**Example `combat_swarm` entry:**
```json
{
  "id": "a86c296b-a7aa-40a5-a059-dbf2bb082f12",
  "name": "ALT-Charlie",
  "model": "altius_600m",
  "type": "combat_swarm",
  "status": "idle",
  "heading": 152.99,
  "speed": 25.0,
  "altitude": 100.0,
  "battery": 72.09,
  "range_used_km": 267.63,
  "max_range_km": 160.0,
  "max_payload_kg": 12.0,
  "max_flight_time_hours": 4.0,
  "current_task": null,
  "position": { "lat": 24.104, "lon": 119.593, "alt": 200.0 },
  "home_position": { "lat": 23.0, "lon": 120.21, "alt": 0.0 }
}
```

**Load behaviour:** On startup the backend reads each `combat_swarm` entry, creates an in-memory `Swarm` object (name, model, status, target_ids), and associates it with a single representative drone record derived from the entry's fields. No `swarm_member` sub-drones are created.

**Save behaviour:** When a swarm's position, battery, or range changes, the backend writes back a single `combat_swarm` entry — never a swarm-group + member list. `status` is always written as `"idle"` (runtime statuses live only in the in-memory State Service).

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
| **No hardcoded default deployments** | System starts with only what is in `assets_config.json`; an absent or empty config = empty battlefield; the default `assets_config.json` ships with the project war game scenario so it works out of the box without baking state into code |
| **Drone status always `idle` in config; runtime state is ephemeral** | `assets_config.json` always stores drone status as `idle` — the backend never writes back runtime statuses (tracking, engaging, searching, returning) to the file; those statuses live only in the in-memory State Service and are lost on restart; this keeps the config file clean and ensures every restart begins from a predictable idle baseline |
| **Enemy target mid-operation status not persisted; active/terminal status is** | Mid-operation statuses (`engaged`, `tracked`) are never written to `assets_config.json` — those targets reload as `active` on restart; `active`, `destroyed`, and `lost` statuses are persisted and survive a restart unchanged |
| **Drag-and-drop asset deployment (Feature 17)** | Operators visually position friendly and enemy assets on the 3D map; the backend persists every drop to `assets_config.json` immediately so the layout survives restarts; the Asset Palette enables adding new asset instances without editing JSON; a newly deployed combat drone swarm appears in the Swarm & Drone Status panel immediately and a newly deployed enemy asset appears in the Enemy Targets panel immediately — no restart or manual refresh required |
| Swarm-level (not drone-level) commands | Enables GPS-denial resilience; drones self-coordinate using on-board AI |
| **LLM selects drone model + swarm size** | Removes manual resource allocation burden; LLM reasons over payload, range, and target type to pick optimal assets |
| **Human-in-the-Loop (HITL) for attack commands** | No autonomous strikes — LLM classifies target threat value and holds proposed attack as a pending approval; operator must explicitly approve before any swarm executes an attack mission; prevents accidental or unintended kinetic action |
| **Blue for friendly, red for enemy** | Universal military UI convention; operators instantly distinguish IFF (Identification Friend or Foe) at a glance; all friendly assets = blue shades, all enemy assets = red shades |
| Two drone models (FPV + Altius-600M) | Covers full threat spectrum: FPV for close swarm/infantry, Altius-600M for armoured/naval/long-range targets |
| **Three recon tiers (MQ-9, Scout, none)** | MQ-9 for high-altitude wide-area ISR with 15 km detection radius and 30+ hours endurance; Scout drones for tactical area coverage with 10 km detection radius (counts configured in `assets_config.json`); all submit feeds to same `/api/recon/feed` endpoint |
| **Movement simulator as 1 Hz asyncio task** | Co-located with broadcast loop; avoids additional threads; position updates are always consistent with the state broadcast that follows immediately |
| **`range_used_km` range budget per drone** | Enforces configured range limits (e.g., FPV 15 km, Altius-600M 160 km); FPV automatically expend on contact; Altius return to base when range consumed |
| **Batch telemetry endpoint (`POST /api/swarm/telemetry`)** | Hardware drones and the simulator share a single interface; decouples position reporting from command execution |
| **Configurable assets via `assets_config.json`** | Requirements specify assets must not be hard-coded; all drone counts, speeds, ranges, and enemy force sizes are read from a config file at startup so scenarios can be adjusted without code changes |
| **Initial seed counts decoupled from asset pool counts (§8.9)** | The `count`/`swarm_count`/`swarm_size` fields on each asset type describe its capability/pool spec (e.g. 10,000 enemy FPV drones total); `initial_seed.*` is a separate, smaller set of counts controlling how many entries the default scenario actually deploys at startup — keeps the out-of-the-box demo manageable while the full pool remains configurable |
| **Enemy asset movement simulation** | Enemy ships, tanks, soldiers, and drones move each tick via the same 1 Hz simulator as friendly drones; recon detection is re-evaluated after each tick, keeping enemy contact positions accurate as they advance |
| **`soldier_unit` shared by both IFF affiliations (§8.3.1, §8.4)** | Friendly Soldier Units (default 1,000) mirror the existing enemy `soldier_unit` type rather than introducing a new asset type; in the default seeded scenario (§8.9) each side's FPV combat swarms are collocated with that same side's Soldier Units, but the two asset types remain independently repositionable after spawn |
| **Enemy FPV drones reorganized into swarms (§8.4)** | Enemy FPV drones moved from individually-tracked drones (150 km/h) to swarm-organized units (60 km/h, default swarm count 2,000 / swarm size 5) to mirror the friendly FPV swarm structure (Feature 36) and enable swarm-level engagement symmetry between both sides |
| **Engage auto-selects swarm in status panel (Feature 15)** | After clicking ENGAGE on a target, the frontend immediately calls `selectSwarm(assignedSwarm.id)` — the Swarm Status panel expands the tasked swarm so the operator can see its drones responding without having to manually locate it among 15 swarms |
| **Idle drones hidden inside swarm cards (Feature 16)** | Swarm cards always render so the operator can see all 15 swarms; but the expanded drone list within a selected swarm hides idle members and shows a count instead — prevents clutter from 5 idle representative drones per swarm while preserving the at-a-glance swarm overview |
| **Type-specific asset icons (Feature 18)** | Each asset type renders with a distinct, recognisable icon (drone icon for UAVs, ship icon for ships, tank icon for tanks, rocket for missile launchers, person for soldier units); combined with the blue/green/red IFF coloring, every entity is immediately classifiable by both type and affiliation without reading labels |
| **Click-to-highlight + fly-to from Target List (Feature 19)** | Clicking an enemy target in the panel highlights the map entity (yellow outline, enlarged point) and triggers a `camera.flyTo()` to center on it — eliminates the need to manually scan the map for a listed threat; implemented by routing the `selectTarget` store action to both the panel selection state and a camera command |
| **Click-to-highlight + fly-to from Swarm Status panel (Feature 20)** | Clicking a swarm card or drone entry highlights the corresponding map entity and triggers `camera.flyTo()` — same mechanism as Feature 19 but for friendly assets; swarm card click highlights all member drones; individual drone click highlights that single drone |
| **Terrain-constrained placement and movement (Feature 21)** | Ground assets (soldiers, tanks, missile launchers) must be on land and stop when they reach water during movement simulation; ships must be in water and stop when they reach shore during movement simulation; drones are unconstrained (valid on land, at sea, or airborne); enforced at config load, during drag-and-drop via CesiumJS terrain sampling, and at every 1 Hz Movement Simulator tick — ground assets and ships that would cross a terrain boundary are halted in place rather than crossing it |
| **Real coastline polygons for land/sea checks (Feature 27)** | Land/sea determination uses actual GeoJSON polygon data (`/data/theater_land.json`) and a ray-casting point-in-polygon algorithm (with hole support) rather than elevation heuristics; geographic coverage spans the full theater: Taiwan (+ Penghu, Kinmen, Matsu, Green Island, Orchid Island), China, North Korea, South Korea, Japan, and Philippines — each with full coastlines and offshore islands; this is the single authoritative terrain oracle used at config load, drag-and-drop, and every Movement Simulator tick |
| **Single-target engage with range-aware swarm selection (Feature 22)** | ENGAGE on one enemy asset targets only that asset — the LLM checks which combat swarms can physically reach it (haversine distance ≤ max_range_km), selects the closest in-range swarm, names it in the approval prompt with distance, and queues a single-target HITL approval; if no swarm is in range the operator is notified inline rather than getting a misleading approval for an unreachable target; once approved, **the button on that target changes from ENGAGE to DISENGAGE** and a message naming the engaging swarm is shown directly beneath the button — kept **always visible** for as long as the target stays engaged, not a one-time toast — and the tasked swarm is committed and unavailable for concurrent engagements — prevents one swarm being double-assigned to two targets simultaneously; clicking DISENGAGE (Feature 32) prompts for confirmation before ending the engagement and recalling the swarm |
| **Confirmation-gated disengage releases target and recalls swarm (Feature 32)** | When the operator clicks DISENGAGE on an `engaged` target, the API pre-check (no LLM call) creates a `PendingApproval` (proposed_action.type = `disengage`) and surfaces it in the same bottom Approval Bar used for HITL attack approvals (§9.3.1) — the swarm is NOT recalled until the operator explicitly confirms; this mirrors Feature 13's human-in-the-loop pattern so an accidental click can't send a swarm home mid-engagement. On confirm (`POST /api/nlp/approve`), the target reverts to `active` and the engaging swarm's status is set to `returning`, flying back to its `home_position` under the normal Movement Simulator rules (§8.5) — no drones are destroyed, unlike the Feature 23 contact-destruction path; on arrival the swarm resets to `idle` and rejoins the available pool. On deny, the target stays `engaged` and nothing changes. Once confirmed, a message is shown beneath the button and the button reverts from DISENGAGE to ENGAGE. |
| **Confirmation-gated stop-tracking releases target and recalls recon drone (Feature 37)** | When the operator clicks STOP TRACKING on a `tracked` target, the API pre-check (no LLM call) creates a `PendingApproval` (proposed_action.type = `stop_tracking`) and surfaces it in the same bottom Approval Bar used for HITL attack approvals and disengage confirmations (§9.3.1) — the recon drone is NOT recalled until the operator explicitly confirms; this mirrors Feature 32's disengage pattern for the tracking flow. On confirm (`POST /api/nlp/approve`), the target reverts to `active` and the tracking drone's status is set to `returning`, flying back to its `home_position` under the normal Movement Simulator rules (§8.5); on arrival the drone resets to `idle` and rejoins the available pool. On deny, the target stays `tracked` and nothing changes. Once confirmed, a message is shown beneath the button and the button reverts from STOP TRACKING to TRACK. |
| **Combat-on-contact destruction (Feature 23)** | The 1 Hz Movement Simulator checks every engaging swarm's proximity to its assigned target each tick; when any member drone comes within 500 m, the target is auto-marked `destroyed` and the **entire combat drone swarm** is destroyed (all member drones → `offline`) — the complete swarm is expended on contact, no drones survive or return; the swarm is immediately reset to `idle` so the UI reflects its depletion. When a swarm is in `engaging` status, the assigned enemy target type and short ID are shown directly on the swarm card — no expansion required, matching the always-visible tracking drone disclosure pattern from Feature 28 |
| **Track-on-target with HITL and recon exclusivity (Feature 24)** | TRACK on one enemy asset mirrors the Feature 22 engage flow but for reconnaissance — the LLM range-checks available recon drones (MQ-9 and Scout), selects the nearest in-range drone, names it in an HITL approval prompt, and queues a single-target `assign_drone` approval; if no recon drone can reach the target the operator is notified inline; once approved **the button on that target changes from TRACK to STOP TRACKING** and a message naming the tracking drone is shown directly beneath the button — kept always visible for as long as the target stays tracked — and the drone is committed and unavailable for concurrent tracking assignments — prevents one recon drone from being tasked to shadow multiple targets simultaneously; re-clicking TRACK on an already-tracked target shows an informational message identifying the current tracking drone (Feature 28) rather than triggering a new assignment; clicking STOP TRACKING (Feature 37) prompts for confirmation before ending the tracking assignment and recalling the drone |
| **Engaged/tracked counts in status bar (Feature 25)** | The header bar derives `ENGAGED` and `TRACKED` counts client-side from the WebSocket state by filtering targets with `status == "engaged"` and `status == "tracked"` respectively — no additional API endpoint is needed; counters update every WebSocket tick (1 second) giving the operator a real-time readout of active engagements and tracking assignments at all times |
| **Continuous target-position tracking for assigned drones (Feature 26)** | At every 1 Hz Movement Simulator tick, the heading of each `engaging` combat swarm member and each `tracking` recon drone is recomputed (haversine bearing from current drone position to current target position) before the position update step — this means friendly drones continuously intercept or shadow a moving enemy target rather than flying to where the target was when first assigned; required because enemy ships, tanks, and airborne drones all move each tick; adds negligible computation (one bearing calc per assigned drone per tick) |
| **Recon drone 10 km standoff orbit + already-tracking notification (Feature 28)** | **Standoff**: at every 1 Hz Movement Simulator tick, after computing the bearing to the target, the Movement Simulator checks the haversine distance from the tracking recon drone to its assigned target; if the distance is ≤ 10 km the drone does not advance that tick (position unchanged) — it holds its current position at the 10 km perimeter and rotates heading to keep the target in the forward arc; if the target subsequently moves and the distance exceeds 10 km, the drone resumes advancing normally. **Already-tracking notification**: when the operator re-clicks TRACK on a target that already has a tracking drone assigned, the platform displays a message identifying which drone is currently tracking that target — no new HITL approval flow is started and the existing tracking drone is not replaced or released. **Tracking drone target display**: a `tracking` recon drone's row in the Swarm & Drone Status panel always shows the target type and short ID it is shadowing inline — no click required; the operator can see all active tracking assignments at a glance |
| **Enemy target type and short ID always visible in Target Panel (Feature 29)** | Each target card in the Enemy Targets panel renders the target type and short ID as a permanent subtitle — no click required; operators can immediately distinguish asset type and identity across all listed threats without reading coordinates or opening an expand view |
| **Suppress DETECTED CONTACTS for recon drones in Swarm & Drone Status panel (Feature 30)** | Reconnaissance drone rows (MQ-9 and Scout) do not show a DETECTED CONTACTS sub-panel — clicking a recon drone row expands movement/status details only; detection data is accessed via the Enemy Targets panel, separating ISR output from drone status and keeping the panel uncluttered |
| **Idle combat and recon drone suppression in Swarm & Drone Status panel (Feature 34)** | Idle drones of both types (combat and recon) are never rendered on the panel — a swarm card is only shown if at least one member drone is non-idle, and idle recon drone rows are fully hidden; this is a stricter rule than Feature 16 (which suppressed individual idle drones within an expanded swarm view but always kept the swarm card visible) — Feature 34 removes the swarm card entirely when all drones are idle, preventing panel clutter from inactive swarms |
| **Swarm displayed as single unit, no member sub-panel (Feature 35)** | Swarms are AI-coordinated units that self-assign internal roles; exposing per-drone detail in the panel adds noise without operator value — the swarm card shows collective status, assigned target, and mission objective; operators do not need to track individual swarm members because the on-drone AI handles coordination; this replaces the expandable sub-panel behavior from Features 16 and 34 |
| **Stationary-by-default with unified context menu (Feature 33)** | All deployed assets spawn stationary — no movement on placement. The right-click context menu is the same for all asset types (drone and non-drone, friendly and enemy): Current Speed / Current Direction / Set Speed / Set Destination / Remove — destination is set by right-clicking on the map; the asset then moves toward that destination at the configured speed; for enemy assets, speed, heading, and destination are persisted to `assets_config.json` so they survive a restart; entered speed is always clamped to the asset's `max_speed_kmh` |
| **Combat swarm stored as single `combat_swarm` entry in config (Feature 36)** | Each combat swarm is persisted as one drone-shaped JSON object with `"type": "combat_swarm"` — no separate swarm-group record, no individual `swarm_member` sub-drones; this keeps the config flat and consistent with how single drones (recon, enemy) are stored; on load the backend reconstructs an in-memory `Swarm` + representative drone from the single entry; on save only that one entry is written back; eliminates the `swarm_member` DroneType value from the config schema |
| In-memory state (no database) | Simplicity for v1; easily replaced with Redis or PostgreSQL |
| WebSocket broadcast (not on-change) | 1-second polling avoids complex change-tracking; sufficient for tactical update rate |
| LLM JSON mode + low temperature | Deterministic structured output; safe for tactical command execution |
| CesiumJS for 3D map | Best-in-class geospatial 3D library; supports real terrain, globe, and entity rendering |
| Taiwan + surrounding waters as default terrain | Matches the war game scenario; provides realistic coastline, strait, and mainland context |
| Mock LLM fallback | Platform is functional without an OpenAI key for development/demo use |

---

*End of Specification*
