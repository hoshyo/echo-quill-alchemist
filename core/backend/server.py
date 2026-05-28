"""Echo-Quill Alchemist — FastAPI + WebSocket server.

Endpoints
---------
POST /trigger_training  body={context, truth}    queues a chunk; returns immediately
POST /infer             body={context, ...}      style-conditioned continuation (post-training use)
GET  /state                                       full snapshot (debug / fallback)
GET  /healthz                                     liveness + queue depth
WS   /ws/alchemist                                push-only stream of WSMessage frames

Run
---
    python core/backend/server.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# core/backend/server.py → core/ → repo root
CORE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CORE_DIR.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# When spawned detached on Windows, file-handle inheritance for stdout/stderr is
# unreliable — start_services.py asks us to redirect ourselves via this env var.
_log_target = os.getenv("ECHO_QUILL_LOG")
if _log_target:
    _log_f = open(_log_target, "a", encoding="utf-8", buffering=1)  # line-buffered
    sys.stdout = _log_f  # type: ignore[assignment]
    sys.stderr = _log_f  # type: ignore[assignment]

from backend.engine import DualTowerJudge, EchoQuillAlchemist, LLMClient  # noqa: E402
from backend.models import (  # noqa: E402
    AlchemistState,
    TrainingRequest,
    TrainingResponse,
    WSMessage,
)

# .env always lives at the repo root (skill level); load it explicitly so we're
# CWD-independent when spawned by scripts/start_services.py.
load_dotenv(REPO_ROOT / ".env")


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
    src = (llm.resolved.get("source") or "none") if hasattr(llm, "resolved") else "none"
    base = (llm.resolved.get("base_url") or "") if hasattr(llm, "resolved") else ""
    masked = (llm.resolved.get("masked_key") or "") if hasattr(llm, "resolved") else ""
    print(
        f"[server] alchemist ready (provider={llm.provider}, creds={src}, "
        f"base={base or '-'}, key={masked or '-'}). "
        "ws=ws://localhost:8000/ws/alchemist"
    )
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
# HTTP — training intake
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


# ---------------------------------------------------------------------------
# HTTP — post-training inference (style-conditioned generation)
# ---------------------------------------------------------------------------

class InferRequest(BaseModel):
    context: str
    top_rules: int = Field(default=5, ge=0, le=20)
    few_shot: int = Field(default=2, ge=0, le=8)
    max_tokens: int = Field(default=600, ge=64, le=4000)
    temperature: float = Field(default=0.85, ge=0.0, le=1.5)


class InferResponse(BaseModel):
    continuation: str
    rules_used: int
    fewshot_used: int


@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest) -> InferResponse:
    """Style-conditioned continuation — uses learned rules + best DPO chosen examples
    as a prompt-time RAG layer over the base LLM. Not a fine-tuned model; the DPO
    pairs in data/dpo.jsonl are the artifact you'd hand to a downstream trainer.
    """
    assert ALCHEMIST is not None
    if not req.context.strip():
        raise HTTPException(status_code=400, detail="context is empty")

    rules_sorted = sorted(
        ALCHEMIST.state.rules,
        key=lambda r: (r.hit_count, r.lifespan),
        reverse=True,
    )
    top_rules = rules_sorted[: req.top_rules]
    rule_block = "\n".join(f"- {r.description}" for r in top_rules) or "（无）"

    dpo_sorted = sorted(
        ALCHEMIST.state.dpo_pairs,
        key=lambda p: p.chosen_score,
        reverse=True,
    )
    fewshot = dpo_sorted[: req.few_shot]
    if fewshot:
        fewshot_block = "\n\n".join(
            f"【示例上文】\n{p.prompt[-300:]}\n【示例续写】\n{p.chosen}" for p in fewshot
        )
    else:
        fewshot_block = "（暂无示例）"

    system = (
        "你是续写引擎。请严格遵守以下从训练语料中习得的风格规则，"
        "并仿照后续示例的语感续写新段落，只输出续写，不要解释、不要标题、不要 Markdown。\n\n"
        f"【风格规则】\n{rule_block}\n\n"
        f"【风格示例】\n{fewshot_block}"
    )
    text = await ALCHEMIST.llm.complete(
        system=system,
        user=f"【上文】\n{req.context}\n\n【续写】",
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    return InferResponse(
        continuation=(text or "").strip(),
        rules_used=len(top_rules),
        fewshot_used=len(fewshot),
    )


# ---------------------------------------------------------------------------
# HTTP — diagnostics
# ---------------------------------------------------------------------------

@app.get("/state", response_model=AlchemistState)
async def get_state() -> AlchemistState:
    assert ALCHEMIST is not None
    return ALCHEMIST.state


@app.get("/healthz")
async def healthz():
    assert ALCHEMIST is not None
    return {
        "ok": True,
        "queued": QUEUE.qsize() if QUEUE else 0,
        "chunks_processed": ALCHEMIST.state.chunks_processed,
        "rules": len(ALCHEMIST.state.rules),
        "dpo_pairs": len(ALCHEMIST.state.dpo_pairs),
        "provider": ALCHEMIST.llm.provider,
    }


# ---------------------------------------------------------------------------
# WebSocket
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
