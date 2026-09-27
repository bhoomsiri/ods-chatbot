"""Negative-rejection metrics (no LLM).

Measures whether the system correctly declines to answer. A "refusal" is the
system emitting one of the safety messages mandated by CLAUDE.md §5 (no evidence
-> ``REFUSAL_TEXT``; out of scope -> ``OUT_OF_SCOPE_TEXT``; guardrail block ->
``SAFETY_NOTICE``). Detection keys off those exact domain constants so it can
never drift from the pipeline.

- negative_rejection_rate: on out-of-scope questions, the fraction correctly
  refused (higher is better — the bot must not answer off-manual).
- false_refusal_rate: on in-scope questions, the fraction wrongly refused
  (lower is better — a refusal here is a missed answerable question).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.entities import OUT_OF_SCOPE_TEXT, REFUSAL_TEXT, SAFETY_NOTICE

_REFUSAL_MARKERS = (REFUSAL_TEXT, OUT_OF_SCOPE_TEXT, SAFETY_NOTICE)


def is_refusal(text: str) -> bool:
    """True if the answer is one of the system's safety/refusal messages."""
    t = text.strip()
    return any(marker in t for marker in _REFUSAL_MARKERS)


def _rate(flags: Sequence[bool]) -> float:
    return sum(1 for f in flags if f) / len(flags) if flags else 0.0


def negative_rejection_rate(refused_flags: Sequence[bool]) -> float:
    """Fraction of out-of-scope questions that were correctly refused."""
    return _rate(refused_flags)


def false_refusal_rate(refused_flags: Sequence[bool]) -> float:
    """Fraction of in-scope questions that were wrongly refused."""
    return _rate(refused_flags)
