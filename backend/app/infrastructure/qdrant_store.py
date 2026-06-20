"""Qdrant vector store adapter — hybrid (dense + sparse) retrieval with RRF.

Named vectors: "dense" (cosine) and "sparse". Category is a payload-indexed
field for fast filtering. Lazily imports qdrant_client.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from app.domain.entities import Chunk, EmbeddedChunk, Embedding, ScoredChunk


def _point_id(chunk_id: str) -> int:
    """Deterministic 63-bit point id from the chunk id.

    Deterministic (unlike the builtin hash(), which is salted per process) so a
    re-ingest overwrites the same point instead of creating near-duplicates, and
    wide enough that collisions are astronomically unlikely.
    """
    digest = hashlib.blake2b(chunk_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") >> 1


class QdrantVectorStore:
    def __init__(
        self,
        *,
        url: str,
        api_key: str | None = None,
        collection: str = "ods_chunks",
        dense_size: int = 1024,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._collection = collection
        self._dense_size = dense_size
        self._client: Any | None = None

    def _c(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self._url, api_key=self._api_key)
        return self._client

    def ensure_collection(self) -> None:
        from qdrant_client import models

        client = self._c()
        if client.collection_exists(self._collection):
            return
        client.create_collection(
            collection_name=self._collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=self._dense_size, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )
        for field in ("category", "department"):
            client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        from qdrant_client import models

        points = []
        for ec in chunks:
            vectors: dict[str, Any] = {"dense": ec.embedding.dense}
            if ec.embedding.sparse is not None:
                vectors["sparse"] = models.SparseVector(
                    indices=ec.embedding.sparse.indices,
                    values=ec.embedding.sparse.values,
                )
            points.append(
                models.PointStruct(
                    id=_point_id(ec.chunk.id),
                    vector=vectors,
                    payload={
                        "chunk_id": ec.chunk.id,
                        "text": ec.chunk.text,
                        "source": ec.chunk.source,
                        "page": ec.chunk.page,
                        "category": ec.chunk.category,
                        "department": ec.chunk.department,
                        "image": ec.chunk.image,
                    },
                )
            )
        self._c().upsert(collection_name=self._collection, points=points)

    def hybrid_search(
        self,
        query: Embedding,
        *,
        category: str | None,
        department: str | None = None,
        top_k: int,
    ) -> list[ScoredChunk]:
        from qdrant_client import models

        must: list[Any] = []
        if category is not None:
            must.append(
                models.FieldCondition(
                    key="category", match=models.MatchValue(value=category)
                )
            )
        if department is not None:
            must.append(
                models.FieldCondition(
                    key="department", match=models.MatchValue(value=department)
                )
            )
        flt = models.Filter(must=must) if must else None

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
