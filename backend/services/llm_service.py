"""LLM-powered natural language command processor using OpenAI."""
from __future__ import annotations
import json
import os
from typing import Optional
from openai import AsyncOpenAI

# ── Geographic regions for the Taiwan theater ────────────────────────────────
# Each region has a bounding box (for area_of_interest) and a camera center.
GEOGRAPHIC_REGIONS: dict[str, dict] = {
    "west_coast": {
        "display": "West Coast Taiwan",
        "bbox": {"min_lat": 22.0, "max_lat": 26.5, "min_lon": 119.5, "max_lon": 121.0},
        "center": {"lat": 24.0, "lon": 120.2, "altitude_km": 150},
    },
    "east_coast": {
        "display": "East Coast Taiwan",
        "bbox": {"min_lat": 22.0, "max_lat": 26.5, "min_lon": 121.0, "max_lon": 122.5},
        "center": {"lat": 23.8, "lon": 121.5, "altitude_km": 150},
    },
    "north_taiwan": {
        "display": "Northern Taiwan",
        "bbox": {"min_lat": 24.5, "max_lat": 26.5, "min_lon": 120.5, "max_lon": 122.0},
        "center": {"lat": 25.1, "lon": 121.4, "altitude_km": 80},
    },
    "south_taiwan": {
        "display": "Southern Taiwan",
        "bbox": {"min_lat": 22.0, "max_lat": 24.0, "min_lon": 120.0, "max_lon": 121.5},
        "center": {"lat": 22.8, "lon": 120.5, "altitude_km": 80},
    },
    "taipei": {
        "display": "Taipei Metro",
        "bbox": {"min_lat": 24.9, "max_lat": 25.2, "min_lon": 121.3, "max_lon": 121.7},
        "center": {"lat": 25.04, "lon": 121.56, "altitude_km": 30},
    },
    "taiwan_strait": {
        "display": "Taiwan Strait",
        "bbox": {"min_lat": 23.0, "max_lat": 26.5, "min_lon": 118.5, "max_lon": 120.5},
        "center": {"lat": 24.0, "lon": 119.5, "altitude_km": 200},
    },
    "fujian": {
        "display": "Fujian Province",
        "bbox": {"min_lat": 23.0, "max_lat": 27.0, "min_lon": 115.5, "max_lon": 120.0},
        "center": {"lat": 25.9, "lon": 119.3, "altitude_km": 100},
    },
    "all_taiwan": {
        "display": "All Taiwan",
        "bbox": {"min_lat": 21.5, "max_lat": 26.5, "min_lon": 119.5, "max_lon": 122.5},
        "center": {"lat": 23.8, "lon": 121.0, "altitude_km": 300},
    },
}

# Keywords that map to each region (for mock fallback)
_REGION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("west_coast",    ["west coast", "western taiwan", "the strait side", "west side"]),
    ("east_coast",    ["east coast", "eastern taiwan", "pacific side", "east side"]),
    ("north_taiwan",  ["north taiwan", "northern taiwan", "north of taiwan", "the north"]),
    ("south_taiwan",  ["south taiwan", "southern taiwan", "south of taiwan", "the south", "kaohsiung"]),
    ("taipei",        ["taipei", "capital", "taipei metro", "taipei area"]),
    ("taiwan_strait", ["taiwan strait", "the strait", "strait", "the channel"]),
    ("fujian",        ["fujian", "mainland china", "the mainland", "main land"]),
    ("all_taiwan",    ["all of taiwan", "entire island", "everywhere", "all taiwan", "island wide"]),
]

_DEPLOY_KEYWORDS = ["deploy", "redeploy", "move", "send", "dispatch", "reposition", "position", "relocate", "advance"]
_ASSET_FILTER_KEYWORDS = {
    "fpv":    ["fpv", "fpv drones", "fpv swarms"],
    "altius": ["altius", "altius-600m", "altius 600", "altius swarm"],
    "recon":  ["recon", "reconnaissance", "scout", "mq9", "mq-9"],
    "combat": ["combat", "attack drones", "combat drones"],
}


def classify_target(target_type: str, altitude: float) -> str:
    """Return 'high', 'medium', or 'low' threat value per spec §6.8."""
    if target_type in ("ship", "missile_launcher"):
        return "high"
    if target_type == "tank":
        return "medium"
    if target_type == "drone":
        return "medium" if altitude > 500 else "low"
    # soldier_unit
    return "low"

