"""Application settings (pydantic-settings v2)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ODS_", extra="ignore")

    app_name: str = "ODS Chatbot API"
    environment: Literal["dev", "prod", "test"] = "dev"

    # When true, wire in-memory fakes instead of real services. Lets the API
    # boot with no Qdrant / models present (graceful degradation, demos, tests).
    use_fakes: bool = True

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Vector store
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "ods_chunks"

    # Embeddings
    embedder: Literal["bge_m3", "openai"] = "bge_m3"
    embedding_dim: int = 1024
    openai_api_key: str | None = None
    openai_embed_model: str = "text-embedding-3-large"

    # Parsing
    # OCR on: image-only/scanned pages (e.g. the EGD brochure) have no text layer
    # and would otherwise be lost. docling keeps the existing text layer and only
    # OCRs bitmap regions, and OCR runs on the GPU, so the cost is acceptable.
    docling_ocr: bool = True

    # Reranker
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # CPU torch threads for the cross-encoder. 0 = leave torch default (physical
    # cores). On a 12-thread CPU, 10 is the measured sweet spot (HT contention
    # makes 12 slightly slower). Ignored on GPU.
    torch_num_threads: int = 10

    # LLM (Gemini)
    gemini_api_key: str | None = None
    gemini_answer_model: str = "gemini-2.5-pro"
    gemini_reformulate_model: str = "gemini-2.5-flash-lite"
    answer_temperature: float = 0.1

    # Retrieval
    retrieval_top_k: int = 20
    rerank_candidates: int = 12
    rerank_top_k: int = 5
    score_threshold: float = 0.3


@lru_cache
def get_settings() -> Settings:
    return Settings()
