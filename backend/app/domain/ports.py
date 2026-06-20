"""Ports (Protocols) — the abstractions use cases depend on.

Concrete adapters live in `infrastructure/`. Use cases must import ONLY from
this module and `entities`, never from `infrastructure`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from app.domain.entities import (
    ChatTurn,
    Chunk,
    ChunkTag,
    Citation,
    EmbeddedChunk,
    Embedding,
    GuardrailVerdict,
    IntentResult,
    ParsedDocument,
    QueryAnalysis,
    ScoredChunk,
)


@runtime_checkable
class DocumentParser(Protocol):
    """Extracts text (+ layout/tables) and page images from a raw file."""

    def parse(self, content: bytes, filename: str) -> ParsedDocument: ...


@runtime_checkable
class Chunker(Protocol):
    """Metadata-aware chunking; chunks never cross a page boundary."""

    def chunk(
        self, document: ParsedDocument, *, category: str | None = None
    ) -> list[Chunk]: ...


@runtime_checkable
class ChunkClassifier(Protocol):
    """Tags each chunk with a content category + surgical department.

    Batch API: implementations may classify many chunks per model call to keep
    cost/latency down. Returns one ChunkTag per input text, in order.
    """

    def classify(self, texts: Sequence[str]) -> list[ChunkTag]: ...


@runtime_checkable
class Embedder(Protocol):
    """Produces dense (+ optional sparse) embeddings."""

    def embed_query(self, text: str) -> Embedding: ...

    def embed_documents(self, texts: Sequence[str]) -> list[Embedding]: ...


@runtime_checkable
class VectorStore(Protocol):
    def ensure_collection(self) -> None: ...

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None: ...

    def hybrid_search(
        self, query: Embedding, *, category: str | None, top_k: int
    ) -> list[ScoredChunk]: ...


@runtime_checkable
class Reranker(Protocol):
    def rerank(
        self, query: str, chunks: Sequence[ScoredChunk], *, top_k: int
    ) -> list[ScoredChunk]: ...


@runtime_checkable
class IntentClassifier(Protocol):
    """Input router: decide whether a message needs RAG or a direct reply.

    Returning IntentResult.direct_response short-circuits retrieval (greetings,
    chit-chat). For a high-trust medical bot, an implementation MUST default to
    a "question" result (no direct_response) whenever it is uncertain, so a real
    question is never swallowed.
    """

    async def classify(
        self, message: str, history: Sequence[ChatTurn]
    ) -> IntentResult: ...


@runtime_checkable
class QueryAnalyzer(Protocol):
    """Pre-retrieval query understanding: scope check + reformulation +
    decomposition of compound questions. Replaces a bare reformulator so the
    use case can route out-of-scope questions and retrieve per sub-intent."""

    async def analyze(
        self, query: str, history: Sequence[ChatTurn]
    ) -> QueryAnalysis: ...


@runtime_checkable
class AnswerLLM(Protocol):
    """Streams an answer grounded in the provided evidence.

    `history` lets the answer resolve follow-ups ("are there only 2?",
    "summarize all of the above") — facts still come only from `contexts`.
    """

    def stream(
        self,
        *,
        question: str,
        contexts: Sequence[ScoredChunk],
        history: Sequence[ChatTurn] = (),
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class Guardrail(Protocol):
    def validate(
        self, answer: str, citations: Sequence[Citation]
    ) -> GuardrailVerdict: ...
