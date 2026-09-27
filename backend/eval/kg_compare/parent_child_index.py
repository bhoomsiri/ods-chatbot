"""Hierarchical (Parent-Child) index over the SAME 3-doc subset, built with NO
LLM — the cost contrast against GraphRAG (~2.07M extraction tokens).

Design (chosen for this single-hop factual domain — stated so the report can cite it):
- PARENT = a large context block (~1650 chars) the LLM answers from, built by
  concatenating a document's chunks in page/position order (overlap-trimmed).
- CHILD  = a small ~350-char slice of a parent (50-char overlap) used only for
  retrieval precision. Query → child search → map back to parent.

The child embeddings (bge-m3 dense, the same embedder Qdrant uses) + the
child→parent map + parent texts are persisted to an ISOLATED file index under
``runs/kg_compare/hierarchical/`` — ``ods_chunks_v3`` is only ever read
(scroll + source filter), never written.

Run inside the backend container:
    docker compose exec backend python -m eval.kg_compare.parent_child_index
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.core.providers import get_embedder
from app.core.settings import get_settings
from eval.kg_compare.kg_index_builder import _CHUNK_RE, _merge_overlap

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "subset_config.json"
OUT_DIR = HERE.parent / "runs" / "kg_compare" / "hierarchical"

# Parent/child sizing (chars). Parent ~1.5-1.8k so the LLM gets a coherent block;
# child ~300-400 so retrieval matches on a focused span.
PARENT_TARGET = 1650
CHILD_SIZE = 350
CHILD_OVERLAP = 50


def _load_subset_ordered(
    *, url: str, api_key: str | None, collection: str, sources: list[str]
) -> dict[str, list[tuple[int, int, str]]]:
    """Scroll subset chunks, returning per-source [(page, idx, text)] sorted."""
    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=url, api_key=api_key)
    flt = models.Filter(
        must=[models.FieldCondition(key="source", match=models.MatchAny(any=sources))]
    )
    buckets: dict[str, list[tuple[int, int, str]]] = {s: [] for s in sources}
    offset: Any = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=flt,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            pay = p.payload or {}
            src = str(pay.get("source", ""))
            cid = str(pay.get("chunk_id", ""))
            m = _CHUNK_RE.match(cid)
            page = int(m.group("page")) if m else int(pay.get("page", 0) or 0)
            idx = int(m.group("idx")) if m else 0
            buckets.setdefault(src, []).append((page, idx, str(pay.get("text", ""))))
        if offset is None:
            break
    return {s: sorted(rows, key=lambda r: (r[0], r[1])) for s, rows in buckets.items()}


def _build_parents(
    rows: list[tuple[int, int, str]], source: str, start_id: int
) -> list[dict[str, Any]]:
    """Concatenate ordered chunks into ~PARENT_TARGET-char parents (page-tagged)."""
    parents: list[dict[str, Any]] = []
    text = ""
    page_start: int | None = None
    page_end: int | None = None
    pid = start_id

    def flush() -> None:
        nonlocal text, page_start, page_end, pid
        if text.strip():
            parents.append(
                {
                    "parent_id": f"P{pid}",
                    "source": source,
                    "page": page_start,
                    "page_end": page_end,
                    "text": text,
                }
            )
            pid += 1
        text, page_start, page_end = "", None, None

    for page, _idx, chunk_text in rows:
        if page_start is None:
            page_start = page
        page_end = page
        text = _merge_overlap(text, chunk_text)
        if len(text) >= PARENT_TARGET:
            flush()
    flush()
    return parents


def _split_children(parent_text: str) -> list[str]:
    """Sliding ~CHILD_SIZE window with CHILD_OVERLAP over a parent."""
    if len(parent_text) <= CHILD_SIZE:
        return [parent_text]
    step = CHILD_SIZE - CHILD_OVERLAP
    out: list[str] = []
    for start in range(0, len(parent_text), step):
        piece = parent_text[start : start + CHILD_SIZE]
        if piece.strip():
            out.append(piece)
        if start + CHILD_SIZE >= len(parent_text):
            break
    return out


def main() -> int:
    conf = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = conf["qdrant"]["subset_sources"]
    collection = conf["qdrant"]["collection"]
    s = get_settings()

    t0 = time.time()
    print(f"[1/4] scroll subset from {collection} ({len(sources)} sources, read-only)")
    ordered = _load_subset_ordered(
        url=s.qdrant_url, api_key=s.qdrant_api_key, collection=collection, sources=sources
    )

    print("[2/4] build parents + children (no LLM)")
    parents: list[dict[str, Any]] = []
    for src in sources:
        parents.extend(_build_parents(ordered.get(src, []), src, start_id=len(parents)))

    children: list[dict[str, Any]] = []  # {child_id, parent_id, text}
    for parent in parents:
        for j, ctext in enumerate(_split_children(parent["text"])):
            children.append(
                {
                    "child_id": f"{parent['parent_id']}c{j}",
                    "parent_id": parent["parent_id"],
                    "text": ctext,
                }
            )
    print(f"      parents={len(parents)}  children={len(children)}")

    print("[3/4] embed children with bge-m3 (dense)")
    embedder = get_embedder()
    embs = embedder.embed_documents([c["text"] for c in children])
    vecs = np.asarray([e.dense for e in embs], dtype=np.float32)

    print("[4/4] persist isolated index + build stats")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT_DIR / "pc_index.npz", child_vecs=vecs)
    (OUT_DIR / "pc_index.json").write_text(
        json.dumps(
            {
                "children": children,
                "parents": {p["parent_id"]: p for p in parents},
                "child_order": [c["child_id"] for c in children],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    build_seconds = round(time.time() - t0, 1)
    parent_chars = [len(p["text"]) for p in parents]
    child_chars = [len(c["text"]) for c in children]
    stats = {
        "method": "hierarchical_parent_child",
        "collection": collection,
        "subset_sources": sources,
        "n_parents": len(parents),
        "n_children": len(children),
        "parent_target_chars": PARENT_TARGET,
        "child_size_chars": CHILD_SIZE,
        "child_overlap_chars": CHILD_OVERLAP,
        "avg_parent_chars": round(float(np.mean(parent_chars)), 1) if parent_chars else 0,
        "avg_child_chars": round(float(np.mean(child_chars)), 1) if child_chars else 0,
        "build_seconds": build_seconds,
        # The cost-axis headline: structuring retrieval needs ZERO LLM calls,
        # unlike GraphRAG's entity/relation extraction (~2.07M tokens).
        "index_llm_calls": 0,
        "index_tokens_est": 0,
        "embedding_model": "bge-m3 (dense, 1024)",
    }
    (OUT_DIR / "pc_build_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n=== Parent-Child index built in {build_seconds}s ===")
    print(
        f"parents={len(parents)} children={len(children)} "
        f"avg_parent={stats['avg_parent_chars']}c avg_child={stats['avg_child_chars']}c"
    )
    print(f"index -> {OUT_DIR}  (LLM calls = 0, tokens = 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
