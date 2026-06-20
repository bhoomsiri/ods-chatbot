"""bge-reranker-v2-m3 cross-encoder reranker adapter.

Lazily imports FlagEmbedding so unit tests / fake mode don't need torch.

Device/precision is auto-selected (use_fp16=None): on a CUDA GPU we use fp16
(the real speedup — RTX 3070 reranks 20 pairs in well under a second); on CPU
fp16 is emulated and gives no speedup (measured 19.5s vs 19.1s), so we use fp32
and instead set the thread count to claw back latency.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.entities import ScoredChunk


class BGEReranker:
    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        use_fp16: bool | None = None,
        num_threads: int = 0,
    ) -> None:
        self._model_name = model_name
        self._use_fp16 = use_fp16  # None = auto (fp16 on GPU, fp32 on CPU)
        self._num_threads = num_threads
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            import torch

            cuda = torch.cuda.is_available()
            if not cuda and self._num_threads > 0:
                torch.set_num_threads(self._num_threads)
            fp16 = cuda if self._use_fp16 is None else self._use_fp16
            from FlagEmbedding import FlagReranker

            self._model = FlagReranker(self._model_name, use_fp16=fp16)
        return self._model

    def rerank(
        self, query: str, chunks: Sequence[ScoredChunk], *, top_k: int
    ) -> list[ScoredChunk]:
        if not chunks:
            return []
        model = self._ensure_model()
        pairs = [[query, c.chunk.text] for c in chunks]
        raw = model.compute_score(pairs, normalize=True)
        scores = raw if isinstance(raw, list) else [raw]
        rescored = [
            ScoredChunk(chunk=c.chunk, score=float(s))
            for c, s in zip(chunks, scores, strict=True)
        ]
        rescored.sort(key=lambda s: s.score, reverse=True)
        return rescored[:top_k]
