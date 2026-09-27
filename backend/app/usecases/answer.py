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


@dataclass(frozen=True)
class RetrievalOutcome:
    """Result of the pre-LLM stages of the pipeline (intent -> evidence filter).

    Lets callers stop *before* generation: the answer use case streams an answer
    from ``evidence``, while the offline eval harness measures retrieval quality
    against ``reranked`` / ``evidence`` without paying for any answer tokens. The
    intermediate stages are exposed so retrieval metrics can inspect each one.
    """

    # Greeting / chit-chat: answer directly, no retrieval happened.
    direct_response: str | None
    # False only for clearly out-of-scope questions (early refusal).
    in_scope: bool
    search_queries: list[str]
    candidates: list[ScoredChunk]  # merged hybrid retrieval, pre-rerank
    reranked: list[ScoredChunk]  # post-rerank, pre-threshold
    evidence: list[ScoredChunk]  # post-threshold; what the LLM would receive


@dataclass(frozen=True)
class GenerationOutcome:
    """Non-streaming result of the full pipeline, for the eval harness.

    ``answer`` is the user-facing text the streaming pipeline would have produced
    (a greeting / out-of-scope / refusal message, or the grounded answer).
    ``evidence`` carries the FULL chunk text fed to the LLM (faithfulness /
    context metrics need it, not the truncated citation snippet).
    """

    # "greeting" | "out_of_scope" | "refused_no_evidence" | "answered"
    status: str
    answer: str
    evidence: list[ScoredChunk]
    guardrail_allowed: bool | None = None

    @property
    def refused(self) -> bool:
        """True when the system declined to answer from the manual."""
        return self.status in ("out_of_scope", "refused_no_evidence")


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

    async def retrieve(
        self,
        question: str,
        *,
        history: Sequence[ChatTurn] = (),
        category: str | None = None,
        department: str | None = None,
    ) -> RetrievalOutcome:
        """Run intent routing -> analyze -> retrieve -> rerank -> evidence filter
        and stop *before* the answer LLM. Returns every intermediate stage.

        ``execute`` calls this and then streams an answer; the eval harness calls
        it directly to measure retrieval quality without spending answer tokens.
        Keeping the logic here (not duplicated in eval) guarantees the harness
        scores the exact pipeline production runs.
        """
        log = logging.getLogger("ods.answer")

        # 0. Input routing: greetings / chit-chat answer directly (no RAG),
        # which avoids a false "ไม่พบข้อมูล" refusal on a friendly hello.
        intent = await self._intent.classify(question, history)
        if intent.direct_response is not None:
            log.info("intent=%s; skipping retrieval", intent.kind)
            return RetrievalOutcome(
                direct_response=intent.direct_response,
                in_scope=True,
                search_queries=[],
                candidates=[],
                reranked=[],
                evidence=[],
            )

        # 1. Cheap pre-retrieval: analyze intent — scope check, reformulation,
        # and decomposition of compound questions.
        analysis = await self._analyzer.analyze(question, history)
        if not analysis.in_scope:
            log.info("out_of_scope reason=%r", analysis.reason)
            return RetrievalOutcome(
                direct_response=None,
                in_scope=False,
                search_queries=[],
                candidates=[],
                reranked=[],
                evidence=[],
            )

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
        reranked = sorted(best_rerank.values(), key=lambda s: s.score, reverse=True)[
            : self._cfg.rerank_top_k
        ]
        evidence = [c for c in reranked if c.score >= self._cfg.score_threshold]
        log.info(
            "candidates=%d reranked_scores=%s threshold=%.2f evidence=%d",
            len(candidates),
            [round(c.score, 4) for c in reranked],
            self._cfg.score_threshold,
            len(evidence),
        )
        return RetrievalOutcome(
            direct_response=None,
            in_scope=True,
            search_queries=search_queries,
            candidates=candidates,
            reranked=reranked,
            evidence=evidence,
        )

    async def generate(
        self,
        question: str,
        *,
        history: Sequence[ChatTurn] = (),
        category: str | None = None,
        department: str | None = None,
    ) -> GenerationOutcome:
        """Run the full pipeline and collect the answer (non-streaming).

        Same stages and safety gates as ``execute`` — it shares ``retrieve`` and
        applies the identical greeting / out-of-scope / no-evidence rules and the
        output guardrail — but returns the assembled answer + full evidence for
        offline scoring instead of streaming SSE events.
        """
        outcome = await self.retrieve(
            question, history=history, category=category, department=department
        )
        if outcome.direct_response is not None:
            return GenerationOutcome(
                status="greeting", answer=outcome.direct_response, evidence=[]
            )
        if not outcome.in_scope:
            return GenerationOutcome(
                status="out_of_scope", answer=OUT_OF_SCOPE_TEXT, evidence=[]
            )
        if not outcome.evidence:
            return GenerationOutcome(
                status="refused_no_evidence", answer=REFUSAL_TEXT, evidence=[]
            )

        citations = [Citation.from_scored(c) for c in outcome.evidence]
        collected: list[str] = []
        async for token in self._llm.stream(
            question=question, contexts=outcome.evidence, history=history
        ):
            collected.append(token)
        answer = "".join(collected)
        verdict = self._guardrail.validate(answer, citations)
        return GenerationOutcome(
            status="answered",
            answer=answer,
            evidence=list(outcome.evidence),
            guardrail_allowed=verdict.allowed,
        )

    async def execute(
        self,
        question: str,
        *,
        history: Sequence[ChatTurn] = (),
        category: str | None = None,
        department: str | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        outcome = await self.retrieve(
            question, history=history, category=category, department=department
        )

        # Greeting / chit-chat short-circuit (no RAG).
        if outcome.direct_response is not None:
            yield TokenEvent(outcome.direct_response)
            return

        # Clearly out-of-scope question -> early refusal.
        if not outcome.in_scope:
            yield TokenEvent(OUT_OF_SCOPE_TEXT)
            return

        # Safety rule §5.1: no evidence -> refuse, do not hallucinate.
        if not outcome.evidence:
            yield TokenEvent(REFUSAL_TEXT)
            return

        citations = [Citation.from_scored(c) for c in outcome.evidence]

        # 4. Stream the grounded answer.
        collected: list[str] = []
        async for token in self._llm.stream(
            question=question, contexts=outcome.evidence, history=history
        ):
            collected.append(token)
            yield TokenEvent(token)

        # 5. Output guardrail (§5): must cite; never diagnose.
        verdict = self._guardrail.validate("".join(collected), citations)
        if verdict.allowed:
            yield CitationsEvent(citations)
        else:
            yield TokenEvent("\n\n" + SAFETY_NOTICE)
