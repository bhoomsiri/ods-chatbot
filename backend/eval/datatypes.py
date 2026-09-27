"""Plain dataclasses passed between the harness stages.

Kept framework-free (no pydantic) so metrics can be unit-tested with hand-built
values and nothing here imports an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalItem:
    """One in-scope question joined with its gold answer + gold pages/sources."""

    id: int
    category: str
    question: str
    gold_pages: frozenset[int]
    gold_sources: frozenset[str] = frozenset()
    gold_answer: str = ""
    source_doc: str = ""
    # True for the negative "no such data" probe (id 30): correct behavior is a
    # refusal, so it is scored by rejection, not by retrieval recall.
    is_rejection_test: bool = False


@dataclass(frozen=True)
class OOSItem:
    """One out-of-scope question (used by the rejection eval in phase 2)."""

    id: str
    type: str
    question: str
    expected: str
    difficulty: str = ""


@dataclass(frozen=True)
class RetrievedContext:
    """A single retrieved chunk, flattened for scoring + serialization."""

    id: str
    page: int | None
    source: str
    score: float
    text: str


@dataclass(frozen=True)
class RetrievalResult:
    """Per-question retrieval outcome for one config, plus its metrics."""

    item_id: int
    question: str
    gold_pages: list[int]
    # Ranked contexts after rerank, before the evidence-filter threshold. Used
    # for rank-quality metrics (MRR/nDCG) that need the full ranking.
    reranked: list[RetrievedContext]
    # Contexts that passed the evidence filter (what the LLM would receive).
    evidence: list[RetrievedContext]
    refused: bool  # True when the evidence filter left nothing (would refuse)
    latency_ms: float
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricRow:
    """Aggregated metrics for one config across the question set."""

    config: str
    knob: str
    n: int
    metrics: dict[str, float] = field(default_factory=dict)
