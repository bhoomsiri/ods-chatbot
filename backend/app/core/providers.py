"""Dependency injection container.

Builds concrete adapters from settings and assembles use cases. Routers depend
on the `get_*_usecase` providers via FastAPI `Depends`. Components are cached so
heavy models load once and the in-memory fake store is shared across requests.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.settings import Settings, get_settings
from app.domain.ports import (
    AnswerLLM,
    ChunkClassifier,
    Chunker,
    DocumentParser,
    Embedder,
    Guardrail,
    IntentClassifier,
    QueryAnalyzer,
    Reranker,
    VectorStore,
)
from app.infrastructure.chunker import MetadataAwareChunker
from app.infrastructure.guardrail import CitationGuardrail
from app.infrastructure.intent_classifier import RuleBasedIntentClassifier
from app.usecases.answer import AnswerQuestion, RetrievalConfig
from app.usecases.ingest import IngestDocument


def _require(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(
            f"{name} is required when ODS_USE_FAKES is false. "
            "Set it in the environment or .env file."
        )
    return value


@lru_cache
def get_parser() -> DocumentParser:
    s = get_settings()
    if s.use_fakes:
        from app.infrastructure.fakes import TextDocumentParser

        return TextDocumentParser()
    from app.infrastructure.docling_parser import DoclingParser

    return DoclingParser(do_ocr=s.docling_ocr)


@lru_cache
def get_chunker() -> Chunker:
    return MetadataAwareChunker()


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.use_fakes:
        from app.infrastructure.fakes import HashEmbedder

        return HashEmbedder()
    if s.embedder == "openai":
        from app.infrastructure.openai_embedder import OpenAIEmbedder

        return OpenAIEmbedder(
            api_key=_require(s.openai_api_key, "ODS_OPENAI_API_KEY"),
            model=s.openai_embed_model,
        )
    from app.infrastructure.bge_m3_embedder import BGEM3Embedder

    return BGEM3Embedder()


@lru_cache
def get_store() -> VectorStore:
    s = get_settings()
    if s.use_fakes:
        from app.infrastructure.fakes import InMemoryVectorStore

        return InMemoryVectorStore()
    from app.infrastructure.qdrant_store import QdrantVectorStore

    return QdrantVectorStore(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        collection=s.qdrant_collection,
        dense_size=s.embedding_dim,
    )


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    if s.use_fakes:
        from app.infrastructure.fakes import PassthroughReranker

        return PassthroughReranker()
    from app.infrastructure.reranker import BGEReranker

    return BGEReranker(
        model_name=s.reranker_model, num_threads=s.torch_num_threads
    )


@lru_cache
def get_query_analyzer() -> QueryAnalyzer:
    s = get_settings()
    if s.use_fakes:
        from app.infrastructure.fakes import FakeQueryAnalyzer

        return FakeQueryAnalyzer()
    from app.infrastructure.gemini_llm import GeminiQueryAnalyzer

    return GeminiQueryAnalyzer(
        api_key=_require(s.gemini_api_key, "ODS_GEMINI_API_KEY"),
        model=s.gemini_reformulate_model,
    )


@lru_cache
def get_llm() -> AnswerLLM:
    s = get_settings()
    if s.use_fakes:
        from app.infrastructure.fakes import EchoLLM

        return EchoLLM()
    from app.infrastructure.gemini_llm import GeminiAnswerLLM

    return GeminiAnswerLLM(
        api_key=_require(s.gemini_api_key, "ODS_GEMINI_API_KEY"),
        model=s.gemini_answer_model,
        temperature=s.answer_temperature,
    )


@lru_cache
def get_guardrail() -> Guardrail:
    return CitationGuardrail()


@lru_cache
def get_intent_classifier() -> IntentClassifier:
    # Rule-based for now; swap for an LLM adapter here without touching the
    # use case. Same implementation in fake and real mode (pure, no services).
    return RuleBasedIntentClassifier()


def get_answer_usecase() -> AnswerQuestion:
    s: Settings = get_settings()
    # Fake embeddings score lower than real bge-m3, so relax the evidence
    # threshold in fake mode to keep the demo answering.
    threshold = 0.05 if s.use_fakes else s.score_threshold
    return AnswerQuestion(
        intent_classifier=get_intent_classifier(),
        analyzer=get_query_analyzer(),
        embedder=get_embedder(),
        store=get_store(),
        reranker=get_reranker(),
        llm=get_llm(),
        guardrail=get_guardrail(),
        config=RetrievalConfig(
            retrieval_top_k=s.retrieval_top_k,
            rerank_candidates=s.rerank_candidates,
            rerank_top_k=s.rerank_top_k,
            score_threshold=threshold,
        ),
    )


@lru_cache
def get_classifier() -> ChunkClassifier | None:
    s = get_settings()
    if s.use_fakes:
        return None
    from app.infrastructure.gemini_llm import GeminiChunkClassifier

    return GeminiChunkClassifier(
        api_key=_require(s.gemini_api_key, "ODS_GEMINI_API_KEY"),
        model=s.gemini_reformulate_model,
    )


def get_ingest_usecase() -> IngestDocument:
    return IngestDocument(
        parser=get_parser(),
        chunker=get_chunker(),
        embedder=get_embedder(),
        store=get_store(),
        classifier=get_classifier(),
    )
