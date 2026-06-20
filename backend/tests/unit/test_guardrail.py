from __future__ import annotations

from app.domain.entities import Citation
from app.infrastructure.guardrail import CitationGuardrail

_CITATION = Citation(
    id="c1", source="ODS MIS 2565", page=12, score=0.9, snippet="งดน้ำงดอาหาร"
)


def test_rejects_answer_without_citation() -> None:
    verdict = CitationGuardrail().validate("คำตอบบางอย่าง", [])
    assert not verdict.allowed
    assert verdict.reason == "missing_citation"


def test_rejects_diagnosis_attempt() -> None:
    verdict = CitationGuardrail().validate("คุณเป็นโรคไส้ติ่งอักเสบ", [_CITATION])
    assert not verdict.allowed
    assert verdict.reason == "diagnosis_attempt"


def test_allows_grounded_answer() -> None:
    verdict = CitationGuardrail().validate(
        "ก่อนผ่าตัดต้องงดน้ำงดอาหาร (ODS MIS 2565 หน้า 12)", [_CITATION]
    )
    assert verdict.allowed
