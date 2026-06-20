"""bge-m3 embedder adapter — dense + sparse (lexical) vectors.

Lazily imports FlagEmbedding so unit tests / fake mode don't need torch.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.entities import Embedding, SparseVector


class BGEM3Embedder:
    def __init__(self, *, model_name: str = "BAAI/bge-m3", use_fp16: bool = True) -> None:
        self._model_name = model_name
        self._use_fp16 = use_fp16
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self._model_name, use_fp16=self._use_fp16)
        return self._model

    def _encode(self, texts: Sequence[str]) -> list[Embedding]:
        model = self._ensure_model()
        out = model.encode(
            list(texts),
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = out["dense_vecs"]
        lexical = out["lexical_weights"]
        embeddings: list[Embedding] = []
        for i in range(len(texts)):
            weights: dict[Any, float] = dict(lexical[i])
            sparse = SparseVector(
                indices=[int(k) for k in weights],
                values=[float(v) for v in weights.values()],
            )
            embeddings.append(
                Embedding(dense=[float(x) for x in dense[i]], sparse=sparse)
            )
        return embeddings

    def embed_query(self, text: str) -> Embedding:
        return self._encode([text])[0]

    def embed_documents(self, texts: Sequence[str]) -> list[Embedding]:
        return self._encode(texts)
