"""Structure-aware chunker (pure Python).

Splits each page independently so a chunk never crosses a page boundary (keeps
citations page-accurate), but within a page it follows the document structure
that DoclingParser exposes as ParsedBlocks:

- a new chunk starts at a section heading, and that heading is prefixed onto the
  chunk as retrieval context;
- a table is kept whole as its own chunk (never split mid-row);
- consecutive text/list blocks are packed up to ~chunk_size, then flushed;
- an oversized single block falls back to a sliding-window character split.

If a page has no blocks (e.g. the plain-text fake parser), it degrades to the
old fixed-size split over `page.text`.
"""

from __future__ import annotations

import re

from app.domain.entities import Chunk, ParsedBlock, ParsedDocument

_WHITESPACE_RE = re.compile(r"\s+")


class MetadataAwareChunker:
    def __init__(
        self, *, chunk_size: int = 800, overlap: int = 120, min_size: int = 80
    ) -> None:
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._min_size = min_size

    def chunk(
        self,
        document: ParsedDocument,
        *,
        category: str | None = None,
        department: str | None = None,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        for page in document.pages:
            blocks = page.blocks or [ParsedBlock("text", page.text)]
            for idx, piece in enumerate(self._chunk_page(blocks)):
                chunks.append(
                    Chunk(
                        id=f"{document.source}::p{page.page}::{idx}",
                        text=piece,
                        source=document.source,
                        page=page.page,
                        category=category,
                        department=department,
                        image=page.image,
                        metadata={"source": document.source, "page": str(page.page)},
                    )
                )
        return chunks

    def _chunk_page(self, blocks: list[ParsedBlock]) -> list[str]:
        pieces: list[str] = []
        heading = ""
        buf: list[str] = []

        def buf_len() -> int:
            return sum(len(b) for b in buf)

        def flush() -> None:
            if not buf:
                return
            body = _WHITESPACE_RE.sub(" ", " ".join(buf)).strip()
            buf.clear()
            if body:
                pieces.append(self._with_heading(heading, body))

        for block in blocks:
            text = _WHITESPACE_RE.sub(" ", block.text).strip()
            if not text:
                continue
            if block.kind == "heading":
                flush()
                heading = text
                continue
            if block.kind == "table":
                flush()
                pieces.append(self._with_heading(heading, text))
                continue
            # text / list
            if len(text) > self._chunk_size:
                flush()
                for part in self._split(text):
                    pieces.append(self._with_heading(heading, part))
                continue
            if buf_len() + len(text) > self._chunk_size:
                flush()
            buf.append(text)
            if buf_len() >= self._chunk_size:
                flush()
        flush()

        # Merge a too-small trailing piece into the previous one to avoid noise.
        if len(pieces) >= 2 and len(pieces[-1]) < self._min_size:
            pieces[-2] = f"{pieces[-2]} {pieces[-1]}"
            pieces.pop()
        return pieces

    def _with_heading(self, heading: str, body: str) -> str:
        if heading and not body.startswith(heading):
            return f"{heading}\n{body}"
        return body

    def _split(self, text: str) -> list[str]:
        if len(text) <= self._chunk_size:
            return [text]
        step = self._chunk_size - self._overlap
        return [
            text[start : start + self._chunk_size]
            for start in range(0, len(text), step)
            if text[start : start + self._chunk_size].strip()
        ]
