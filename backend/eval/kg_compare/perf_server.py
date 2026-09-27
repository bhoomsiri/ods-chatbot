"""Twin-endpoint perf server for the JMeter Vector-vs-KG comparison (spec §8).

Two SSE endpoints that differ ONLY in the retriever; the generator (Gemini
answer model + safety prompt + SSE framing) is identical, so any latency gap is
attributable to retrieval, not to a better-written endpoint (§6.5 fairness).

  POST /vec/chat  → Qdrant subset retrieval (SubsetVectorStore, reused)
  POST /kg/chat   → LightRAG mix retrieval  (LightRAG, reused)
  POST /pc/chat   → Hierarchical parent-child retrieval (PCRetriever, reused)

Both stream ``{"type":"token"}`` … ``{"type":"done"}`` exactly like the app's
/api/chat, so the existing JMeter assertion and CSV work unchanged.

Does NOT edit backend/app (imports it read-only), does NOT touch history/postgres,
and binds a DEDICATED port (8100) so it never collides with the production backend
(8000) and can be killed without affecting it.

Run inside the backend container:
    docker compose exec -d backend python -m eval.kg_compare.perf_server
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.settings import get_settings
from app.domain.entities import Chunk, ScoredChunk
from app.infrastructure.gemini_llm import GeminiAnswerLLM
from eval.config import ExperimentConfig
from eval.kg_compare.lightrag_retriever import make_rag
from eval.kg_compare.pc_retriever import PCRetriever
from eval.kg_compare.subset_store import SubsetVectorStore
from eval.pipeline import build_retriever

log = logging.getLogger("kg.perf")
PORT = 8100
app = FastAPI(title="KG-compare perf twin")

_state: dict[str, Any] = {}


class ChatBody(BaseModel):
    message: str
    history: list[Any] = []


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.on_event("startup")
async def _startup() -> None:
    import json as _json
    from pathlib import Path

    s = get_settings()
    conf = _json.loads(
        (Path(__file__).resolve().parent / "subset_config.json").read_text("utf-8")
    )
    sources = conf["qdrant"]["subset_sources"]
    collection = conf["qdrant"]["collection"]

    # Vector side: the production retrieval pipeline restricted to the subset.
    cfg = ExperimentConfig(name="perf_vec", collection=collection)
    vec = build_retriever(cfg, allow_llm=False)
    vec._store = SubsetVectorStore(  # noqa: SLF001 - deliberate injection
        sources=sources,
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        collection=collection,
        dense_size=s.embedding_dim,
    )
    _state["vec"] = vec

    # KG side: the pre-built graph (context retrieval only).
    _state["rag"] = await make_rag(
        working_dir=str(
            Path(__file__).resolve().parent.parent / "runs" / "kg_compare" / "kg_store"
        ),
        api_key=s.gemini_api_key,
    )

    # Hierarchical side: the parent-child index (retrieval only; shares generator).
    _state["pc"] = PCRetriever(api_key=s.gemini_api_key)

    # Shared generator — SAME model/prompt for all endpoints.
    _state["llm"] = GeminiAnswerLLM(
        api_key=s.gemini_api_key, model="gemini-2.5-flash", temperature=0.1
    )
    log.info("perf server ready on :%d", PORT)


async def _vec_contexts(message: str) -> list[ScoredChunk]:
    outcome = await _state["vec"].retrieve(message)
    return list(outcome.evidence)


async def _kg_contexts(message: str) -> list[ScoredChunk]:
    from lightrag import QueryParam

    ctx = await _state["rag"].aquery(
        message, param=QueryParam(mode="mix", only_need_context=True, enable_rerank=False)
    )
    text = ctx if isinstance(ctx, str) else str(ctx)
    if not text.strip():
        return []
    # Wrap the graph-retrieved context as a single context block so the shared
    # generator formats + streams it identically to the vector evidence.
    return [
        ScoredChunk(
            chunk=Chunk(
                id="kg",
                text=text,
                source="knowledge-graph",
                page=None,
                category=None,
                department=None,
                image=None,
            ),
            score=1.0,
        )
    ]


async def _stream(message: str, contexts: list[ScoredChunk]) -> AsyncIterator[str]:
    parts: list[str] = []
    try:
        async for tok in _state["llm"].stream(question=message, contexts=contexts):
            parts.append(tok)
            yield _sse({"type": "token", "text": tok})
        yield _sse({"type": "done"})
    except Exception as exc:  # noqa: BLE001
        log.exception("generation failed")
        yield _sse({"type": "error", "detail": str(exc)[:120]})


@app.post("/vec/chat")
async def vec_chat(body: ChatBody) -> StreamingResponse:
    contexts = await _vec_contexts(body.message)
    return StreamingResponse(
        _stream(body.message, contexts),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/kg/chat")
async def kg_chat(body: ChatBody) -> StreamingResponse:
    contexts = await _kg_contexts(body.message)
    return StreamingResponse(
        _stream(body.message, contexts),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _pc_contexts(message: str) -> list[ScoredChunk]:
    return _state["pc"].retrieve(message)


@app.post("/pc/chat")
async def pc_chat(body: ChatBody) -> StreamingResponse:
    contexts = await _pc_contexts(body.message)
    return StreamingResponse(
        _stream(body.message, contexts),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "ready": str("llm" in _state)}


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