SYSTEM_PROMPT = """You are the AI tactical coordinator and UI controller for the Lattice drone swarm command and control platform — a war game simulator over Taiwan.

Your role is to interpret natural language operator commands and translate them into structured JSON actions covering three categories:
1. **Tactical commands** — assign drone swarms or single drones to missions
2. **UI commands** — control the 3D map view (pan, zoom, focus on entities)
3. **Geographic deployment commands** — redeploy all or filtered assets to a named tactical region

## Drone Fleet
- **MQ-9 Recon** (mq9_recon): Reconnaissance only. Max range 1,900 km, 27h endurance. Do NOT assign to attack missions.
- **FPV Combat** (fpv_combat): Light payload 4 kg, max range 15 km. Best for enemy FPV drones, soldiers, light vehicles at close range.
- **Altius-600M** (altius_600m): Heavy payload 12 kg, max range 440 km. Best for tanks, ships, missile launchers, long-range drones, and targets on mainland China (Fujian).

## Drone Selection Rules (apply before every assignment)
1. **Payload match**: FPV (4 kg) for light targets; Altius-600M (12 kg) for armoured/naval/long-range targets.
2. **Range check**: FPV max 15 km — only assign to nearby targets. Altius-600M max 440 km — required for mainland targets.
3. **Swarm size**: 10–50 for single vehicles; 50–200 for formations; 200+ for massed threats.
4. **Inventory**: Context includes current drone counts per model — select realistically.

## Available Action Types
- **assign_swarm**: Assign a swarm to a mission (locate/track/attack/patrol/return/abort). Include drone_model and recommended_swarm_size.
- **assign_drone**: Assign a single drone to a mission.
- **mark_target_destroyed**: Mark an enemy target as destroyed.
- **deploy_to_region**: Redeploy all (or filtered) swarms to patrol a named geographic region. Use for commands like "deploy all assets to the west coast", "move FPV drones to northern Taiwan". Fields: region (see below), asset_filter ("all"|"combat"|"recon"|"fpv"|"altius"), objective.
- **request_approval**: Used INSTEAD of assign_swarm/assign_drone when the command_type is "attack". Classify each active target as high/medium/low, produce an approval_prompt for the operator, and embed the proposed assign_swarm action in proposed_action. The operator must approve before execution.
- **request_status**: Provide a text status summary (no execution needed).
- **ui_command**: Control the 3D map (pan/zoom/focus). Sub-types: fly_to, fly_to_target, fly_to_drone, zoom_in, zoom_out, set_view_mode, toggle_layer.
- **none**: Command could not be interpreted.

## Target Threat Classification (for request_approval)
| Target type          | Condition         | Threat value |
|----------------------|-------------------|--------------|
| ship                 | any               | high         |
| missile_launcher     | any               | high         |
| tank                 | any               | medium       |
| drone                | altitude > 500 m  | medium       |
| drone                | altitude ≤ 500 m  | low          |
| soldier_unit         | any               | low          |

## Geographic Regions (for deploy_to_region)
- west_coast — Taiwan west coast and Taiwan Strait approaches
- east_coast — Taiwan east coast (Pacific side)
- north_taiwan — Northern Taiwan including Taipei
- south_taiwan — Southern Taiwan including Kaohsiung
- taipei — Taipei metropolitan area
- taiwan_strait — Taiwan Strait (between island and mainland)
- fujian — Fujian province, mainland China
- all_taiwan — All of Taiwan island

## Response Format
Always respond with a JSON object:
{
  "interpretation": "plain English explanation of what you understood",
  "action": {
    "type": "assign_swarm | assign_drone | mark_target_destroyed | deploy_to_region | request_approval | request_status | ui_command | none",

    // Tactical fields (assign_swarm / assign_drone):
    "swarm_id": "<id>",
    "drone_model": "fpv_combat | altius_600m",
    "recommended_swarm_size": 50,
    "drone_id": "<id>",
    "command_type": "locate | track | attack | patrol | return | abort",
    "target_ids": ["<id>", ...],
    "objective": "concise mission objective",
    "priority": 7,
    "notes": "reason for drone model and swarm size selection",

    // HITL attack approval fields (request_approval):
    "classified_targets": [
      {"target_id": "<id>", "type": "ship", "threat_value": "high", "position": {...}}
    ],
    "threat_summary": {"high": 2, "medium": 3, "low": 1},
    "approval_prompt": "Requesting approval to attack 6 targets: 2 high-value ships, 3 medium-value tanks, 1 low-value FPV drone.",
    "proposed_action": { /* the assign_swarm action to execute on approval */ },

    // Geographic deployment fields (deploy_to_region):
    "region": "west_coast | east_coast | north_taiwan | south_taiwan | taipei | taiwan_strait | fujian | all_taiwan",
    "asset_filter": "all | combat | recon | fpv | altius",

    // UI command fields (ui_command):
    "ui_subtype": "fly_to | fly_to_target | fly_to_drone | zoom_in | zoom_out | set_view_mode | toggle_layer",
    "destination": { "name": "Taiwan", "lat": 23.8, "lon": 121.0, "altitude_km": 300 },
    "target_id": "<id>",
    "layer": "friendly | enemy | swarms | all",
    "visible": true,
    "view_mode": "tactical | ground | globe"
  },
  "explanation": "what action was taken or why no action was possible"
}

## Rules
- In GPS-denial environments, swarm drones coordinate autonomously — assign objectives, NOT individual waypoints.
- Always prefer swarm assignments over single-drone assignments for combat missions.
- Map target references (e.g. "enemy tank") to matching target IDs from context.
- Map swarm references (e.g. "ALT-Alpha") to correct swarm IDs from context.
- Attack commands: priority 8–10. Patrol/search: priority 3–6. Deploy: priority 4–6.
- For UI commands, resolve place names to lat/lon: Taiwan (23.8, 121.0, alt 300km), Taipei (25.04, 121.56, alt 50km), Fujian (25.9, 119.3, alt 100km), Taiwan Strait (24.0, 119.5, alt 200km).
- "deploy all assets to the west coast" → deploy_to_region with region=west_coast, asset_filter=all
- "send FPV drones north" → deploy_to_region with region=north_taiwan, asset_filter=fpv
- **HITL rule**: When command_type is "attack", ALWAYS return request_approval instead of assign_swarm. Never execute an attack directly.
"""

