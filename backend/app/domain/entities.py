"""Core domain entities. NO framework imports (no pydantic/fastapi here)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ChatTurn:
    """One turn of conversation history."""

    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class SparseVector:
    """Lexical (sparse) representation, e.g. bge-m3 lexical weights."""

    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class Embedding:
    """Dense vector, optionally paired with a sparse vector (hybrid)."""

    dense: list[float]
    sparse: SparseVector | None = None


@dataclass(frozen=True)
class ParsedBlock:
    """A structural element extracted from a page (for structure-aware chunking).

    kind: "heading" | "text" | "list" | "table".
    """

    kind: str
    text: str


@dataclass(frozen=True)
class ParsedPage:
    page: int
    text: str
    image: str | None = None  # data URL / path to the rendered page image
    # Structured elements in reading order. Empty for plain-text parsers; the
    # chunker then falls back to splitting `text`.
    blocks: list[ParsedBlock] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDocument:
    source: str  # human-readable source name, e.g. "ODS MIS 2565"
    pages: list[ParsedPage]


@dataclass(frozen=True)
class Chunk:
    """A retrievable, metadata-tagged unit of text (never crosses a page)."""

    id: str
    text: str
    source: str
    page: int | None = None
    category: str | None = None  # content phase, e.g. ก่อนผ่าตัด / หลังผ่าตัด
    department: str | None = None  # surgical department, e.g. จักษุ / นรีเวช
    image: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


# Department tag for content that applies to every surgical department (general
# ODS policy/prep/safety docs). A department filter always includes this bucket
# so selecting one specialty keeps the general material and only drops OTHER
# specialties' specific docs.
GENERAL_DEPARTMENT = "ภาพรวม/ไม่ระบุ"


@dataclass(frozen=True)
class ChunkTag:
    """Classification labels assigned to a chunk before indexing."""

    category: str
    department: str


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: Chunk
    embedding: Embedding


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Citation:
    id: str
    source: str
    page: int | None
    score: float | None
    snippet: str | None
    image: str | None = None

    @classmethod
    def from_scored(cls, scored: ScoredChunk, *, snippet_len: int = 240) -> Citation:
        c = scored.chunk
        snippet = c.text[:snippet_len].strip()
        if len(c.text) > snippet_len:
            snippet += "…"
        return cls(
            id=c.id,
            source=c.source,
            page=c.page,
            score=round(scored.score, 4),
            snippet=snippet,
            image=c.image,
        )


@dataclass(frozen=True)
class Message:
    """One persisted chat message belonging to a conversation."""

    id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime
    citations: list[Citation] = field(default_factory=list)


@dataclass(frozen=True)
class Conversation:
    """A persisted chat thread, scoped to a user (Claude-style history item)."""

    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class IntentResult:
    """Outcome of input routing.

    kind: a label such as "greeting" or "question".
    direct_response: if set, the use case answers with it and skips RAG
    (used for greetings/chit-chat). None means "treat as a real question".
    """

    kind: str
    direct_response: str | None = None


@dataclass(frozen=True)
class QueryAnalysis:
    """Pre-retrieval query understanding.

    in_scope: False only for questions clearly unrelated to ODS / the hospital
        (the use case then refuses early). Leans True — the evidence filter,
        not this flag, is the real gate for "we have no document on this".
    reformulated: a single standalone search query (resolves pronouns/context).
    sub_queries: distinct information needs when the question is compound; each
        is retrieved separately and the candidates merged. Empty for a simple
        single-intent question.
    """

    in_scope: bool
    reformulated: str
    sub_queries: list[str] = field(default_factory=list)
    reason: str = ""

    def queries(self) -> list[str]:
        """The queries to retrieve for: the decomposed parts, else the main."""
        qs = [q.strip() for q in self.sub_queries if q.strip()]
        return qs or [self.reformulated]


@dataclass(frozen=True)
class IngestReport:
    filename: str
    chunks: int


# --- Streaming output events emitted by the answer use case ------------------


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class CitationsEvent:
    citations: list[Citation]


AnswerEvent = TokenEvent | CitationsEvent


# User-facing system messages.
QUOTA_MESSAGE = (
    "ขออภัยครับ ขณะนี้ระบบใช้งานเกินโควตา/โทเค็นที่กำหนด (rate limit ของ Gemini) "
    "กรุณาลองใหม่อีกครั้งในอีกสักครู่ หรือแจ้งผู้ดูแลระบบให้ตรวจสอบโควตา"
)
ERROR_MESSAGE = "ขออภัยครับ เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่อีกครั้ง"

# Safety copy mandated by CLAUDE.md §5.
REFUSAL_TEXT = "ไม่พบข้อมูลในคู่มือ กรุณาสอบถามเจ้าหน้าที่"
OUT_OF_SCOPE_TEXT = (
    "ขออภัยครับ คำถามนี้อยู่นอกขอบเขตข้อมูลการผ่าตัดแบบวันเดียวกลับ (ODS) "
    "ของโรงพยาบาลโพธาราม หากมีข้อสงสัยอื่น กรุณาสอบถามเจ้าหน้าที่"
)
SAFETY_NOTICE = "ขออภัย ระบบไม่สามารถให้คำตอบนี้ได้ " "กรุณาปรึกษาเจ้าหน้าที่หรือแพทย์โดยตรง"
