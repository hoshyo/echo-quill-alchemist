"""Echo-Quill Alchemist — FastAPI + WebSocket server.

Endpoints
---------
POST /trigger_training  body={context, truth}    queues a chunk; returns immediately
GET  /state                                       full snapshot (debug / fallback)
GET  /healthz                                     liveness + queue depth
WS   /ws/alchemist                                push-only stream of WSMessage frames

Run
---
    python backend/server.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# allow `python backend/server.py` (puts repo root on path)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.engine import DualTowerJudge, EchoQuillAlchemist, LLMClient  # noqa: E402
from backend.models import (  # noqa: E402
    AlchemistState,
    TrainingRequest,
    TrainingResponse,
    WSMessage,
)

load_dotenv()


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, msg: WSMessage) -> None:
        text = msg.model_dump_json()
        async with self.lock:
            dead: List[WebSocket] = []
            for ws in list(self.active):
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                if ws in self.active:
                    self.active.remove(ws)


manager = ConnectionManager()
ALCHEMIST: Optional[EchoQuillAlchemist] = None
QUEUE: Optional[asyncio.Queue] = None


# ---------------------------------------------------------------------------
# Lifespan: load model, start worker, hand back over to FastAPI
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ALCHEMIST, QUEUE
    judge = DualTowerJudge()
    llm = LLMClient()
    ALCHEMIST = EchoQuillAlchemist(judge=judge, llm=llm, broadcaster=manager.broadcast)
    QUEUE = asyncio.Queue()
    worker = asyncio.create_task(_worker())
    print(f"[server] alchemist ready ({llm.provider}). ws=ws://localhost:8000/ws/alchemist")
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        await llm.aclose()


app = FastAPI(title="Echo-Quill Alchemist", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _worker() -> None:
    assert QUEUE is not None and ALCHEMIST is not None
    while True:
        req: TrainingRequest = await QUEUE.get()
        try:
            await ALCHEMIST.process_chunk(req)
        except Exception as e:
            await manager.broadcast(WSMessage(type="log", payload={"line": f"[FATAL] {e!r}"}))
        finally:
            QUEUE.task_done()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

@app.post("/trigger_training", response_model=TrainingResponse)
async def trigger_training(req: TrainingRequest) -> TrainingResponse:
    assert QUEUE is not None and ALCHEMIST is not None
    await QUEUE.put(req)
    return TrainingResponse(
        accepted=True,
        chunk_index=ALCHEMIST.state.chunks_processed + QUEUE.qsize(),
        note=f"queued (qsize={QUEUE.qsize()})",
    )


@app.get("/state", response_model=AlchemistState)
async def get_state() -> AlchemistState:
    assert ALCHEMIST is not None
    return ALCHEMIST.state


@app.get("/healthz")
async def healthz():
    return {"ok": True, "queued": QUEUE.qsize() if QUEUE else 0}


# ---------------------------------------------------------------------------
# WebSocket (push-only — client→server msgs are ignored, kept open for ping/pong)
# ---------------------------------------------------------------------------

@app.websocket("/ws/alchemist")
async def ws_alchemist(ws: WebSocket):
    assert ALCHEMIST is not None
    await manager.connect(ws)
    snap = WSMessage(type="snapshot", payload=ALCHEMIST.state.model_dump(mode="json"))
    try:
        await ws.send_text(snap.model_dump_json())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.server:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
