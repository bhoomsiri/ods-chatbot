"""PCRetriever — Hierarchical (Parent-Child) answer path over the subset index.

Answers a question with the SAME production parts the Vector RAG uses (bge-m3
embedder, bge-reranker-v2-m3, evidence threshold 0.3, gemini-2.5-flash + the app
safety prompt, guardrail) — only the retrieval STRUCTURE differs: search small
children, answer from their large parents. This keeps the 3-way comparison fair
(only the index architecture varies).

Retrieval: embed query (bge-m3 dense) → cosine over child vectors → map children
back to parents → dedup → rerank parents (bge-reranker) → keep score ≥ 0.3. No
evidence → the standard refusal, exactly like the Vector RAG's threshold gate.

Returns the SAME schema as ``LightRagRetriever`` (GraphAnswer) so Phase 3 scores
all three methods identically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.providers import get_embedder, get_guardrail, get_reranker
from app.domain.entities import REFUSAL_TEXT, Chunk, Citation, ScoredChunk
from app.infrastructure.gemini_llm import GeminiAnswerLLM

HERE = Path(__file__).resolve().parent
INDEX_DIR = HERE.parent / "runs" / "kg_compare" / "hierarchical"

# Fairness-locked to the Vector RAG's knobs (subset_config.json).
CHILD_TOP_K = 40  # children pulled before mapping to parents
RERANK_CANDIDATES = 20  # unique parents fed to the reranker (= vector rerank_candidates)
RERANK_TOP_K = 8  # survivors to the evidence filter (= vector rerank_top_k)
THRESHOLD = 0.3  # evidence-filter cutoff (= vector score_threshold)


@dataclass
class GraphAnswer:  # same shape as lightrag_retriever.GraphAnswer (Phase-3 schema)
    status: str
    answer: str
    context: str
    refused: bool
    n_context_chars: int
    error: str | None = None


def _l2norm(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.clip(n, 1e-12, None)


class PCRetriever:
    """Hierarchical retriever: child search → parent answer."""

    def __init__(
        self,
        *,
        api_key: str,
        index_dir: Path = INDEX_DIR,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.1,
    ) -> None:
        data = json.loads((index_dir / "pc_index.json").read_text(encoding="utf-8"))
        self._children: list[dict[str, str]] = data["children"]
        self._parents: dict[str, dict[str, object]] = data["parents"]
        self._child_vecs = _l2norm(
            np.load(index_dir / "pc_index.npz")["child_vecs"].astype(np.float32)
        )
        self._embedder = get_embedder()
        self._reranker = get_reranker()
        self._guardrail = get_guardrail()
        self._llm = GeminiAnswerLLM(api_key=api_key, model=model, temperature=temperature)

    def _candidate_parents(self, question: str) -> list[ScoredChunk]:
        q = np.asarray(self._embedder.embed_query(question).dense, dtype=np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-12)
        sims = self._child_vecs @ q
        top = np.argsort(-sims)[:CHILD_TOP_K]
        seen: dict[str, float] = {}
        order: list[str] = []
        for i in top:
            pid = self._children[int(i)]["parent_id"]
            if pid not in seen:
                seen[pid] = float(sims[int(i)])
                order.append(pid)
            if len(order) >= RERANK_CANDIDATES:
                break
        cands: list[ScoredChunk] = []
        for pid in order:
            p = self._parents[pid]
            cands.append(
                ScoredChunk(
                    chunk=Chunk(
                        id=pid,
                        text=str(p["text"]),
                        source=str(p["source"]),
                        page=p.get("page"),  # type: ignore[arg-type]
                    ),
                    score=seen[pid],
                )
            )
        return cands

    def retrieve(self, question: str) -> list[ScoredChunk]:
        """Retrieval only: child search → parent → rerank → evidence@0.3.

        Shared by ``generate`` and the perf server's ``/pc/chat`` so both measure
        the identical retrieval path.
        """
        cands = self._candidate_parents(question)
        reranked = (
            self._reranker.rerank(question, cands, top_k=RERANK_TOP_K) if cands else []
        )
        return [c for c in reranked if c.score >= THRESHOLD]

    async def generate(self, question: str) -> GraphAnswer:
        try:
            evidence = self.retrieve(question)
            if not evidence:
                return GraphAnswer(
                    status="refused_no_evidence",
                    answer=REFUSAL_TEXT,
                    context="",
                    refused=True,
                    n_context_chars=0,
                )
            parts: list[str] = []
            async for tok in self._llm.stream(question=question, contexts=evidence):
                parts.append(tok)
            answer = "".join(parts).strip()
            citations = [Citation.from_scored(c) for c in evidence]
            _ = self._guardrail.validate(answer, citations)  # same guardrail as prod
            context = "\n\n".join(c.chunk.text for c in evidence)
            refused = not answer or "ไม่พบข้อมูล" in answer
            return GraphAnswer(
                status="refused_no_evidence" if refused else "answered",
                answer=answer,
                context=context[:8000],
                refused=refused,
                n_context_chars=len(context),
            )
        except Exception as exc:  # noqa: BLE001 - record, don't abort the sweep
            return GraphAnswer(
                status="error",
                answer="",
                context="",
                refused=False,
                n_context_chars=0,
                error=str(exc)[:200],
            )
