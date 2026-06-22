"""Batch corpus ingest for the ODS knowledge base.

Walks the reorganised corpus folder and ingests it into the configured Qdrant
collection (set ODS_QDRANT_COLLECTION to build a fresh "blue-green" collection
without touching the live one). Three things this script owns that the per-file
/api/ingest endpoint does not:

1. Dedup docx/pdf pairs — prefer the .docx (clean Thai unicode) when it has real
   extractable text; if the .docx is image-only (no text, docling can't OCR
   images embedded in DOCX) fall back to its .pdf sibling. A text-empty file with
   no sibling is skipped (e.g. EGD.docx — its content is covered by the separate
   "การส่องกล้องตรวจ..." PDF). PDFs are never skipped on this cheap pre-check:
   an image-only PDF (e.g. the สปสช. 2567 announcement) is rescued by docling OCR.

2. Department from the folder — the corpus encodes department in its folder
   layout far more reliably than guessing from text. Consent subfolders map
   directly; VDO/แผ่นพับ are per-procedure so map by filename keyword; everything
   else (central manuals, general consent) is the ภาพรวม/ไม่ระบุ bucket. The
   classifier still fills the content *category* per chunk.

Run inside the backend container, e.g.:
    docker compose exec -e ODS_QDRANT_COLLECTION=ods_chunks_v3 \
        backend python scripts/ingest_corpus.py /tmp/corpus
"""

from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from app.core.providers import (
    get_chunker,
    get_classifier,
    get_embedder,
    get_store,
)
from app.usecases.ingest import IngestDocument

# --- text pre-measure (cheap, no docling) --------------------------------

_THAI_RE = re.compile(r"[฀-๿]")
_TAG_RE = re.compile(r"<[^>]+>")
_MIN_THAI = 150  # below this a docx is treated as image-only


