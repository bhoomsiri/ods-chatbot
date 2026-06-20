from __future__ import annotations

from app.domain.entities import ParsedDocument, ParsedPage
from app.infrastructure.chunker import MetadataAwareChunker


def test_chunks_never_cross_pages_and_are_tagged() -> None:
    doc = ParsedDocument(
        source="ODS MIS 2565",
        pages=[
            ParsedPage(page=1, text="ก่อนผ่าตัด " * 200),
            ParsedPage(page=2, text="หลังผ่าตัด " * 200),
        ],
    )
    chunks = MetadataAwareChunker(chunk_size=300, overlap=50).chunk(
        doc, category="pre_op"
    )

    assert len(chunks) > 2  # long pages are split
    assert {c.page for c in chunks} == {1, 2}
    assert all(c.category == "pre_op" for c in chunks)
    assert all(c.source == "ODS MIS 2565" for c in chunks)
    # A page-1 chunk must not contain page-2 text.
    page1 = [c for c in chunks if c.page == 1]
    assert all("หลังผ่าตัด" not in c.text for c in page1)


def test_blank_pages_are_skipped() -> None:
    doc = ParsedDocument(
        source="doc", pages=[ParsedPage(page=1, text="   "), ParsedPage(page=2, text="x")]
    )
    chunks = MetadataAwareChunker().chunk(doc)
    assert [c.page for c in chunks] == [2]
