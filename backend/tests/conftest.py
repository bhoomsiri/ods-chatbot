"""Shared test fixtures. Unit tests use in-memory fakes — no network."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.domain.entities import AnswerEvent
from app.infrastructure.chunker import MetadataAwareChunker
from app.infrastructure.fakes import (
    EchoLLM,
    FakeQueryAnalyzer,
    HashEmbedder,
    InMemoryVectorStore,
    PassthroughReranker,
    TextDocumentParser,
)
from app.infrastructure.guardrail import CitationGuardrail
from app.infrastructure.intent_classifier import RuleBasedIntentClassifier
from app.usecases.answer import AnswerQuestion, RetrievalConfig
from app.usecases.ingest import IngestDocument


@pytest.fixture
def store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder()


@pytest.fixture
def ingest_uc(store: InMemoryVectorStore, embedder: HashEmbedder) -> IngestDocument:
    return IngestDocument(
        parser=TextDocumentParser(),
        chunker=MetadataAwareChunker(),
        embedder=embedder,
        store=store,
    )


@pytest.fixture
def answer_uc(store: InMemoryVectorStore, embedder: HashEmbedder) -> AnswerQuestion:
    return AnswerQuestion(
        intent_classifier=RuleBasedIntentClassifier(),
        analyzer=FakeQueryAnalyzer(),
        embedder=embedder,
        store=store,
        reranker=PassthroughReranker(),
        llm=EchoLLM(),
        guardrail=CitationGuardrail(),
        config=RetrievalConfig(score_threshold=0.1),
    )


async def collect(stream: AsyncIterator[AnswerEvent]) -> list[AnswerEvent]:
    return [event async for event in stream]
