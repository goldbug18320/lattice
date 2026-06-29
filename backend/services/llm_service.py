"""LLM-powered natural language command processor using OpenAI."""
from __future__ import annotations
import json
import math
import os
import re
from typing import Optional
from openai import AsyncOpenAI

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
2. **Attack approval requests (HITL)** — classify targets and queue for operator confirmation before any attack executes
3. **Natural language status responses** — answer status queries in plain English without issuing commands

## Drone Fleet
- **MQ-9 Recon** (mq9_recon): Reconnaissance only. Max range 1,900 km, 30+ hour endurance. Do NOT assign to attack missions.
- **Scout Recon** (scout_recon): Reconnaissance only. Max range 150 km, max speed 150 km/h. Do NOT assign to attack missions.
- **FPV Combat** (fpv_combat): Light payload 4 kg, max range 15 km. Best for enemy FPV drones, soldiers, light vehicles at close range.
- **Altius-600M** (altius_600m): Heavy payload 12 kg, max range 440 km. Best for tanks, ships, missile launchers, long-range drones, and targets on mainland China (Fujian).

## Drone Selection Rules (apply before every assignment)
1. **Payload match**: FPV (4 kg) for light targets; Altius-600M (12 kg) for armoured/naval/long-range targets.
2. **Range check**: FPV max 15 km — only assign to nearby targets. Altius-600M max 440 km — required for mainland targets.
3. **Swarm size**: 10–50 for single vehicles; 50–200 for formations; 200+ for massed threats.
4. **Inventory**: Context includes current drone counts per model — select realistically.

## Available Action Types
- **assign_swarm**: Assign a swarm to a mission (locate/patrol/return/abort). Include drone_model and recommended_swarm_size.
- **assign_drone**: Assign a single drone to a mission.
- **mark_target_destroyed**: Mark an enemy target as destroyed.
- **request_approval**: Used for two scenarios: (1) INSTEAD of assign_swarm when command_type is "attack" — classify targets, embed assign_swarm in proposed_action; (2) INSTEAD of assign_drone when command_type is "track" (Feature 24) — select a recon drone in range, embed assign_drone in proposed_action.
- **no_swarm_in_range**: Return ONLY for single-target ENGAGE (Feature 22) when no combat swarm can physically reach the target. Carry an `explanation` string. Do NOT create an approval.
- **no_recon_in_range**: Return ONLY for single-target TRACK (Feature 24) when no recon drone (MQ-9 or Scout) can physically reach the target.
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

## Response Format
Always respond with a JSON object:
{
  "interpretation": "plain English explanation of what you understood",
  "action": {
    "type": "assign_swarm | assign_drone | mark_target_destroyed | request_approval | none",

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
    "proposed_action": { /* the assign_swarm action to execute on approval */ }
  },
  "explanation": "what action was taken or why no action was possible"
}

