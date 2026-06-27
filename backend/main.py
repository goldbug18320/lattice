"""Lattice – AI-Enabled Drone Swarm Command & Control Platform"""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api.recon import router as recon_router
from api.swarm import router as swarm_router
from api.nlp import router as nlp_router
from api.assets import router as assets_router
from services.state_service import state_service
from services.movement_service import movement_service


# ─── WebSocket Connection Manager ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


# ─── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background state broadcaster
    task = asyncio.create_task(broadcast_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def broadcast_loop():
    """Ticks movement simulation and broadcasts full battlefield state every second."""
    while True:
        await asyncio.sleep(1)
        movement_service.tick(state_service)
        state_service.expire_approvals()
        if manager.active:
            state = state_service.get_full_state()
            await manager.broadcast(json.dumps(state, default=str))


app = FastAPI(
    title="Lattice C2",
    description="AI-Enabled Drone Swarm Command & Control Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recon_router, prefix="/api/recon", tags=["Reconnaissance"])
app.include_router(swarm_router, prefix="/api/swarm", tags=["Swarm Control"])
app.include_router(nlp_router, prefix="/api/nlp", tags=["NLP Commands"])
app.include_router(assets_router, prefix="/api/assets", tags=["Asset Management"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial state immediately on connect
        state = state_service.get_full_state()
        await websocket.send_text(json.dumps(state, default=str))
        # Keep connection alive, receiving any client messages
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/")
async def root():
    return {
        "platform": "Lattice C2",
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs",
    }


@app.get("/api/state", summary="Get full battlefield state snapshot")
async def get_state():
    return state_service.get_full_state()
