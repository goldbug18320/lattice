"""Natural language command processing endpoint."""
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from services.state_service import state_service, APPROVAL_TTL_MINUTES
from services.llm_service import llm_service
from services.swarm_service import swarm_service
from models.drone import SwarmCommand, DroneCommand, CommandType, Swarm, Drone
from models.target import PendingApproval


def _swarm_representative_position(swarm: Swarm, all_drones: list[Drone]) -> Optional[dict]:
    """Return the average lat/lon of a swarm's member drones, or None if no positioned members."""
    members = [d for d in all_drones if d.swarm_id == swarm.id and d.position]
    if not members:
        return None
    return {
        "lat": sum(d.position.lat for d in members) / len(members),
        "lon": sum(d.position.lon for d in members) / len(members),
    }


def _swarm_max_range_km(swarm: Swarm, all_drones: list[Drone]) -> Optional[float]:
    """Return the max_range_km of the first member drone (all share the same model)."""
    member = next((d for d in all_drones if d.swarm_id == swarm.id and d.max_range_km), None)
    return member.max_range_km if member else None

router = APIRouter()


class NLPCommandRequest(BaseModel):
    command: str
    context_override: Optional[dict] = None


@router.post("/command", summary="Process a natural language operator command")
async def process_nlp_command(req: NLPCommandRequest):
    """
    Accepts a natural language command from the operator.
    Uses LLM to interpret and translate into a structured action,
    then executes it against the appropriate API.
    """
    if not req.command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty")

    # Feature 32: DISENGAGE queues a confirmation — like Feature 13's HITL attack
    # approval — rather than executing immediately. No LLM call, but a
    # PendingApproval is created so the operator must explicitly confirm (via the
    # same approval bar / approve-deny endpoints) before the swarm is recalled.
    did_match = re.search(r'disengage\s+target\s+with\s+id\s+(\S+)', req.command.lower())
    if did_match:
        target_id = did_match.group(1)
        target = state_service.get_target(target_id)
        if not target or target.status.value != "engaged":
            message = "Target is not currently engaged."
            return {
                "command": req.command,
                "interpretation": message,
                "explanation": message,
                "action": {"type": "none", "explanation": message},
                "execution_result": None,
            }

        engaging_swarm = next(
            (s for s in state_service.get_all_swarms()
             if target_id in s.target_ids and s.status.value == "engaging"),
            None,
        )
        swarm_name = engaging_swarm.name if engaging_swarm else "the combat swarm"
        swarm_id = engaging_swarm.id if engaging_swarm else None
        prompt = f"Disengage this {target.type.value} from {swarm_name}? {swarm_name} will return to base."

        approval = PendingApproval(
            command=req.command,
            interpretation="Confirm disengage — the swarm will return to base.",
            approval_prompt=prompt,
            proposed_action={
                "type": "disengage",
                "target_id": target_id,
                "swarm_id": swarm_id,
                "swarm_name": swarm_name,
            },
            expires_at=datetime.utcnow() + timedelta(minutes=APPROVAL_TTL_MINUTES),
        )
        state_service.add_approval(approval)

        return {
            "command": req.command,
            "interpretation": approval.interpretation,
            "explanation": prompt,
            "action": {
                "type": "request_disengage_confirmation",
                "approval_prompt": prompt,
                "proposed_action": approval.proposed_action,
            },
            "execution_result": {"approval_id": approval.id, "status": "pending"},
        }

    # Feature 37: STOP TRACKING queues a confirmation — mirrors Feature 32's disengage
    # flow but for reconnaissance tracking. No LLM call, but a PendingApproval is
    # created so the operator must explicitly confirm before the recon drone is recalled.
    stid_match = re.search(r'stop\s+tracking\s+target\s+with\s+id\s+(\S+)', req.command.lower())
    if stid_match:
        target_id = stid_match.group(1)
        target = state_service.get_target(target_id)
        if not target or target.status.value != "tracked":
            message = "Target is not currently tracked."
            return {
                "command": req.command,
                "interpretation": message,
                "explanation": message,
                "action": {"type": "none", "explanation": message},
                "execution_result": None,
            }

        tracking_drone = next(
            (d for d in state_service.get_all_drones()
             if d.tracking_target_id == target_id and d.status.value == "tracking"),
            None,
        )
        drone_name = tracking_drone.name if tracking_drone else "the reconnaissance drone"
        drone_id = tracking_drone.id if tracking_drone else None
        prompt = f"Stop tracking this {target.type.value} from {drone_name}? {drone_name} will return to base."

        approval = PendingApproval(
            command=req.command,
            interpretation="Confirm stop tracking — the drone will return to base.",
            approval_prompt=prompt,
            proposed_action={
                "type": "stop_tracking",
                "target_id": target_id,
                "drone_id": drone_id,
                "drone_name": drone_name,
            },
            expires_at=datetime.utcnow() + timedelta(minutes=APPROVAL_TTL_MINUTES),
        )
        state_service.add_approval(approval)

        return {
            "command": req.command,
            "interpretation": approval.interpretation,
            "explanation": prompt,
            "action": {
                "type": "request_stop_tracking_confirmation",
                "approval_prompt": prompt,
                "proposed_action": approval.proposed_action,
            },
            "execution_result": {"approval_id": approval.id, "status": "pending"},
        }

    # Feature 28: if this is a single-target TRACK and the target is already tracked,
    # return an informational response identifying the current tracking drone — no LLM call,
    # no approval, no replacement.
    tid_match = re.search(r'track\s+target\s+with\s+id\s+(\S+)', req.command.lower())
    if tid_match:
        target_id = tid_match.group(1)
        target = state_service.get_target(target_id)
        if target and target.status.value == "tracked":
            tracking_drone = next(
                (d for d in state_service.get_all_drones() if d.tracking_target_id == target_id),
                None,
            )
            drone_name = tracking_drone.name if tracking_drone else "a reconnaissance drone"
            message = f"Target is already being tracked by {drone_name}."
            return {
                "command": req.command,
                "interpretation": "Target is already in tracked status.",
                "explanation": message,
                "action": {
                    "type": "already_tracked",
                    "drone_name": drone_name,
                    "drone_id": tracking_drone.id if tracking_drone else None,
                    "explanation": message,
                },
                "execution_result": None,
            }

    # Build battlefield context for the LLM
    all_drones = state_service.get_all_drones()
    context = req.context_override or {
        "swarms": [
            {
                "id": s.id,
                "name": s.name,
                "drone_model": s.drone_model.value if s.drone_model else None,
                "fleet_size": s.total_drone_count if s.total_drone_count > 0 else len(s.drone_ids),
                "status": s.status.value,
                "drone_count": len(s.drone_ids),
                "objective": s.objective,
                # Feature 22: provide position + range so the LLM can do a range check
                "representative_position": _swarm_representative_position(s, all_drones),
                "max_range_km": _swarm_max_range_km(s, all_drones),
            }
            for s in state_service.get_all_swarms()
        ],
        "drones": [
            {
                "id": d.id,
                "name": d.name,
                "type": d.type.value,
                "model": d.model.value if d.model else None,
                "status": d.status.value,
                "battery": d.battery,
                "max_payload_kg": d.max_payload_kg,
                "max_range_km": d.max_range_km,
                "swarm_id": d.swarm_id,
                "position": d.position.model_dump() if d.position else None,
            }
            for d in all_drones
        ],
        "targets": [
            {
                "id": t.id,
                "type": t.type.value,
                "status": t.status.value,
                "position": t.position.model_dump(),
                "confidence": t.confidence,
            }
            for t in state_service.get_all_targets()
            if t.affiliation == "enemy"
        ],
    }

    # Call LLM
    llm_result = await llm_service.process_command(req.command, context)

    action = llm_result.get("action", {})
    execution_result = None

    if action.get("type") == "request_approval":
        approval = PendingApproval(
            command=req.command,
            interpretation=llm_result.get("interpretation", ""),
            approval_prompt=action.get("approval_prompt", req.command),
            threat_summary=action.get("threat_summary", {}),
            classified_targets=action.get("classified_targets", []),
            proposed_action=action.get("proposed_action", {}),
            expires_at=datetime.utcnow() + timedelta(minutes=APPROVAL_TTL_MINUTES),
        )
        state_service.add_approval(approval)
        execution_result = {"approval_id": approval.id, "status": "pending"}

    elif action.get("type") == "assign_swarm" and action.get("swarm_id"):
        cmd = SwarmCommand(
            command_type=CommandType(action.get("command_type", "patrol")),
            target_ids=action.get("target_ids", []),
            objective=action.get("objective", req.command),
            priority=action.get("priority", 5),
            notes=action.get("notes"),
        )
        execution_result = swarm_service.execute_swarm_command(action["swarm_id"], cmd)

    elif action.get("type") == "assign_drone" and action.get("drone_id"):
        cmd = DroneCommand(
            command_type=CommandType(action.get("command_type", "patrol")),
            target_id=action.get("target_ids", [None])[0] if action.get("target_ids") else None,
            objective=action.get("objective", req.command),
            notes=action.get("notes"),
        )
        execution_result = swarm_service.execute_drone_command(action["drone_id"], cmd)

    elif action.get("type") == "no_swarm_in_range":
        # Feature 22: no idle swarm can reach the target — nothing to execute or store
        execution_result = {"no_swarm_in_range": True, "target_id": action.get("target_id")}

    elif action.get("type") == "no_recon_in_range":
        # Feature 24: no recon drone can reach the target — nothing to execute or store
        execution_result = {"no_recon_in_range": True, "target_id": action.get("target_id")}

    elif action.get("type") == "mark_target_destroyed":
        for tid in action.get("target_ids", []):
            state_service.mark_target_destroyed(tid)
        execution_result = {"marked_destroyed": action.get("target_ids", [])}

    # Log the NLP command
    state_service.log_command({
        "type": "nlp_command",
        "raw_command": req.command,
        "interpretation": llm_result.get("interpretation"),
        "action_type": action.get("type"),
        "execution_result": execution_result,
    })

    return {
        "command": req.command,
        "interpretation": llm_result.get("interpretation"),
        "explanation": llm_result.get("explanation"),
        "action": action,
        "execution_result": execution_result,
    }


