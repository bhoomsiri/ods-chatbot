"""LightRagRetriever — GraphRAG answer path over the pre-built subset graph.

Opens the graph built by ``build_kg`` (read-only: no insert) and answers a
question with LightRAG's ``mix`` mode (KG entities/relations + vector chunks —
LightRAG's strongest mode, giving GraphRAG its best chance, §6.5). To keep the
comparison fair it is handed the SAME guardrail intent the vector RAG's system
prompt encodes (answer only from context; refuse if absent; concise Thai) via
``user_prompt`` — so GraphRAG isn't penalised for its default verbose prompt,
and any failure to refuse on out-of-subset questions is a real architectural
result, not a prompt artefact.

Same answer model (gemini-2.5-flash) + embeddings (bge-m3) as the vector RAG.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Mirrors the vector RAG's answer system prompt intent (app safety §5), passed as
# LightRAG user_prompt so both systems get the same "grounded / refuse / concise
# Thai / no inline citations" contract.
SAFETY_USER_PROMPT = (
    "ตอบโดยใช้ข้อมูลจากบริบทที่ให้มาเท่านั้น ห้ามแต่งเติมข้อมูลนอกเหนือจากนี้ "
    "หากบริบทไม่มีข้อมูลที่ตอบคำถามได้ ให้ตอบว่า "
    "'ไม่พบข้อมูลในคู่มือ กรุณาสอบถามเจ้าหน้าที่' เท่านั้น "
    "ห้ามวินิจฉัยโรคหรือสั่งจ่ายยา ตอบเป็นภาษาไทย กระชับ ชัดเจน "
    "ห้ามใส่ชื่อแหล่งที่มาหรือเลขหน้าในคำตอบ"
)

_REFUSAL_MARKERS = (
    "ไม่พบข้อมูล",
    "ไม่มีข้อมูล",
    "unable to provide",
    "cannot provide",
    "no relevant",
    "[no-context]",
)


@dataclass
class GraphAnswer:
    status: str  # "answered" | "refused_no_evidence" | "error"
    answer: str
    context: str
    refused: bool
    n_context_chars: int
    error: str | None = None


async def make_rag(*, working_dir: str, api_key: str) -> Any:
    """Open the pre-built LightRAG graph for querying (no insert)."""
    from lightrag import LightRAG
    from lightrag.kg.shared_storage import initialize_pipeline_status
    from lightrag.utils import EmbeddingFunc

    from eval.kg_compare.kg_llm import (
        make_bge_embedding_func,
        make_gemini_llm_func,
    )

    llm_func, _ = make_gemini_llm_func(
        api_key=api_key, model="gemini-2.5-flash", temperature=0.1
    )
    embed_func, _ = make_bge_embedding_func(use_fp16=True)
    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_func,
        llm_model_name="gemini-2.5-flash",
        embedding_func=EmbeddingFunc(
            embedding_dim=1024, max_token_size=8192, func=embed_func
        ),
        addon_params={"language": "Thai"},
        embedding_func_max_async=2,
        llm_model_max_async=4,
    )
    await rag.initialize_storages()
    await initialize_pipeline_status()
    return rag


class LightRagRetriever:
    """Answers a question from the subset knowledge graph (mix mode)."""

    def __init__(self, rag: Any, *, mode: str = "mix") -> None:
        self._rag = rag
        self._mode = mode

    async def generate(self, question: str) -> GraphAnswer:
        from lightrag import QueryParam

        try:
            ctx = await self._rag.aquery(
                question,
                param=QueryParam(
                    mode=self._mode, only_need_context=True, enable_rerank=False
                ),
            )
            context = ctx if isinstance(ctx, str) else str(ctx)
            answer = await self._rag.aquery(
                question,
                param=QueryParam(
                    mode=self._mode,
                    enable_rerank=False,
                    user_prompt=SAFETY_USER_PROMPT,
                ),
            )
            answer = answer if isinstance(answer, str) else str(answer)
        except Exception as exc:  # noqa: BLE001 - record, don't abort the sweep
            return GraphAnswer(
                status="error",
                answer="",
                context="",
                refused=False,
                n_context_chars=0,
                error=str(exc)[:200],
            )

        low = answer.lower()
        refused = (not answer.strip()) or any(m.lower() in low for m in _REFUSAL_MARKERS)
        return GraphAnswer(
            status="refused_no_evidence" if refused else "answered",
            answer=answer,
            context=context[:8000],
            refused=refused,
            n_context_chars=len(context),
        )
