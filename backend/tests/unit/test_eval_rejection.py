"""Rejection metrics (pure, no LLM)."""

from __future__ import annotations

from app.domain.entities import OUT_OF_SCOPE_TEXT, REFUSAL_TEXT, SAFETY_NOTICE
from eval.metrics.rejection import (
    false_refusal_rate,
    is_refusal,
    negative_rejection_rate,
)


def test_is_refusal_matches_domain_messages() -> None:
    assert is_refusal(REFUSAL_TEXT)
    assert is_refusal(OUT_OF_SCOPE_TEXT)
    assert is_refusal("คำตอบบางส่วน\n\n" + SAFETY_NOTICE)  # appended guardrail notice
    assert not is_refusal("งดน้ำงดอาหารอย่างน้อย 8 ชั่วโมง (อ้างอิง หน้า 3)")


def test_negative_rejection_rate() -> None:
    # 3 of 4 out-of-scope questions correctly refused.
    assert negative_rejection_rate([True, True, True, False]) == 0.75
    assert negative_rejection_rate([]) == 0.0


def test_false_refusal_rate() -> None:
    # 1 of 5 in-scope questions wrongly refused.
    assert false_refusal_rate([False, False, True, False, False]) == 0.2
