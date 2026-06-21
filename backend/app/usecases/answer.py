"""AnswerQuestion use case — orchestrates the online RAG query pipeline.

Depends only on ports (domain abstractions), never on infrastructure.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from app.domain.entities import (
    OUT_OF_SCOPE_TEXT,
    REFUSAL_TEXT,
    SAFETY_NOTICE,
    AnswerEvent,
    ChatTurn,
    Citation,
    CitationsEvent,
    ScoredChunk,
    TokenEvent,
)
from app.domain.ports import (
    AnswerLLM,
    Embedder,
    Guardrail,
    IntentClassifier,
    QueryAnalyzer,
    Reranker,
    VectorStore,
)


# ODS boilerplate phrases. When present in a rerank query they bias the
# cross-encoder toward generic "ODS overview" documents and away from
# procedure-specific ones (a Tympanoplasty consent scores ~0.9 against the bare
# procedure name but ~0.1 against "...แบบ ODS ได้ไหม"). We add a stripped,
# procedure-focused variant of each query as an extra rerank lens. This only
# affects reranking — retrieval already surfaces the procedure document.
_ODS_BOILERPLATE = (
    "ในระบบการผ่าตัดแบบวันเดียวกลับ",
    "การผ่าตัดแบบวันเดียวกลับ",
    "แบบวันเดียวกลับ",
    "วันเดียวกลับ",
    "ของโรงพยาบาลโพธาราม",
    "โรงพยาบาลโพธาราม",
    "One-Day Surgery",
    "One Day Surgery",
    "(ODS)",
    "ODS",
    "ได้หรือไม่",
    "ได้ไหม",
    "ได้มั้ย",
)


def _procedure_focus(query: str) -> str:
    """Strip ODS boilerplate, leaving the procedure/topic terms for reranking."""
    out = query
    for phrase in _ODS_BOILERPLATE:
        out = out.replace(phrase, " ")
    return " ".join(out.split())


@dataclass(frozen=True)
class RetrievalConfig:
    retrieval_top_k: int = 20
    # How many of the retrieved candidates to feed the (expensive) cross-encoder
    # reranker. Hybrid RRF already orders well, so reranking the best N instead
    # of all retrieved keeps top-5 identical while cutting CPU rerank latency.
    rerank_candidates: int = 12
    rerank_top_k: int = 5
    score_threshold: float = 0.3


class AnswerQuestion:
    def __init__(
        self,
        *,
        intent_classifier: IntentClassifier,
        analyzer: QueryAnalyzer,
        embedder: Embedder,
        store: VectorStore,
        reranker: Reranker,
        llm: AnswerLLM,
        guardrail: Guardrail,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._intent = intent_classifier
        self._analyzer = analyzer
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._llm = llm
        self._guardrail = guardrail
        self._cfg = config or RetrievalConfig()

    async def execute(
        self,
        question: str,
        *,
        history: Sequence[ChatTurn] = (),
        category: str | None = None,
        department: str | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        log = logging.getLogger("ods.answer")

        # 0. Input routing: greetings / chit-chat answer directly (no RAG),
        # which avoids a false "ไม่พบข้อมูล" refusal on a friendly hello.
        intent = await self._intent.classify(question, history)
        if intent.direct_response is not None:
            log.info("intent=%s; skipping retrieval", intent.kind)
            yield TokenEvent(intent.direct_response)
            return

        # 1. Cheap pre-retrieval: analyze intent — scope check, reformulation,
        # and decomposition of compound questions.
        analysis = await self._analyzer.analyze(question, history)
        if not analysis.in_scope:
            log.info("out_of_scope reason=%r", analysis.reason)
            yield TokenEvent(OUT_OF_SCOPE_TEXT)
            return

        # Middle path: retrieve with the RAW question as well as the reformulated
        # / decomposed queries, then merge. This keeps the benefits of
        # reformulation (context resolution, doc-style wording, decomposition)
        # while guaranteeing a mis-reformulation can never drop the user's
        # literal intent. Dedup exact duplicates (raw == reformulated is common).
        search_queries = list(dict.fromkeys([question, *analysis.queries()]))
        log.info(
            "raw=%r search_queries=%r category=%r department=%r",
            question,
            search_queries,
            category,
            department,
        )

        # 2. Hybrid retrieval (dense + sparse, RRF) per query, with category
        # filter. Merge candidates across queries, keeping each chunk's best
        # score, so both the raw and reformulated phrasings contribute evidence.
        merged: dict[str, ScoredChunk] = {}
        for q in search_queries:
            query_embedding = self._embedder.embed_query(q)
            for sc in self._store.hybrid_search(
                query_embedding,
                category=category,
                department=department,
                top_k=self._cfg.retrieval_top_k,
            ):
                best = merged.get(sc.chunk.id)
                if best is None or sc.score > best.score:
                    merged[sc.chunk.id] = sc
        candidates = sorted(merged.values(), key=lambda s: s.score, reverse=True)

        # 3. Rerank + evidence filter (score threshold). Rerank the candidate
        # pool against EACH search query and keep every chunk's best score
        # across queries. A single ODS-themed reformulation reranked alone lets
        # generic "ODS overview" docs crowd out a procedure-specific document
        # (e.g. the Tympanoplasty consent form scores ~0.9 against the bare
        # procedure name but ~0.1 against "...แบบ ODS ได้ไหม"). Per-query max
        # rescues that procedure evidence while keeping the ODS context too.
        pool = candidates[: self._cfg.rerank_candidates]
        rerank_queries = list(
            dict.fromkeys(
                [*search_queries, *(_procedure_focus(q) for q in search_queries)]
            )
        )
        rerank_queries = [q for q in rerank_queries if len(q) >= 4]
        best_rerank: dict[str, ScoredChunk] = {}
        for q in rerank_queries:
            for sc in self._reranker.rerank(q, pool, top_k=self._cfg.rerank_top_k):
                cur = best_rerank.get(sc.chunk.id)
                if cur is None or sc.score > cur.score:
                    best_rerank[sc.chunk.id] = sc
        reranked = sorted(
            best_rerank.values(), key=lambda s: s.score, reverse=True
        )[: self._cfg.rerank_top_k]
        evidence = [c for c in reranked if c.score >= self._cfg.score_threshold]
        log.info(
            "candidates=%d reranked_scores=%s threshold=%.2f evidence=%d",
            len(candidates),
            [round(c.score, 4) for c in reranked],
            self._cfg.score_threshold,
            len(evidence),
        )

        # Safety rule §5.1: no evidence -> refuse, do not hallucinate.
        if not evidence:
            yield TokenEvent(REFUSAL_TEXT)
            return

        citations = [Citation.from_scored(c) for c in evidence]

        # 4. Stream the grounded answer.
        collected: list[str] = []
        async for token in self._llm.stream(
            question=question, contexts=evidence, history=history
        ):
            collected.append(token)
            yield TokenEvent(token)

        # 5. Output guardrail (§5): must cite; never diagnose.
        verdict = self._guardrail.validate("".join(collected), citations)
        if verdict.allowed:
            yield CitationsEvent(citations)
        else:
            yield TokenEvent("\n\n" + SAFETY_NOTICE)
