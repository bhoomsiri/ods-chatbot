"""Read-only vector store that restricts retrieval to the KG-comparison subset.

Wraps the production ``QdrantVectorStore`` and adds a ``source ∈ subset`` payload
filter to every hybrid search, so the vector RAG sees ONLY the subset documents
(the same corpus the GraphRAG index will be built from — fairness gate C/D).

Isolation: query + payload-filter only. Never upserts, deletes, or edits an
index. Lives in ``eval/kg_compare`` and imports the app adapter read-only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.entities import GENERAL_DEPARTMENT, Chunk, Embedding, ScoredChunk
from app.infrastructure.qdrant_store import QdrantVectorStore


class SubsetVectorStore(QdrantVectorStore):
    """QdrantVectorStore that always constrains results to ``sources``."""

    def __init__(self, *, sources: Sequence[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sources = list(sources)

    def hybrid_search(
        self,
        query: Embedding,
        *,
        category: str | None,
        department: str | None = None,
        top_k: int,
    ) -> list[ScoredChunk]:
        from qdrant_client import models

        must: list[Any] = [
            models.FieldCondition(
                key="source", match=models.MatchAny(any=self._sources)
            )
        ]
        if category is not None:
            must.append(
                models.FieldCondition(
                    key="category", match=models.MatchValue(value=category)
                )
            )
        if department is not None:
            dept_values = [department]
            if department != GENERAL_DEPARTMENT:
                dept_values.append(GENERAL_DEPARTMENT)
            must.append(
                models.FieldCondition(
                    key="department", match=models.MatchAny(any=dept_values)
                )
            )
        flt = models.Filter(must=must)

        prefetch = [
            models.Prefetch(query=query.dense, using="dense", limit=top_k, filter=flt)
        ]
        if query.sparse is not None:
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(
                        indices=query.sparse.indices, values=query.sparse.values
                    ),
                    using="sparse",
                    limit=top_k,
                    filter=flt,
                )
            )

        result = self._c().query_points(
            collection_name=self._collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )

        scored: list[ScoredChunk] = []
        for point in result.points:
            payload = point.payload or {}
            chunk = Chunk(
                id=str(payload.get("chunk_id", point.id)),
                text=str(payload.get("text", "")),
                source=str(payload.get("source", "")),
                page=payload.get("page"),
                category=payload.get("category"),
                department=payload.get("department"),
                image=payload.get("image"),
            )
            scored.append(ScoredChunk(chunk=chunk, score=float(point.score)))
        return scored
