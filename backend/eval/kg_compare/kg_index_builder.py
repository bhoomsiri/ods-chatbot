"""Build a LightRAG knowledge graph over the 3-doc subset (fairness gate D:
same corpus as the vector RAG).

Corpus source = the exact chunk texts already in ``ods_chunks_v3`` (read-only
scroll with a ``source`` filter), reconstructed per document into continuous
text (overlap-trimmed) so LightRAG can extract cross-chunk relations. We feed
the SAME information the vector store holds — no re-parsing of original files.

Records index time, LLM extraction cost, and node/edge counts for the cost axis
(§4), and dumps an entity/relation sample for the Thai quality gate (§6.5-C).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CHUNK_RE = re.compile(r"^(?P<src>.*)::p(?P<page>\d+)::(?P<idx>\d+)$")


@dataclass
class SourceDoc:
    source: str
    text: str
    n_chunks: int
    n_chars: int


def _merge_overlap(acc: str, nxt: str, max_overlap: int = 400) -> str:
    """Append ``nxt`` to ``acc``, trimming the largest shared boundary (the
    chunker's overlap window) so reconstructed text isn't duplicated."""
    if not acc:
        return nxt
    limit = min(len(acc), len(nxt), max_overlap)
    for k in range(limit, 0, -1):
        if acc[-k:] == nxt[:k]:
            return acc + nxt[k:]
    return acc + "\n" + nxt


def load_subset_docs(
    *, url: str, api_key: str | None, collection: str, sources: list[str]
) -> list[SourceDoc]:
    """Scroll the subset chunks and reconstruct one continuous text per source."""
    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=url, api_key=api_key)
    flt = models.Filter(
        must=[models.FieldCondition(key="source", match=models.MatchAny(any=sources))]
    )
    # source -> list[(page, idx, text)]
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

    docs: list[SourceDoc] = []
    for src in sources:
        rows = sorted(buckets.get(src, []), key=lambda r: (r[0], r[1]))
        text = ""
        for _, _, chunk_text in rows:
            text = _merge_overlap(text, chunk_text)
        docs.append(
            SourceDoc(source=src, text=text, n_chunks=len(rows), n_chars=len(text))
        )
    return docs


def graph_stats(working_dir: Path) -> dict[str, Any]:
    """Count nodes/edges and sample entities/relations from the built graph."""
    import networkx as nx

    gml = next(working_dir.glob("*.graphml"), None)
    if gml is None:
        return {"n_nodes": 0, "n_edges": 0, "sample_entities": [], "sample_relations": []}
    g = nx.read_graphml(gml)
    ents = []
    for node, data in list(g.nodes(data=True))[:25]:
        ents.append(
            {
                "entity": str(node),
                "type": data.get("entity_type", ""),
                "description": (data.get("description", "") or "")[:200],
            }
        )
    rels = []
    for u, v, data in list(g.edges(data=True))[:25]:
        rels.append(
            {
                "src": str(u),
                "dst": str(v),
                "keywords": data.get("keywords", ""),
                "description": (data.get("description", "") or "")[:200],
            }
        )
    return {
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "graphml": gml.name,
        "sample_entities": ents,
        "sample_relations": rels,
    }
