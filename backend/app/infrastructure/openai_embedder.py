"""OpenAI embedder adapter — dense vectors only (no sparse).

Drop-in alternative to bge-m3 for the dense channel; selected via settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.entities import Embedding


class OpenAIEmbedder:
    def __init__(self, *, api_key: str, model: str = "text-embedding-3-large") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def _embed(self, texts: Sequence[str]) -> list[Embedding]:
        client = self._ensure_client()
        resp = client.embeddings.create(model=self._model, input=list(texts))
        return [Embedding(dense=list(item.embedding)) for item in resp.data]

    def embed_query(self, text: str) -> Embedding:
        return self._embed([text])[0]

    def embed_documents(self, texts: Sequence[str]) -> list[Embedding]:
        return self._embed(texts)
