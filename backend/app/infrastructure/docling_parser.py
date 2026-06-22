"""Docling document parser adapter.

Lazily imports `docling` so the rest of the app (and unit tests) can run
without the heavy dependency installed.

Three things this adapter handles for the ODS corpus:
1. OCR — kept ON so image-only / scanned pages (e.g. the EGD brochure, which has
   no text layer) still yield text. `force_full_page_ocr` stays False, so pages
   that already have a real text layer keep it (fast) and OCR only fills in
   bitmap regions. OCR runs on the GPU when available.
2. Thai repair — some manual PDFs use a font where the sara-am vowel (U+0E33)
   fails to map and docling emits U+FFFD before sara-aa (U+0E32). We repair this
   and strip private-use bullet glyphs.
3. Structure — instead of one flat text blob per page, we keep the docling items
   (headings / paragraphs / lists / tables) as ParsedBlocks so the chunker can
   split on meaning and keep tables whole.
"""

from __future__ import annotations

import io
import re
from typing import Any

from app.domain.entities import ParsedBlock, ParsedDocument, ParsedPage

# Some PDF fonts fail to map the upper part of sara-am (U+0E33), so docling emits
# U+FFFD there. The lost glyph shows up in a few shapes, all repaired below:
#   "น�้า" -> "น้ำ"  (น้ำ: FFFD + tone + sara-aa)
#   "ค�ำ"       -> "คำ"             (FFFD directly before sara-am)
#   "ค�า"       -> "คำ"             (FFFD + sara-aa, no tone)
_AM_TONE_RE = re.compile("�([่-๋])า")  # FFFD + tone + aa -> tone + am
_AM_BEFORE_RE = re.compile("�ำ")  # FFFD + am -> am
_AM_PLAIN_RE = re.compile("�า")  # FFFD + aa -> am
# Anything still left: Private Use Area bullets and stray U+FFFD glyphs.
_JUNK_RE = re.compile("[-�]")
_WS_RE = re.compile(r"[ \t]+")


def repair_thai(text: str) -> str:
    """Repair the Thai sara-am extraction artifacts and drop unmapped glyphs."""
    text = _AM_TONE_RE.sub("\\1ำ", text)
    text = _AM_BEFORE_RE.sub("ำ", text)
    text = _AM_PLAIN_RE.sub("ำ", text)
    text = _JUNK_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def _kind_for(label: Any) -> str:
    name = str(getattr(label, "name", label) or "").lower()
    if "title" in name or "header" in name or "section" in name:
        return "heading"
    if "list" in name:
        return "list"
    if "table" in name:
        return "table"
    return "text"


class DoclingParser:
    def __init__(self, *, source_name: str | None = None, do_ocr: bool = True) -> None:
        self._source_name = source_name
        self._do_ocr = do_ocr
        self._converter: Any | None = None

    def _ensure_converter(self) -> Any:
        if self._converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                EasyOcrOptions,
                PdfPipelineOptions,
            )
            from docling.document_converter import DocumentConverter, PdfFormatOption

            pdf_opts = PdfPipelineOptions()  # type: ignore[call-arg]
            pdf_opts.do_ocr = self._do_ocr
            pdf_opts.do_table_structure = True
            # docling's default OCR languages are ['fr','de','es','en'] — without
            # Thai, scanned Thai PDFs (e.g. the สปสช. 2567 payment announcement,
            # which has no text layer) come out as garbage. EasyOCR supports Thai;
            # keep 'en' for the mixed Thai/English (ICD codes, ODS/MIS) content.
            pdf_opts.ocr_options = EasyOcrOptions(lang=["th", "en"])
            self._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts)
                }
            )
        return self._converter

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        from docling.datamodel.base_models import (  # type: ignore[attr-defined]
            DocumentStream,
        )

        converter = self._ensure_converter()
        stream = DocumentStream(name=filename, stream=io.BytesIO(content))
        result = converter.convert(stream)
        doc = result.document

        source = self._source_name or filename.rsplit(".", 1)[0]
        blocks_by_page: dict[int, list[ParsedBlock]] = {}

        for item, _level in doc.iterate_items():
            page_no = 1
            prov = getattr(item, "prov", None)
            if prov:
                page_no = getattr(prov[0], "page_no", 1)

            kind = _kind_for(getattr(item, "label", None))
            if kind == "table":
                text = self._table_markdown(item, doc)
            else:
                text = getattr(item, "text", "") or ""
            text = repair_thai(text)
            if not text:
                continue
            blocks_by_page.setdefault(page_no, []).append(ParsedBlock(kind, text))

        pages: list[ParsedPage] = []
        for page_no in sorted(blocks_by_page):
            blocks = blocks_by_page[page_no]
            pages.append(
                ParsedPage(
                    page=page_no,
                    text="\n".join(b.text for b in blocks),
                    blocks=blocks,
                )
            )

        if not pages:
            md = repair_thai(doc.export_to_markdown())
            pages = [ParsedPage(page=1, text=md, blocks=[ParsedBlock("text", md)])]

        return ParsedDocument(source=source, pages=pages)

    @staticmethod
    def _table_markdown(item: Any, doc: Any) -> str:
        exporter = getattr(item, "export_to_markdown", None)
        if exporter is not None:
            try:
                out = exporter(doc)
            except (TypeError, AttributeError):
                try:
                    out = exporter()
                except (TypeError, AttributeError):
                    out = None
            if out:
                return str(out)
        return str(getattr(item, "text", "") or "")
