"""LLM + embedding functions for LightRAG, bound to the SAME models the vector
RAG uses — fairness gates A/B (equal answer model + equal embeddings).

- LLM  = Gemini ``gemini-2.5-flash`` via ``google.generativeai`` (the app's SDK).
         Used by LightRAG for BOTH entity/relation extraction and answer
         generation. A call/token counter is attached for the cost axis (§4).
- Embed = the app's ``BGEM3Embedder`` dense vectors (1024-dim, bge-m3), the same
          embedder Qdrant was built with.

Isolation: new code in ``kg_compare``; imports app adapters read-only.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.infrastructure.bge_m3_embedder import BGEM3Embedder

# Rough chars-per-token for Thai; RELATIVE cost only (same constant as the
# existing generation harness so the two experiments are comparable).
CHARS_PER_TOKEN = 3.0


@dataclass
class LlmCostMeter:
    """Counts LightRAG's LLM usage so Phase 4 can price the graph build."""

    calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    per_call: list[dict[str, int]] = field(default_factory=list)

    def record(self, prompt: str, completion: str) -> None:
        self.calls += 1
        self.prompt_chars += len(prompt)
        self.completion_chars += len(completion)
        self.per_call.append(
            {"prompt_chars": len(prompt), "completion_chars": len(completion)}
        )

    def summary(self) -> dict[str, float]:
        return {
            "llm_calls": self.calls,
            "prompt_chars": self.prompt_chars,
            "completion_chars": self.completion_chars,
            "prompt_tokens_est": round(self.prompt_chars / CHARS_PER_TOKEN, 1),
            "completion_tokens_est": round(self.completion_chars / CHARS_PER_TOKEN, 1),
            "total_tokens_est": round(
                (self.prompt_chars + self.completion_chars) / CHARS_PER_TOKEN, 1
            ),
        }


def make_gemini_llm_func(
    *, api_key: str, model: str = "gemini-2.5-flash", temperature: float = 0.1
) -> tuple[Any, LlmCostMeter]:
    """Return ``(llm_model_func, meter)`` for LightRAG.

    Signature matches LightRAG's contract:
    ``async (prompt, system_prompt=None, history_messages=[], **kwargs) -> str``.
    No app safety system prompt is injected — LightRAG supplies its own
    extraction / RAG prompts, and biasing them would corrupt the comparison.
    """
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    meter = LlmCostMeter()

    async def llm_model_func(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        keyword_extraction: bool = False,
        **kwargs: Any,
    ) -> str:
        parts: list[str] = []
        if system_prompt:
            parts.append(system_prompt)
        for msg in history_messages or []:
            role = msg.get("role", "")
            parts.append(f"{role}: {msg.get('content', '')}")
        parts.append(prompt)
        full = "\n\n".join(parts)

        gm = genai.GenerativeModel(model)
        cfg = genai.types.GenerationConfig(temperature=temperature)

        def _call() -> str:
            resp = gm.generate_content(full, generation_config=cfg)
            try:
                return resp.text or ""
            except (ValueError, AttributeError):
                return ""

        text = await asyncio.to_thread(_call)
        meter.record(full, text)
        return text

    return llm_model_func, meter


def make_bge_embedding_func(*, use_fp16: bool = True) -> tuple[Any, BGEM3Embedder]:
    """Return an async embedding callable (bge-m3 dense, 1024-dim) for LightRAG.

    Reuses the app embedder so GraphRAG and the vector store share identical
    vectors. Wrapped in ``EmbeddingFunc`` by the caller.
    """
    embedder = BGEM3Embedder(use_fp16=use_fp16)

    async def embed(texts: list[str]) -> np.ndarray:
        def _encode() -> np.ndarray:
            embs = embedder.embed_documents(texts)
            return np.array([e.dense for e in embs], dtype=np.float32)

        return await asyncio.to_thread(_encode)

    return embed, embedder
