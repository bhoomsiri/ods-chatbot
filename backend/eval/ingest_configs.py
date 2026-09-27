"""Phase 3 — build a Qdrant collection per (chunk_size, overlap) config.

Parses the corpus ONCE (the expensive docling step) and re-chunks/embeds/upserts
it for each ``kind: index`` config into its own collection (e.g. ods_eval_c256),
so E1/E2 can be measured with the same retrieval metrics as phase 1 without
touching the live ods_chunks_v3.

Reuses the production corpus walk + dedup + department resolution from
``scripts.ingest_corpus`` and the real parser/embedder/chunker — only the chunk
geometry changes per config. The chunk *category* classifier is skipped on
purpose: the eval retrieves with no category/department filter, so content tags
do not affect the measured ranking, and skipping it avoids a per-config Gemini
bill.

Run in the demo-down window (heavy GPU: docling + embeddings):
    python -m eval.ingest_configs /app/_corpus
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.providers import get_embedder
from app.domain.entities import Chunk, EmbeddedChunk, ParsedDocument
from app.infrastructure.chunker import MetadataAwareChunker
from app.infrastructure.docling_parser import DoclingParser
from eval.config import ExperimentConfig, load_configs, select
from eval.pipeline import build_store
from scripts.ingest_corpus import (
    needs_ocr,
    resolve_department,
    select_files,
    source_label,
)

CONFIGS_PATH = Path(__file__).resolve().parent / "configs.yaml"


@dataclass(frozen=True)
class ParsedDoc:
    document: ParsedDocument
    department: str | None


def parse_corpus(root: Path) -> list[ParsedDoc]:
    """Parse every selected corpus file once (OCR only image-only PDFs)."""
    parser_ocr = DoclingParser(do_ocr=True)
    parser_plain = DoclingParser(do_ocr=False)
    chosen, skipped = select_files(root)
    stem_counts: Counter[str] = Counter(p.stem.lower() for p in chosen)
    print(f"corpus: {root} | {len(chosen)} files, {len(skipped)} skipped")

    docs: list[ParsedDoc] = []
    for p in chosen:
        rel = p.relative_to(root)
        source = source_label(rel, stem_counts)
        dept = resolve_department(rel)
        parser = parser_ocr if needs_ocr(p) else parser_plain
        try:
            document = parser.parse(p.read_bytes(), f"{source}{p.suffix}")
        except Exception as e:  # noqa: BLE001 - keep going, report
            print(f"  ERROR parse {rel} — {type(e).__name__}: {e}")
            continue
        docs.append(ParsedDoc(document=document, department=dept))
        print(f"  parsed {rel}")
    return docs


def build_collection(cfg: ExperimentConfig, docs: list[ParsedDoc]) -> int:
    """Re-chunk the parsed docs at this config's geometry and upsert."""
    chunker = MetadataAwareChunker(
        chunk_size=cfg.ingest.chunk_size, overlap=cfg.ingest.overlap
    )
    embedder = get_embedder()
    store = build_store(cfg.collection)
    store.ensure_collection()

    total = 0
    for pd in docs:
        chunks: list[Chunk] = chunker.chunk(pd.document, department=pd.department)
        if not chunks:
            continue
        embeddings = embedder.embed_documents([c.text for c in chunks])
        store.upsert(
            [
                EmbeddedChunk(chunk=c, embedding=e)
                for c, e in zip(chunks, embeddings, strict=True)
            ]
        )
        total += len(chunks)
    return total


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-3 re-index per chunk config")
    parser.add_argument("root", nargs="?", default="/app/_corpus")
    parser.add_argument("--configs", default=str(CONFIGS_PATH))
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"corpus root not found: {root}")
        return 1

    configs = select(load_configs(args.configs), eval_kind="retrieval", kind="index")
    if args.only:
        wanted = set(args.only)
        configs = [c for c in configs if c.name in wanted]
    if not configs:
        print("no index configs to build")
        return 1

    docs = parse_corpus(root)
    print(f"\nparsed {len(docs)} docs; building {len(configs)} collections\n")
    for cfg in configs:
        n = build_collection(cfg, docs)
        print(
            f"  [{cfg.name}] {cfg.collection} "
            f"chunk={cfg.ingest.chunk_size}/overlap={cfg.ingest.overlap} -> {n} chunks"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
