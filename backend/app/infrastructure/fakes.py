"""In-memory fake adapters.

Used for (a) local boot without Qdrant/models (USE_FAKES=1, graceful
degradation) and (b) unit tests, where ports must be faked with no network.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from itertools import count

from app.domain.entities import (
    GENERAL_DEPARTMENT,
    ChatTurn,
    Citation,
    Conversation,
    EmbeddedChunk,
    Embedding,
    Message,
    ParsedDocument,
    ParsedPage,
    QueryAnalysis,
    ScoredChunk,
)

_DIM = 256


def _features(text: str) -> list[str]:
    """Whitespace tokens + character trigrams.

    Trigrams give meaningful similarity for scripts without word spacing
    (e.g. Thai), where whitespace tokenization alone would find nothing.
    """
    lower = text.lower()
    feats = lower.split()
    compact = "".join(lower.split())
    feats += [compact[i : i + 3] for i in range(len(compact) - 2)]
    return feats


def _hash_embed(text: str) -> list[float]:
    """Deterministic, dependency-free pseudo-embedding (feature hashing)."""
    vec = [0.0] * _DIM
    for feat in _features(text):
        h = int(hashlib.md5(feat.encode("utf-8")).hexdigest(), 16)
        vec[h % _DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class TextDocumentParser:
    """Decodes plain-text/markdown uploads into a single-page document.

    Real PDFs should use DoclingParser; this keeps fake-mode runnable.
    """

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="ignore")
        source = filename.rsplit(".", 1)[0]
        # Treat form-feed as a page break if present.
        raw_pages = text.split("\f") if "\f" in text else [text]
        pages = [
            ParsedPage(page=i + 1, text=p) for i, p in enumerate(raw_pages) if p.strip()
        ]
        return ParsedDocument(
            source=source, pages=pages or [ParsedPage(page=1, text=text)]
        )


class HashEmbedder:
    def embed_query(self, text: str) -> Embedding:
        return Embedding(dense=_hash_embed(text))

    def embed_documents(self, texts: Sequence[str]) -> list[Embedding]:
        return [Embedding(dense=_hash_embed(t)) for t in texts]


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[EmbeddedChunk] = []

    def ensure_collection(self) -> None:  # noqa: D401 - no-op for in-memory store
        return None

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        existing = {item.chunk.id for item in self._items}
        for ec in chunks:
            if ec.chunk.id in existing:
                continue
            self._items.append(ec)
            existing.add(ec.chunk.id)

    def hybrid_search(
        self,
        query: Embedding,
        *,
        category: str | None,
        department: str | None = None,
        top_k: int,
    ) -> list[ScoredChunk]:
        pool = [
            ec
            for ec in self._items
            if (category is None or ec.chunk.category in (None, category))
            and (
                department is None
                or ec.chunk.department in (None, department, GENERAL_DEPARTMENT)
            )
        ]
        scored = [
            ScoredChunk(chunk=ec.chunk, score=_cosine(query.dense, ec.embedding.dense))
            for ec in pool
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]


class PassthroughReranker:
    def rerank(
        self, query: str, chunks: Sequence[ScoredChunk], *, top_k: int
    ) -> list[ScoredChunk]:
        ordered = sorted(chunks, key=lambda s: s.score, reverse=True)
        return list(ordered[:top_k])


class FakeQueryAnalyzer:
    """Passthrough analyzer: in-scope, no decomposition, query unchanged."""

    async def analyze(self, query: str, history: Sequence[ChatTurn]) -> QueryAnalysis:
        return QueryAnalysis(in_scope=True, reformulated=query)


class InMemoryConversationStore:
    """Non-persistent ConversationStore for fake mode + unit tests.

    Scopes every operation by user_id exactly like the Postgres adapter, so the
    same ownership tests run against both. A monotonic counter drives ids and
    timestamps so ordering is deterministic (avoids same-microsecond ties).
    """

    def __init__(self) -> None:
        self._convs: dict[str, Conversation] = {}
        self._msgs: dict[str, list[Message]] = {}
        self._seq = count(1)

    def _stamp(self) -> datetime:
        return datetime.fromtimestamp(next(self._seq), tz=timezone.utc)

    async def create(self, *, user_id: str, title: str) -> Conversation:
        ts = self._stamp()
        cid = f"conv-{next(self._seq)}"
        conv = Conversation(
            id=cid,
            user_id=user_id,
            title=title.strip()[:200] or "แชตใหม่",
            created_at=ts,
            updated_at=ts,
        )
        self._convs[cid] = conv
        self._msgs[cid] = []
        return conv

    async def list_for_user(self, *, user_id: str) -> list[Conversation]:
        owned = [c for c in self._convs.values() if c.user_id == user_id]
        return sorted(owned, key=lambda c: c.updated_at, reverse=True)

    def _owned(self, conversation_id: str, user_id: str) -> Conversation | None:
        conv = self._convs.get(conversation_id)
        return conv if conv is not None and conv.user_id == user_id else None

    async def get_messages(
        self, *, conversation_id: str, user_id: str
    ) -> list[Message] | None:
        if self._owned(conversation_id, user_id) is None:
            return None
        return list(self._msgs.get(conversation_id, []))

    async def add_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        citations: Sequence[Citation] = (),
    ) -> Message | None:
        conv = self._owned(conversation_id, user_id)
        if conv is None:
            return None
        ts = self._stamp()
        msg = Message(
            id=f"msg-{next(self._seq)}",
            role=role,
            content=content,
            created_at=ts,
            citations=list(citations),
        )
        self._msgs[conversation_id].append(msg)
        # Bump thread to the top of the sidebar.
        self._convs[conversation_id] = Conversation(
            id=conv.id,
            user_id=conv.user_id,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=ts,
        )
        return msg

    async def set_title(
        self, *, conversation_id: str, user_id: str, title: str
    ) -> bool:
        conv = self._owned(conversation_id, user_id)
        if conv is None:
            return False
        self._convs[conversation_id] = Conversation(
            id=conv.id,
            user_id=conv.user_id,
            title=title.strip()[:200] or "แชตใหม่",
            created_at=conv.created_at,
            updated_at=self._stamp(),
        )
        return True

    async def delete(self, *, conversation_id: str, user_id: str) -> bool:
        if self._owned(conversation_id, user_id) is None:
            return False
        self._convs.pop(conversation_id, None)
        self._msgs.pop(conversation_id, None)
        return True


class EchoLLM:
    """Streams a safe, citation-anchored canned answer from the evidence."""

    async def stream(
        self,
        *,
        question: str,
        contexts: Sequence[ScoredChunk],
        history: Sequence[ChatTurn] = (),
    ) -> AsyncIterator[str]:
        top = contexts[0].chunk
        snippet = top.text[:120].strip()
        answer = (
            f"จากคู่มือ {top.source} หน้า {top.page}: {snippet} "
            f"(คำตอบตัวอย่างจากโหมด fake — ยังไม่ได้เชื่อมต่อโมเดลจริง)"
        )
        for word in answer.split(" "):
            yield word + " "
