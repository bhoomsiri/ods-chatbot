"""IngestDocument use case — offline ingestion pipeline.

parse -> structure-aware chunk -> (classify category/department) -> embed
-> upsert into the vector store.
"""

from __future__ import annotations

import dataclasses

from app.domain.entities import EmbeddedChunk, IngestReport
from app.domain.ports import (
    ChunkClassifier,
    Chunker,
    DocumentParser,
    Embedder,
    VectorStore,
)


class IngestDocument:
    def __init__(
        self,
        *,
        parser: DocumentParser,
        chunker: Chunker,
        embedder: Embedder,
        store: VectorStore,
        classifier: ChunkClassifier | None = None,
    ) -> None:
        self._parser = parser
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._classifier = classifier

    def execute(
        self, content: bytes, filename: str, *, category: str | None = None
    ) -> IngestReport:
        document = self._parser.parse(content, filename)
        chunks = self._chunker.chunk(document, category=category)
        if not chunks:
            return IngestReport(filename=filename, chunks=0)

        # Tag each chunk with content category + surgical department.
        if self._classifier is not None:
            tags = self._classifier.classify([c.text for c in chunks])
            chunks = [
                dataclasses.replace(c, category=t.category, department=t.department)
                for c, t in zip(chunks, tags, strict=True)
            ]

        embeddings = self._embedder.embed_documents([c.text for c in chunks])
        embedded = [
            EmbeddedChunk(chunk=chunk, embedding=emb)
            for chunk, emb in zip(chunks, embeddings, strict=True)
        ]
        self._store.upsert(embedded)
        return IngestReport(filename=filename, chunks=len(chunks))
