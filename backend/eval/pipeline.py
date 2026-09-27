"""Assemble an ``AnswerQuestion`` from the production adapters with per-run knob
overrides — without editing ``.env`` or mutating the settings singleton.

Phase 1 (retrieval) builds a retriever that uses the real embedder, vector store
and reranker but a *passthrough* analyzer (no reformulation LLM) and a guard LLM
that refuses to run — so a retrieval eval can never spend answer tokens and is
fully deterministic. ``allow_llm=True`` (phase 2) wires the real analyzer/LLM.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.core.providers import (
    get_embedder,
    get_guardrail,
    get_intent_classifier,
    get_llm,
    get_reranker,
    get_store,
)
from app.core.settings import get_settings
from app.domain.entities import ChatTurn, ScoredChunk
from app.domain.ports import AnswerLLM, QueryAnalyzer, VectorStore
from app.infrastructure.fakes import FakeQueryAnalyzer
from app.usecases.answer import AnswerQuestion, RetrievalConfig
from eval.config import ExperimentConfig
from eval.metrics.llm_judge import FakeJudge, GeminiJudge, Judge

# Fixed judge model for ALL configs, so the E8 answer-model comparison is never
# graded by the model under test.
JUDGE_MODEL = "gemini-2.5-flash"


class _UnusedLLM:
    """An ``AnswerLLM`` that refuses to run.

    Injected for retrieval-only runs so any accidental call to generation fails
    loudly instead of silently spending tokens.
    """

    def stream(
        self,
        *,
        question: str,
        contexts: Sequence[ScoredChunk],
        history: Sequence[ChatTurn] = (),
    ) -> AsyncIterator[str]:
        raise RuntimeError("retrieval-only eval must not call the answer LLM")


def build_store(collection: str) -> VectorStore:
    """Reuse the cached production store when the collection matches settings;
    otherwise build a read-only Qdrant store bound to ``collection`` (phase 3
    index sweeps). In fake mode the in-memory store is returned regardless."""
    s = get_settings()
    if s.use_fakes or collection == s.qdrant_collection:
        return get_store()
    from app.infrastructure.qdrant_store import QdrantVectorStore

    return QdrantVectorStore(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        collection=collection,
        dense_size=s.embedding_dim,
    )


def build_answer_llm(cfg: ExperimentConfig) -> AnswerLLM:
    """Real answer LLM bound to THIS config's model + temperature (for E8/E9).

    In fake mode the echo LLM is used so a generation smoke runs without a key.
    """
    s = get_settings()
    if s.use_fakes:
        return get_llm()
    from app.infrastructure.gemini_llm import GeminiAnswerLLM

    api_key = s.gemini_api_key
    if not api_key:
        raise RuntimeError("ODS_GEMINI_API_KEY required for generation eval")
    return GeminiAnswerLLM(
        api_key=api_key,
        model=cfg.query.answer_model,
        temperature=cfg.query.temperature,
    )


def build_query_analyzer(cfg: ExperimentConfig) -> QueryAnalyzer:
    """Real query analyzer bound to THIS config's reformulate model (for E10).

    Mirrors ``build_answer_llm``: the model is taken from the config knob, not the
    ``ODS_GEMINI_REFORMULATE_MODEL`` env, so E10 can swap Flash-Lite for Flash
    without touching ``.env``. In fake mode the passthrough analyzer is returned
    so a generation smoke runs without a key.
    """
    s = get_settings()
    if s.use_fakes:
        return FakeQueryAnalyzer()
    from app.infrastructure.gemini_llm import GeminiQueryAnalyzer

    api_key = s.gemini_api_key
    if not api_key:
        raise RuntimeError(
            "ODS_GEMINI_API_KEY required for reformulation in generation eval"
        )
    return GeminiQueryAnalyzer(api_key=api_key, model=cfg.query.reformulate_model)


def build_judge(*, allow_llm: bool = True) -> Judge:
    """Fixed-model Gemini judge (or a deterministic fake in tests/fake mode)."""
    s = get_settings()
    if s.use_fakes or not allow_llm or not s.gemini_api_key:
        return FakeJudge()
    return GeminiJudge(api_key=s.gemini_api_key, model=JUDGE_MODEL)


def build_retriever(cfg: ExperimentConfig, *, allow_llm: bool = False) -> AnswerQuestion:
    """Construct an ``AnswerQuestion`` wired with this config's knobs.

    ``allow_llm=False`` (phase 1) forces a passthrough analyzer + guard LLM, so
    the only models touched are the embedder and reranker (read-only retrieval).
    ``allow_llm=True`` (phase 2) wires the real reformulator (when the config
    enables it) and the config's answer model/temperature for generation.
    """
    analyzer: QueryAnalyzer
    llm: AnswerLLM
    if allow_llm and cfg.query.reformulate:
        analyzer = build_query_analyzer(cfg)
    else:
        analyzer = FakeQueryAnalyzer()
    llm = build_answer_llm(cfg) if allow_llm else _UnusedLLM()

    return AnswerQuestion(
        intent_classifier=get_intent_classifier(),
        analyzer=analyzer,
        embedder=get_embedder(),
        store=build_store(cfg.collection),
        reranker=get_reranker(),
        llm=llm,
        guardrail=get_guardrail(),
        config=RetrievalConfig(
            retrieval_top_k=cfg.query.retrieval_top_k,
            rerank_candidates=cfg.query.rerank_candidates,
            rerank_top_k=cfg.query.rerank_top_k,
            score_threshold=cfg.query.score_threshold,
        ),
    )
