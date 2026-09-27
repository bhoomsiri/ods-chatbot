"""Deterministic retrieval metrics — no LLM, no heavy deps.

Each function scores a *ranked* list of retrieved keys against the set of gold
keys for one question. The "key" is generic: pass page numbers for page-level
metrics, or source-document names for source-level metrics (robust to the
hospital .docx files that collapse to a single page, where the gold page numbers
were authored against the original multi-page layout). Relevance is binary: a
retrieved item is relevant iff its key is one of the gold keys. Keys may repeat
across chunks and may be ``None`` (e.g. a chunk with no page → never relevant).

Definitions (k = cutoff, 1-indexed ranks):
- hit@k     : 1.0 if any of the top-k items is relevant, else 0.0
- recall@k  : (# distinct gold keys covered by the top-k) / (# gold keys)
- mrr       : 1 / (rank of the first relevant item within the top-k), else 0.0
- ndcg@k    : DCG@k / IDCG@k with binary gains, IDCG = the same labels in ideal
              (descending) order; 0.0 when no relevant item is in the top-k

All four are pure functions of their inputs (fully reproducible).
"""

from __future__ import annotations

import math
from collections.abc import Collection, Hashable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=Hashable)


def _relevance(retrieved: Sequence[T | None], gold: Collection[T]) -> list[int]:
    """Binary relevance label per retrieved item, in rank order."""
    goldset = set(gold)
    return [1 if (key is not None and key in goldset) else 0 for key in retrieved]


def hit_at_k(retrieved: Sequence[T | None], gold: Collection[T], k: int) -> float:
    if k <= 0 or not gold:
        return 0.0
    return 1.0 if any(_relevance(retrieved[:k], gold)) else 0.0


def recall_at_k(retrieved: Sequence[T | None], gold: Collection[T], k: int) -> float:
    """Fraction of distinct gold keys found in the top-k."""
    goldset = set(gold)
    if k <= 0 or not goldset:
        return 0.0
    found = {key for key in retrieved[:k] if key is not None and key in goldset}
    return len(found) / len(goldset)


def precision_at_k(retrieved: Sequence[T | None], gold: Collection[T], k: int) -> float:
    """Fraction of the top-k retrieved items that are relevant: #relevant / k.

    Counts positions (a repeated gold key counts each time it appears), unlike
    recall which counts distinct gold keys — this is precision by definition.
    """
    if k <= 0 or not gold:
        return 0.0
    labels = _relevance(retrieved[:k], gold)
    return sum(labels) / k


def mrr(
    retrieved: Sequence[T | None], gold: Collection[T], k: int | None = None
) -> float:
    """Reciprocal rank of the first relevant item (within top-k if given)."""
    if not gold:
        return 0.0
    labels = _relevance(retrieved, gold)
    if k is not None:
        labels = labels[:k]
    for rank, rel in enumerate(labels, start=1):
        if rel:
            return 1.0 / rank
    return 0.0


def _dcg(labels: Sequence[int]) -> float:
    # gain_i / log2(rank_i + 1), ranks 1-indexed.
    return sum(rel / math.log2(rank + 1) for rank, rel in enumerate(labels, start=1))


def ndcg_at_k(retrieved: Sequence[T | None], gold: Collection[T], k: int) -> float:
    if k <= 0 or not gold:
        return 0.0
    labels = _relevance(retrieved[:k], gold)
    ideal = sorted(labels, reverse=True)
    idcg = _dcg(ideal)
    if idcg == 0.0:
        return 0.0
    return _dcg(labels) / idcg