@router.get("/pending", summary="List pending attack approval requests")
async def get_pending_approvals():
    """Returns all pending HITL attack approvals that have not yet expired."""
    return state_service.get_pending_approvals()


@router.post("/approve/{approval_id}", summary="Approve a pending attack request")
async def approve_attack(approval_id: str):
    """Approves a pending attack request and immediately executes the proposed action."""
    approval = state_service.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval.status}")

    state_service.decide_approval(approval_id, "approved")

    # Execute the proposed action
    proposed = approval.proposed_action
    execution_result = None
    if proposed.get("type") == "disengage":
        # Feature 32: confirmed — release the target and recall the swarm to base.
        result = state_service.disengage_target(proposed.get("target_id"))
        swarm_name = result["swarm_name"] if result else proposed.get("swarm_name", "the combat swarm")
        execution_result = {
            "target_id": proposed.get("target_id"),
            "target_status": "active",
            "swarm_id": result["swarm_id"] if result else proposed.get("swarm_id"),
            "swarm_status": "returning" if result else None,
            "explanation": f"{swarm_name} is returning to base; target is no longer engaged.",
        }

    elif proposed.get("type") == "stop_tracking":
        # Feature 37: confirmed — release the target and recall the recon drone to base.
        result = state_service.stop_tracking_target(proposed.get("target_id"))
        drone_name = result["drone_name"] if result else proposed.get("drone_name", "the reconnaissance drone")
        execution_result = {
            "target_id": proposed.get("target_id"),
            "target_status": "active",
            "drone_id": result["drone_id"] if result else proposed.get("drone_id"),
            "drone_status": "returning" if result else None,
            "explanation": f"{drone_name} is returning to base; target is no longer tracked.",
        }

    elif proposed.get("type") == "assign_swarm" and proposed.get("swarm_id"):
        cmd = SwarmCommand(
            command_type=CommandType(proposed.get("command_type", "attack")),
            target_ids=proposed.get("target_ids", []),
            objective=proposed.get("objective", ""),
            priority=proposed.get("priority", 9),
            notes=proposed.get("notes"),
        )
        execution_result = swarm_service.execute_swarm_command(proposed["swarm_id"], cmd)

    elif proposed.get("type") == "assign_drone" and proposed.get("drone_id"):
        cmd = DroneCommand(
            command_type=CommandType(proposed.get("command_type", "attack")),
            target_id=proposed.get("target_ids", [None])[0] if proposed.get("target_ids") else None,
            objective=proposed.get("objective", ""),
            notes=proposed.get("notes"),
        )
        execution_result = swarm_service.execute_drone_command(proposed["drone_id"], cmd)

    state_service.log_command({
        "type": "hitl_approved",
        "approval_id": approval_id,
        "command": approval.command,
        "execution_result": execution_result,
    })
    return {
        "approved": True,
        "approval_id": approval_id,
        "execution_result": execution_result,
    }


@router.post("/deny/{approval_id}", summary="Deny a pending attack request")
async def deny_attack(approval_id: str):
    """Denies a pending attack request. No action is executed."""
    approval = state_service.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval.status}")

    state_service.decide_approval(approval_id, "denied")
    state_service.log_command({
        "type": "hitl_denied",
        "approval_id": approval_id,
        "command": approval.command,
    })
    return {"denied": True, "approval_id": approval_id}


