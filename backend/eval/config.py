"""Experiment configuration schema (pydantic v2).

One ``ExperimentConfig`` = one OFAT cell: every knob held at baseline except the
one under test. ``parse_configs`` validates already-parsed dicts (so unit tests
need no YAML dependency); ``load_configs`` is the thin YAML file wrapper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EvalKind = Literal["retrieval", "generation", "rejection"]
ConfigKind = Literal["runtime", "index"]


def _default_eval() -> list[EvalKind]:
    return ["retrieval"]


class IngestParams(BaseModel):
    """Re-index knobs (used only when ``kind == 'index'``)."""

    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(default=800, gt=0)
    overlap: int = Field(default=120, ge=0)

    @model_validator(mode="after")
    def _overlap_below_size(self) -> IngestParams:
        if self.overlap >= self.chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        return self


class QueryParams(BaseModel):
    """Runtime knobs. Defaults are the production baseline so a sweep config
    only needs to override the single knob under test (OFAT)."""

    model_config = ConfigDict(extra="forbid")

    retrieval_top_k: int = Field(default=20, gt=0)
    rerank_candidates: int = Field(default=20, gt=0)
    rerank_top_k: int = Field(default=8, gt=0)
    score_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    answer_model: str = "gemini-2.5-flash"
    reformulate: bool = True
    # Query-transform model (E10). Default is the production Flash-Lite so every
    # existing config keeps its exact behaviour; only E10 overrides it to Flash.
    reformulate_model: str = "gemini-2.5-flash-lite"
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def _topk_consistency(self) -> QueryParams:
        if self.rerank_top_k > self.rerank_candidates:
            raise ValueError("rerank_top_k must be <= rerank_candidates")
        return self


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    knob: str = ""  # OFAT group label, e.g. "E3:retrieval_top_k"
    kind: ConfigKind = "runtime"
    collection: str = "ods_chunks_v3"
    ingest: IngestParams = Field(default_factory=IngestParams)
    query: QueryParams = Field(default_factory=QueryParams)
    eval: list[EvalKind] = Field(default_factory=_default_eval)
    repeats: int = Field(default=1, ge=1)

    @field_validator("eval")
    @classmethod
    def _non_empty_unique(cls, v: list[EvalKind]) -> list[EvalKind]:
        if not v:
            raise ValueError("eval must list at least one metric kind")
        if len(set(v)) != len(v):
            raise ValueError("eval kinds must be unique")
        return v


class ConfigSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configs: list[ExperimentConfig]

    @field_validator("configs")
    @classmethod
    def _unique_names(cls, v: list[ExperimentConfig]) -> list[ExperimentConfig]:
        names = [c.name for c in v]
        if len(set(names)) != len(names):
            raise ValueError("config names must be unique")
        return v


def parse_configs(data: Any) -> list[ExperimentConfig]:
    """Validate a parsed mapping/list into ExperimentConfigs (no file I/O)."""
    if isinstance(data, list):
        data = {"configs": data}
    return ConfigSuite.model_validate(data).configs


def load_configs(path: str | Path) -> list[ExperimentConfig]:
    """Load + validate configs.yaml. Imports PyYAML lazily."""
    import yaml  # type: ignore[import-untyped]

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return parse_configs(raw)


def select(
    configs: list[ExperimentConfig], *, eval_kind: EvalKind, kind: ConfigKind
) -> list[ExperimentConfig]:
    """Filter to configs that request ``eval_kind`` and match ``kind``."""
    return [c for c in configs if eval_kind in c.eval and c.kind == kind]