## Rules
- In GPS-denial environments, swarm drones coordinate autonomously — assign objectives, NOT individual waypoints.
- Always prefer swarm assignments over single-drone assignments for combat missions.
- Map target references (e.g. "enemy tank") to matching target IDs from context.
- Map swarm references (e.g. "ALT-Alpha") to correct swarm IDs from context.
- Attack commands: priority 8–10. Patrol/search: priority 3–6. Track: priority 6.
- **HITL attack rule**: When command_type is "attack", ALWAYS return request_approval (not assign_swarm). Never execute an attack directly.
- **HITL single-target engage rule (Feature 22)**: When the command references a specific target ID (e.g. "engage and attack target with id <id>"), include ONLY that one target in target_ids and classified_targets. Select the nearest idle (non-engaging) combat swarm whose representative_position is within max_range_km of the target. Engaging swarms are already committed and do NOT qualify. Name the swarm in approval_prompt (e.g. "Requesting approval to engage 1 high-value ship using ALT-Alpha (212 km away)."). If no idle combat swarm can physically reach the target, return no_swarm_in_range instead of request_approval.
- **HITL track rule (Feature 24)**: When command_type is "track" and a target ID is referenced, ALWAYS return request_approval with an assign_drone proposed_action. Select the nearest MQ-9 or Scout drone whose max_range_km ≥ haversine distance to the target. If none qualifies, return no_recon_in_range.
"""

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

        # ── Tactical commands ─────────────────────────────────────────────────
        action_type = "none"
        cmd_type = "patrol"
        target_ids = []
        drone_model = "fpv_combat"

        if any(w in cmd_lower for w in ["attack", "engage", "destroy", "strike"]):
            # Feature 22: if a specific target ID is referenced, engage ONLY that target
            tid_match = re.search(r'target\s+with\s+id\s+(\S+)', cmd_lower)
            single_target_id = tid_match.group(1) if tid_match else None

            if single_target_id:
                # Single-target ENGAGE — find only that target
                single_target = next(
                    (t for t in targets if t.get("id") == single_target_id),
                    None,
                )
                active_targets = [single_target] if single_target else []
            else:
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

            # Range-aware swarm selection (Feature 22)
            target_pos = active_targets[0].get("position") if active_targets else None
            swarm_id = None
            selected_swarm_name = None
            dist_str = ""
            if target_pos:
                best_dist = float("inf")
                for s in swarms:
                    if not s.get("name", "").startswith(model_prefix):
                        continue
                    if s.get("status") in ("engaging",):
                        continue
                    s_pos = s.get("representative_position")
                    if not s_pos:
                        # Fall back: pick first matching idle swarm without range check
                        if swarm_id is None:
                            swarm_id = s["id"]
                            selected_swarm_name = s.get("name")
                        continue
                    dlat = (target_pos["lat"] - s_pos["lat"]) * 111.32
                    dlon = (target_pos["lon"] - s_pos["lon"]) * 111.32 * math.cos(math.radians(s_pos["lat"]))
                    dist = math.sqrt(dlat ** 2 + dlon ** 2)
                    max_range = s.get("max_range_km", float("inf"))
                    if dist <= max_range and dist < best_dist:
                        best_dist = dist
                        swarm_id = s["id"]
                        selected_swarm_name = s.get("name")
                        dist_str = f" ({round(dist)} km away)"
            if single_target_id and not classified:
                return {
                    "interpretation": "[MOCK] Engage command — target not found",
                    "action": {
                        "type": "no_swarm_in_range",
                        "target_id": single_target_id,
                        "explanation": "Target not found or already destroyed.",
                    },
                    "explanation": "[MOCK] Target not found.",
                }
            if single_target_id and swarm_id is None:
                return {
                    "interpretation": "[MOCK] Engage command — no combat swarm available",
                    "action": {
                        "type": "no_swarm_in_range",
                        "target_id": single_target_id,
                        "explanation": "No combat swarm in range — all swarms are currently engaged.",
                    },
                    "explanation": "[MOCK] No combat swarm available.",
                }
            if swarm_id is None:
                for s in swarms:
                    if s.get("name", "").startswith(model_prefix):
                        swarm_id = s["id"]
                        selected_swarm_name = s.get("name")
                        break
            if swarm_id is None and swarms:
                swarm_id = swarms[0]["id"]
                selected_swarm_name = swarms[0].get("name")

            if single_target_id:
                tv = classified[0]["threat_value"] if classified else "unknown"
                t_type = classified[0]["type"] if classified else "target"
                swarm_label = selected_swarm_name or "combat swarm"
                approval_prompt = (
                    f"Requesting approval to engage 1 {tv}-value {t_type} "
                    f"using {swarm_label}{dist_str}."
                )
            else:
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
            # Feature 24: TRACK routes through HITL with a recon drone
            tid_match = re.search(r'target\s+with\s+id\s+(\S+)', cmd_lower)
            target_id = tid_match.group(1) if tid_match else None

            target_pos = None
            if target_id:
                for t in targets:
                    if t.get("id") == target_id:
                        target_pos = t.get("position")
                        break

            recon_models = {"mq9_recon", "scout_recon"}
            drones = context.get("drones", [])
            available_recon = [
                d for d in drones
                if d.get("model") in recon_models
                and d.get("status") not in ("tracking", "engaging", "offline")
                and d.get("position")
                and d.get("max_range_km")
            ]

            selected_drone = None
            if target_pos and available_recon:
                best_dist = float("inf")
                for d in available_recon:
                    d_pos = d["position"]
                    dlat = (target_pos["lat"] - d_pos["lat"]) * 111.32
                    dlon = (target_pos["lon"] - d_pos["lon"]) * 111.32 * math.cos(math.radians(d_pos["lat"]))
                    dist = math.sqrt(dlat ** 2 + dlon ** 2)
                    if dist <= d["max_range_km"] and dist < best_dist:
                        best_dist = dist
                        selected_drone = d
            elif available_recon:
                selected_drone = available_recon[0]

            if selected_drone is None:
                return {
                    "interpretation": "[MOCK] Track command — no reconnaissance drone in range",
                    "action": {
                        "type": "no_recon_in_range",
                        "target_id": target_id,
                        "explanation": "No reconnaissance drone can reach this target.",
                    },
                    "explanation": "[MOCK] No recon drone is available or in range.",
                }

            drone_name = selected_drone.get("name", "Unknown")
            dist_str = ""
            if target_pos and selected_drone.get("position"):
                d_pos = selected_drone["position"]
                dlat = (target_pos["lat"] - d_pos["lat"]) * 111.32
                dlon = (target_pos["lon"] - d_pos["lon"]) * 111.32 * math.cos(math.radians(d_pos["lat"]))
                dist_km = round(math.sqrt(dlat ** 2 + dlon ** 2))
                dist_str = f" ({dist_km} km away)"
            approval_prompt = f"Requesting approval to track target using {drone_name}{dist_str}."
            proposed = {
                "type": "assign_drone",
                "drone_id": selected_drone["id"],
                "command_type": "track",
                "target_ids": [target_id] if target_id else [],
                "objective": f"Track target using {drone_name}",
                "priority": 6,
                "notes": f"Mock — {drone_name} selected for reconnaissance tracking.",
            }
            return {
                "interpretation": f"[MOCK] Track command — routing through HITL with {drone_name}",
                "action": {
                    "type": "request_approval",
                    "classified_targets": [],
                    "threat_summary": {"high": 0, "medium": 0, "low": 0},
                    "approval_prompt": approval_prompt,
                    "proposed_action": proposed,
                },
                "explanation": f"[MOCK] Track request queued for operator approval. Selected: {drone_name}.",
            }

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
