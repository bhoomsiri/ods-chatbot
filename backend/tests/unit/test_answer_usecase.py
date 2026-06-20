from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.domain.entities import (
    OUT_OF_SCOPE_TEXT,
    REFUSAL_TEXT,
    ChatTurn,
    CitationsEvent,
    QueryAnalysis,
    TokenEvent,
)
from app.domain.intent import GREETING_RESPONSE
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


class _StubAnalyzer:
    """Analyzer that returns a fixed analysis, for testing routing/merge."""

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

_DOC = (
    "ก่อนผ่าตัดผู้ป่วยต้องงดน้ำงดอาหาร อย่างน้อย 6 ถึง 8 ชั่วโมง "
    "เพื่อความปลอดภัยในการให้ยาระงับความรู้สึก"
).encode()


@pytest.mark.asyncio
async def test_greeting_responds_without_retrieval(answer_uc: AnswerQuestion) -> None:
    events = await collect(answer_uc.execute("สวัสดีครับ"))
    assert len(events) == 1
    assert isinstance(events[0], TokenEvent)
    assert events[0].text == GREETING_RESPONSE


@pytest.mark.asyncio
async def test_refuses_when_no_evidence(answer_uc: AnswerQuestion) -> None:
    events = await collect(answer_uc.execute("ค่าจอดรถเท่าไหร่"))
    assert len(events) == 1
    assert isinstance(events[0], TokenEvent)
    assert events[0].text == REFUSAL_TEXT


@pytest.mark.asyncio
async def test_streams_answer_and_citations_with_evidence(
    answer_uc: AnswerQuestion, ingest_uc: IngestDocument
) -> None:
    report = ingest_uc.execute(_DOC, "ODS MIS 2565.txt", category="pre_op")
    assert report.chunks >= 1

    events = await collect(
        answer_uc.execute("ก่อนผ่าตัดต้องงดน้ำงดอาหารกี่ชั่วโมง", category="pre_op")
    )

    tokens = [e for e in events if isinstance(e, TokenEvent)]
    citation_events = [e for e in events if isinstance(e, CitationsEvent)]

    assert tokens, "expected streamed answer tokens"
    assert len(citation_events) == 1
    citations = citation_events[0].citations
    assert citations and citations[0].source == "ODS MIS 2565"
    assert citations[0].page == 1


@pytest.mark.asyncio
async def test_out_of_scope_routes_to_message(
    store: InMemoryVectorStore, embedder: HashEmbedder
) -> None:
    uc = _uc(
        store,
        embedder,
        QueryAnalysis(in_scope=False, reformulated="วันนี้อากาศเป็นยังไง", reason="off-topic"),
    )
    events = await collect(uc.execute("วันนี้อากาศเป็นยังไง"))
    assert len(events) == 1
    assert isinstance(events[0], TokenEvent)
    assert events[0].text == OUT_OF_SCOPE_TEXT


@pytest.mark.asyncio
async def test_decomposition_merges_evidence_from_each_subquery(
    store: InMemoryVectorStore, embedder: HashEmbedder, ingest_uc: IngestDocument
) -> None:
    ingest_uc.execute(
        "ก่อนผ่าตัดต้องงดน้ำงดอาหารอย่างน้อย 6 ชั่วโมง".encode(), "งดน้ำ.txt"
    )
    ingest_uc.execute(
        "หลังผ่าตัดควรระวังไม่ให้แผลโดนน้ำจนกว่าจะตัดไหม".encode(), "ดูแลแผล.txt"
    )

    # A compound question split into two sub-queries, one matching each doc.
    uc = _uc(
        store,
        embedder,
        QueryAnalysis(
            in_scope=True,
            reformulated="ก่อนและหลังผ่าตัดต้องทำอย่างไร",
            sub_queries=["ก่อนผ่าตัดงดน้ำงดอาหารกี่ชั่วโมง", "หลังผ่าตัดดูแลแผลอย่างไร"],
        ),
    )
    events = await collect(uc.execute("ก่อนและหลังผ่าตัดต้องทำอย่างไร"))
    citation_events = [e for e in events if isinstance(e, CitationsEvent)]
    assert len(citation_events) == 1
    sources = {c.source for c in citation_events[0].citations}
    assert {"งดน้ำ", "ดูแลแผล"} <= sources
