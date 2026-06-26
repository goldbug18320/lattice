"""Reconnaissance feed API endpoints."""
from fastapi import APIRouter, HTTPException
from models.target import ReconFeed, Target, TargetReport, TargetStatus
from models.drone import DroneStatus
from services.state_service import state_service

router = APIRouter()


@router.post("/feed", summary="Submit reconnaissance data from a drone")
async def submit_recon_feed(feed: ReconFeed):
    """
    Endpoint called by reconnaissance drones to report enemy target locations.
    Creates new targets or updates existing ones.
    """
    created = 0
    updated = 0

    for report in feed.targets:
        if report.existing_target_id and state_service.get_target(report.existing_target_id):
            # Update existing target
            existing = state_service.get_target(report.existing_target_id)
            existing.position = report.position
            existing.heading = report.heading
            existing.speed = report.speed
            existing.confidence = report.confidence
            existing.reported_by = feed.recon_drone_id
            if report.notes:
                existing.notes = report.notes
            state_service.upsert_target(existing)
            updated += 1
        else:
            # Create new target
            target = Target(
                type=report.type,
                position=report.position,
                heading=report.heading,
                speed=report.speed,
                confidence=report.confidence,
                reported_by=feed.recon_drone_id,
                notes=report.notes,
            )
            state_service.upsert_target(target)
            created += 1

    # Update recon drone position if known
    recon_drone = next(
        (d for d in state_service.get_all_drones() if d.name == feed.recon_drone_id or d.id == feed.recon_drone_id),
        None
    )
    if recon_drone:
        state_service.update_drone(recon_drone.id, {"status": DroneStatus.PATROLLING})

    return {"received": len(feed.targets), "created": created, "updated": updated}


@router.get("/targets", summary="Get all active enemy targets")
async def get_targets(
    type: str | None = None,
    status: str | None = None,
    min_confidence: float = 0.0,
):
    """Returns all tracked enemy targets, optionally filtered."""
    targets = state_service.get_all_targets()
    if type:
        targets = [t for t in targets if t.type.value == type]
    if status:
        targets = [t for t in targets if t.status.value == status]
    targets = [t for t in targets if t.confidence >= min_confidence]
    return targets


@router.get("/targets/{target_id}", summary="Get a specific target")
async def get_target(target_id: str):
    target = state_service.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    return target


@router.patch("/targets/{target_id}/status", summary="Update target status")
async def update_target_status(target_id: str, status: TargetStatus):
    target = state_service.get_target(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    target.status = status
    state_service.upsert_target(target)
    return target


@router.delete("/targets/{target_id}", summary="Remove a target")
async def remove_target(target_id: str):
    if not state_service.remove_target(target_id):
        raise HTTPException(status_code=404, detail="Target not found")
    return {"removed": target_id}