# Hardcoded place-name lookups for mock fallback
_PLACE_COORDS = {
    "taiwan":        {"lat": 23.8,  "lon": 121.0,  "altitude_km": 300},
    "taipei":        {"lat": 25.04, "lon": 121.56, "altitude_km": 50},
    "fujian":        {"lat": 25.9,  "lon": 119.3,  "altitude_km": 100},
    "taiwan strait": {"lat": 24.0,  "lon": 119.5,  "altitude_km": 200},
    "strait":        {"lat": 24.0,  "lon": 119.5,  "altitude_km": 200},
    "kaohsiung":     {"lat": 22.63, "lon": 120.30, "altitude_km": 30},
    "taichung":      {"lat": 24.15, "lon": 120.68, "altitude_km": 30},
    "tainan":        {"lat": 23.00, "lon": 120.21, "altitude_km": 30},
}


class LLMService:
    def __init__(self):
        self.client = None
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")

    async def process_command(self, command: str, context: dict) -> dict:
        """Parse a natural language command and return a structured action."""
        context_str = json.dumps(context, indent=2, default=str)
        user_message = f"""Current battlefield state:
{context_str}

Operator command: {command}"""

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return self._mock_response(command, context)

        if self.client is None:
            self.client = AsyncOpenAI(api_key=api_key)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        text = response.choices[0].message.content
        return json.loads(text)

    def _mock_response(self, command: str, context: dict) -> dict:
        """Fallback mock response when OpenAI key is not configured."""
        cmd_lower = command.lower()
        swarms = context.get("swarms", [])
        targets = context.get("targets", [])

        # ── Geographic deployment commands ────────────────────────────────────
        is_deploy = any(w in cmd_lower for w in _DEPLOY_KEYWORDS)
        if is_deploy:
            matched_region = None
            for region_key, keywords in _REGION_KEYWORDS:
                if any(kw in cmd_lower for kw in keywords):
                    matched_region = region_key
                    break
            if matched_region:
                # Determine asset filter
                asset_filter = "all"
                for filt, keywords in _ASSET_FILTER_KEYWORDS.items():
                    if any(kw in cmd_lower for kw in keywords):
                        asset_filter = filt
                        break
                region_info = GEOGRAPHIC_REGIONS[matched_region]
                return {
                    "interpretation": f"[MOCK] Deploy {asset_filter} assets to {region_info['display']}",
                    "action": {
                        "type": "deploy_to_region",
                        "region": matched_region,
                        "asset_filter": asset_filter,
                        "objective": f"Patrol {region_info['display']}",
                        "priority": 5,
                    },
                    "explanation": f"[MOCK] Redeploying {asset_filter} swarms to {region_info['display']} for patrol.",
                }

        # ── UI commands ──────────────────────────────────────────────────────
        ui_keywords = ["show", "zoom", "focus", "map", "view", "fly to", "navigate", "go to", "look at"]
        if any(w in cmd_lower for w in ui_keywords):
            # Check if a specific drone name is mentioned
            drones = context.get("drones", [])
            matched_drone = None
            for d in drones:
                name = d.get("name", "")
                if name.lower() in cmd_lower:
                    matched_drone = d
                    break

            if matched_drone and matched_drone.get("position"):
                pos = matched_drone["position"]
                return {
                    "interpretation": f"[MOCK] Fly to drone {matched_drone['name']}",
                    "action": {
                        "type": "ui_command",
                        "ui_subtype": "fly_to_drone",
                        "drone_id": matched_drone["id"],
                        "destination": {
                            "lat": pos["lat"],
                            "lon": pos["lon"],
                            "altitude_km": max(pos.get("alt", 0) / 1000 + 0.05, 0.05),
                        },
                    },
                    "explanation": f"[MOCK] Flying map camera to drone {matched_drone['name']}.",
                }

            # Fall back to place-name lookup
            dest = None
            for place, coords in _PLACE_COORDS.items():
                if place in cmd_lower:
                    dest = {"name": place.title(), **coords}
                    break
            if dest is None:
                dest = {"name": "Taiwan", **_PLACE_COORDS["taiwan"]}
            subtype = "zoom_in" if "zoom in" in cmd_lower else "zoom_out" if "zoom out" in cmd_lower else "fly_to"
            return {
                "interpretation": f"[MOCK] UI navigation request: '{command}'",
                "action": {
                    "type": "ui_command",
                    "ui_subtype": subtype,
                    "destination": dest,
                },
                "explanation": f"[MOCK] Flying map camera to {dest['name']}.",
            }

        # ── Tactical commands ─────────────────────────────────────────────────
        action_type = "none"
        cmd_type = "patrol"
        target_ids = []
        drone_model = "fpv_combat"

        if any(w in cmd_lower for w in ["attack", "engage", "destroy", "strike"]):
            # HITL: classify targets and return request_approval instead of assign_swarm
            active_targets = [t for t in targets if t.get("status") == "active"][:6]
            classified = []
            threat_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
            for t in active_targets:
                tv = classify_target(t.get("type", ""), t.get("position", {}).get("alt", 0))
                threat_counts[tv] += 1
                classified.append({
                    "target_id": t["id"],
                    "type": t.get("type"),
                    "threat_value": tv,
                    "position": t.get("position"),
                })
            # Build the proposed assign_swarm action (to be executed if approved)
            heavy = {"tank", "ship", "missile_launcher", "drone"}
            has_heavy = any(t.get("type") in heavy for t in active_targets)
            drone_model = "altius_600m" if has_heavy else "fpv_combat"
            model_prefix = "ALT" if drone_model == "altius_600m" else "FPV"
            swarm_id = None
            for s in swarms:
                if s.get("name", "").startswith(model_prefix):
                    swarm_id = s["id"]
                    break
            if swarm_id is None and swarms:
                swarm_id = swarms[0]["id"]
            summary_parts = [f"{v} {k}-value" for k, v in threat_counts.items() if v > 0]
            approval_prompt = (
                f"Requesting approval to attack {len(classified)} target(s): "
                + ", ".join(summary_parts)
                + ". Proposed action: deploy "
                + drone_model.replace("_", " ")
                + " swarm."
            )
            proposed = {
                "type": "assign_swarm",
                "swarm_id": swarm_id,
                "drone_model": drone_model,
                "recommended_swarm_size": 50,
                "command_type": "attack",
                "target_ids": [c["target_id"] for c in classified],
                "objective": command,
                "priority": 9,
                "notes": f"Mock – {drone_model} selected for attack mission.",
            }
            return {
                "interpretation": f"[MOCK] Attack command — routing through HITL approval",
                "action": {
                    "type": "request_approval",
                    "classified_targets": classified,
                    "threat_summary": threat_counts,
                    "approval_prompt": approval_prompt,
                    "proposed_action": proposed,
                },
                "explanation": "[MOCK] Attack classified and queued for operator approval.",
            }
        elif any(w in cmd_lower for w in ["track", "follow", "monitor"]):
            action_type = "assign_swarm"
            cmd_type = "track"
        elif any(w in cmd_lower for w in ["locate", "find", "search", "scout"]):
            action_type = "assign_swarm"
            cmd_type = "locate"
        elif any(w in cmd_lower for w in ["return", "recall", "rtb"]):
            action_type = "assign_swarm"
            cmd_type = "return"

        # Prefer swarm matching the selected drone model
        swarm_id = None
        model_prefix = "ALT" if drone_model == "altius_600m" else "FPV"
        for s in swarms:
            if s.get("name", "").startswith(model_prefix):
                swarm_id = s["id"]
                break
        if swarm_id is None and swarms:
            swarm_id = swarms[0]["id"]

        return {
            "interpretation": f"[MOCK – no API key] Operator said: '{command}'",
            "action": {
                "type": action_type,
                "swarm_id": swarm_id,
                "drone_model": drone_model,
                "recommended_swarm_size": 50 if cmd_type == "attack" else 20,
                "command_type": cmd_type,
                "target_ids": target_ids,
                "objective": command,
                "priority": 7 if cmd_type == "attack" else 5,
                "notes": f"Mock response – {drone_model} selected. Configure OPENAI_API_KEY for real LLM processing.",
            },
            "explanation": f"[MOCK] Interpreted as {cmd_type} command assigned to {model_prefix} swarm.",
        }


llm_service = LLMService()
