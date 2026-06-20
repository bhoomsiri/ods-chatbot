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

        # 3. Rerank + evidence filter (score threshold). Only the best
        # rerank_candidates by RRF order go through the cross-encoder.
        reranked = self._reranker.rerank(
            analysis.reformulated,
            candidates[: self._cfg.rerank_candidates],
            top_k=self._cfg.rerank_top_k,
        )
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
