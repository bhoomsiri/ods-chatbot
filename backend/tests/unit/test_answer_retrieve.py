"""retrieve() exposes the pre-LLM stages without changing execute() behavior.

These lock the contract the eval harness depends on (§10 of the spec): the
chunks retrieve() returns as evidence are exactly what execute() cites, and the
greeting / out-of-scope / no-evidence short-circuits still hold.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.domain.entities import (
    REFUSAL_TEXT,
    ChatTurn,
    CitationsEvent,
    QueryAnalysis,
    TokenEvent,
)
from app.infrastructure.fakes import (
    EchoLLM,
    HashEmbedder,
    InMemoryVectorStore,
    PassthroughReranker,
)
from app.infrastructure.guardrail import CitationGuardrail
from app.infrastructure.intent_classifier import RuleBasedIntentClassifier
from app.usecases.answer import AnswerQuestion, RetrievalConfig
from app.usecases.ingest import IngestDocument
from tests.conftest import collect

_DOC = (
    "ก่อนผ่าตัดผู้ป่วยต้องงดน้ำงดอาหาร อย่างน้อย 6 ถึง 8 ชั่วโมง "
    "เพื่อความปลอดภัยในการให้ยาระงับความรู้สึก"
).encode()


class _StubAnalyzer:
    def __init__(self, analysis: QueryAnalysis) -> None:
        self._analysis = analysis

    async def analyze(self, query: str, history: Sequence[ChatTurn]) -> QueryAnalysis:
        return self._analysis


def _uc(
    store: InMemoryVectorStore, embedder: HashEmbedder, analysis: QueryAnalysis
) -> AnswerQuestion:
    return AnswerQuestion(
        intent_classifier=RuleBasedIntentClassifier(),
        analyzer=_StubAnalyzer(analysis),
        embedder=embedder,
        store=store,
        reranker=PassthroughReranker(),
        llm=EchoLLM(),
        guardrail=CitationGuardrail(),
        config=RetrievalConfig(score_threshold=0.1),
    )


@pytest.mark.asyncio
async def test_retrieve_evidence_matches_execute_citations(
    answer_uc: AnswerQuestion, ingest_uc: IngestDocument
) -> None:
    ingest_uc.execute(_DOC, "ODS MIS 2565.txt", category="pre_op")
    q = "ก่อนผ่าตัดต้องงดน้ำงดอาหารกี่ชั่วโมง"

    outcome = await answer_uc.retrieve(q, category="pre_op")
    assert outcome.direct_response is None
    assert outcome.in_scope is True
    assert outcome.evidence, "expected evidence for an answerable question"

    events = await collect(answer_uc.execute(q, category="pre_op"))
    [cit_event] = [e for e in events if isinstance(e, CitationsEvent)]

    assert [c.chunk.id for c in outcome.evidence] == [c.id for c in cit_event.citations]


@pytest.mark.asyncio
async def test_retrieve_greeting_short_circuits(answer_uc: AnswerQuestion) -> None:
    outcome = await answer_uc.retrieve("สวัสดีครับ")
    assert outcome.direct_response is not None
    assert outcome.evidence == []
    assert outcome.candidates == []


@pytest.mark.asyncio
async def test_retrieve_no_evidence_then_execute_refuses(
    answer_uc: AnswerQuestion,
) -> None:
    # Empty store -> nothing retrieved -> no evidence.
    outcome = await answer_uc.retrieve("ค่าจอดรถเท่าไหร่")
    assert outcome.direct_response is None
    assert outcome.in_scope is True
    assert outcome.evidence == []

    events = await collect(answer_uc.execute("ค่าจอดรถเท่าไหร่"))
    assert len(events) == 1
    assert isinstance(events[0], TokenEvent)
    assert events[0].text == REFUSAL_TEXT


@pytest.mark.asyncio
async def test_retrieve_out_of_scope(
    store: InMemoryVectorStore, embedder: HashEmbedder
) -> None:
    uc = _uc(
        store,
        embedder,
        QueryAnalysis(in_scope=False, reformulated="วันนี้อากาศเป็นยังไง", reason="off"),
    )
    outcome = await uc.retrieve("วันนี้อากาศเป็นยังไง")
    assert outcome.in_scope is False
    assert outcome.direct_response is None
    assert outcome.evidence == []


@pytest.mark.asyncio
async def test_generate_answered_matches_execute_text(
    answer_uc: AnswerQuestion, ingest_uc: IngestDocument
) -> None:
    ingest_uc.execute(_DOC, "ODS MIS 2565.txt", category="pre_op")
    q = "ก่อนผ่าตัดต้องงดน้ำงดอาหารกี่ชั่วโมง"

    gen = await answer_uc.generate(q, category="pre_op")
    assert gen.status == "answered"
    assert gen.answer
    assert gen.refused is False
    assert gen.guardrail_allowed is True
    # full chunk text is preserved for faithfulness scoring (not truncated)
    assert gen.evidence and gen.evidence[0].chunk.text

    # generate() collects exactly what execute() would stream
    events = await collect(answer_uc.execute(q, category="pre_op"))
    streamed = "".join(e.text for e in events if isinstance(e, TokenEvent))
    assert gen.answer == streamed


@pytest.mark.asyncio
async def test_generate_status_branches(answer_uc: AnswerQuestion) -> None:
    greeting = await answer_uc.generate("สวัสดีครับ")
    assert greeting.status == "greeting"
    assert greeting.refused is False

    # empty store -> no evidence -> refusal
    refused = await answer_uc.generate("ค่าจอดรถเท่าไหร่")
    assert refused.status == "refused_no_evidence"
    assert refused.answer == REFUSAL_TEXT
    assert refused.refused is True