def _docx_thai(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as z:
            xmls = [
                n
                for n in z.namelist()
                if n.startswith("word/") and n.endswith(".xml") and "document" in n
            ]
            text = "".join(_TAG_RE.sub("", z.read(n).decode("utf-8", "ignore")) for n in xmls)
        return len(_THAI_RE.findall(text))
    except Exception:
        return 0


def _pdf_thai(path: Path, max_pages: int = 8) -> int:
    """Thai chars in the PDF text layer (sampled). 0 → scanned/image-only.

    Uses pypdfium2 — docling's own PDF backend — so this sees exactly the text
    layer docling would extract. (pypdf's extract_text returns nothing for these
    files inside the container, which would mislabel every PDF as scanned.)
    """
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        n = min(max_pages, len(pdf))
        text = ""
        for i in range(n):
            textpage = pdf[i].get_textpage()
            text += textpage.get_text_bounded()
        return len(_THAI_RE.findall(text))
    except Exception:
        return 0


def needs_ocr(path: Path) -> bool:
    """OCR only image-only PDFs (e.g. the scanned 2567 announcement). Text-layer
    PDFs and DOCX are parsed without OCR — running easyocr on every page of the
    150+ page manuals is what OOM-killed the first run."""
    if path.suffix.lower() != ".pdf":
        return False
    return _pdf_thai(path) < _MIN_THAI


# --- department resolution -----------------------------------------------

_CONSENT_DEPT = {
    "จักษุ": "จักษุ",
    "นรีเวชกรรม": "นรีเวช",
    "ศัยลยกรรม": "ศัลยกรรมทั่วไป",  # folder name carries the user's typo
    "ศัลยกรรม": "ศัลยกรรมทั่วไป",
    "ศัลยกรรมหลอดเลือด": "หลอดเลือด",
    "โสต ศอ นาสิก": "โสต ศอ นาสิก",
}

# Per-procedure keywords for VDO/แผ่นพับ (filename-based). GI endoscopy is folded
# into ศัลยกรรมทั่วไป to match the consent folders. Order matters: more specific
# departments are checked before general surgery.
_KEYWORD_DEPT: list[tuple[tuple[str, ...], str]] = [
    (("ต้อเนื้อ", "ต้อ", "เปลือกตา", "blephar", "pterygium", "จักษุ"), "จักษุ"),
    (
        ("ขูดมดลูก", "โพรงมดลูก", "ปากมดลูก", "leep", "hysteroscop", "นรีเวช", "d&c", "มดลูก"),
        "นรีเวช",
    ),
    (("หลอดเลือด", "avf", "avg", "ฟอกไต"), "หลอดเลือด"),
    (("โสต", "tympanoplasty", "หู คอ จมูก"), "โสต ศอ นาสิก"),
    (
        (
            "ไส้เลื่อน", "hernia", "ริดสีดวง", "hemorrhoid", "นิ่ว", "ถุงน้ำดี",
            "cholecystectomy", "lc", "colono", "gastro", "ส่องกล้อง", "ลำไส้",
            "ทางเดินอาหาร", "egd",
        ),
        "ศัลยกรรมทั่วไป",
    ),
]

GENERAL = "ภาพรวม/ไม่ระบุ"

# Readable folder tag used to disambiguate two files that share a stem (e.g.
# แผ่นพับ/LC.docx and ใบยินยอม/.../LC.docx). Without this they'd produce the same
# `source` → identical chunk ids → one silently overwrites the other in Qdrant.
_FOLDER_LABEL = {
    "VDO": "VDO",
    "แผ่นพับ": "แผ่นพับ",
    "ใบยินยอมผ่าตัด": "ใบยินยอม",
    "คู่มือ ODS": "คู่มือ ODS",
}


def source_label(rel: Path, stem_counts: Counter[str]) -> str:
    """Unique, citation-friendly source name. Plain stem unless that stem is
    shared by another file, in which case the folder is appended."""
    stem = rel.stem
    if stem_counts[stem.lower()] > 1:
        top = rel.parts[0] if rel.parts else ""
        return f"{stem} [{_FOLDER_LABEL.get(top, top)}]"
    return stem


def resolve_department(rel: Path) -> str | None:
    """Folder/filename → department. None means 'let the classifier decide'."""
    parts = rel.parts
    top = parts[0] if parts else ""

    if top == "ใบยินยอมผ่าตัด":
        # consent in a department subfolder → that department; loose files at the
        # folder root (general consent, workload, patient selection) → general.
        if len(parts) >= 3:
            return _CONSENT_DEPT.get(parts[1], GENERAL)
        return GENERAL

    if top == "คู่มือ ODS":
        return GENERAL  # central/national manuals + the 2567 announcement

    if top in ("VDO", "แผ่นพับ"):
        stem = rel.stem.lower()
        for keywords, dept in _KEYWORD_DEPT:
            if any(k in stem for k in keywords):
                return dept
        return None  # e.g. "ขั้นตอนการรับบริการ ODS" — classifier → ภาพรวม

    return None


# --- file selection (dedup) ----------------------------------------------


def select_files(root: Path) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Return (files_to_ingest, skipped[(path, reason)])."""
    all_files = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in (".docx", ".pdf")
        and not p.name.startswith("~$")
    ]
    groups: dict[tuple[str, str], list[Path]] = {}
    for p in all_files:
        groups.setdefault((str(p.parent), p.stem.lower()), []).append(p)

    chosen: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for files in groups.values():
        docx = next((f for f in files if f.suffix.lower() == ".docx"), None)
        pdf = next((f for f in files if f.suffix.lower() == ".pdf"), None)
        if docx is not None and _docx_thai(docx) >= _MIN_THAI:
            chosen.append(docx)
        elif pdf is not None:
            chosen.append(pdf)  # text-layer PDF, or image PDF rescued by OCR
            if docx is not None:
                skipped.append((docx, "image-only docx → used pdf sibling"))
        elif docx is not None:
            skipped.append((docx, "image-only docx, no pdf sibling → skipped"))
    return sorted(chosen), skipped


# --- resume support ------------------------------------------------------


def existing_sources(store: object) -> set[str]:
    """Sources already present in the collection (so a re-run can resume after a
    crash without redoing finished files)."""
    client = store._c()  # type: ignore[attr-defined]
    collection = store._collection  # type: ignore[attr-defined]
    sources: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=512,
            with_payload=["source"],
            with_vectors=False,
            offset=offset,
        )
        for p in points:
            src = (p.payload or {}).get("source")
            if src:
                sources.add(str(src))
        if offset is None:
            break
    return sources


# --- main ----------------------------------------------------------------


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/corpus")
    if not root.is_dir():
        raise SystemExit(f"corpus root not found: {root}")

    # docling's OCR pipeline is heavy; build it once but only route image-only
    # PDFs through it. Text-layer files use a no-OCR parser (fast + low memory).
    from app.infrastructure.docling_parser import DoclingParser

    chunker = get_chunker()
    embedder = get_embedder()
    store = get_store()
    classifier = get_classifier()
    store.ensure_collection()  # type: ignore[attr-defined]

    def make_ingest(do_ocr: bool) -> IngestDocument:
        return IngestDocument(
            parser=DoclingParser(do_ocr=do_ocr),
            chunker=chunker,
            embedder=embedder,
            store=store,
            classifier=classifier,
        )

    ingest_ocr = make_ingest(True)
    ingest_plain = make_ingest(False)

    done = existing_sources(store)
    chosen, skipped = select_files(root)
    stem_counts: Counter[str] = Counter(p.stem.lower() for p in chosen)
    print(f"corpus: {root}")
    print(f"selected {len(chosen)} files, skipped {len(skipped)}, already-done {len(done)}\n")
    for p, reason in skipped:
        print(f"  SKIP  {p.relative_to(root)}  — {reason}")
    print()

    total = 0
    for p in chosen:
        rel = p.relative_to(root)
        # `source` is how DoclingParser labels the doc (from the filename stem)
        # and how `done` matches for resume — keep them in lockstep.
        source = source_label(rel, stem_counts)
        if source in done:
            print(f"  ---- skip (already ingested)  {rel}")
            continue
        dept = resolve_department(rel)
        ocr = needs_ocr(p)
        ingest = ingest_ocr if ocr else ingest_plain
        try:
            report = ingest.execute(
                p.read_bytes(), f"{source}{p.suffix}", department=dept
            )
        except Exception as e:  # keep going; report the failure
            print(f"  ERROR {rel}  — {type(e).__name__}: {e}")
            continue
        total += report.chunks
        tag = f"{dept or 'LLM'}{', OCR' if ocr else ''}"
        print(f"  {report.chunks:>4} chunks  [{tag}]  {rel}")

    print(f"\nDONE: +{total} chunks this run")


if __name__ == "__main__":
    main()
