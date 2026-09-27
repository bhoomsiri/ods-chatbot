"""Schema validation for the ablation config (no YAML dependency)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.config import parse_configs, select


def test_minimal_config_uses_baseline_defaults() -> None:
    [cfg] = parse_configs([{"name": "baseline"}])
    assert cfg.kind == "runtime"
    assert cfg.collection == "ods_chunks_v3"
    assert cfg.query.retrieval_top_k == 20
    assert cfg.query.rerank_top_k == 8
    assert cfg.query.score_threshold == 0.3
    assert cfg.eval == ["retrieval"]


def test_reformulate_model_defaults_to_flash_lite() -> None:
    # Default must stay Flash-Lite so every existing config keeps its behaviour;
    # only E10 overrides it.
    [cfg] = parse_configs([{"name": "baseline"}])
    assert cfg.query.reformulate_model == "gemini-2.5-flash-lite"


def test_reformulate_model_override_parses() -> None:
    [cfg] = parse_configs(
        [{"name": "E10", "query": {"reformulate_model": "gemini-2.5-flash"}}]
    )
    assert cfg.query.reformulate_model == "gemini-2.5-flash"
    # overriding the model must not flip the reformulate switch off
    assert cfg.query.reformulate is True


def test_duplicate_names_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_configs([{"name": "dup"}, {"name": "dup"}])


def test_overlap_must_be_below_chunk_size() -> None:
    with pytest.raises(ValidationError):
        parse_configs(
            [{"name": "x", "kind": "index", "ingest": {"chunk_size": 256, "overlap": 256}}]
        )


def test_rerank_top_k_cannot_exceed_candidates() -> None:
    with pytest.raises(ValidationError):
        parse_configs(
            [{"name": "x", "query": {"rerank_candidates": 5, "rerank_top_k": 8}}]
        )


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_configs([{"name": "x", "nope": 1}])


def test_empty_eval_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_configs([{"name": "x", "eval": []}])


def test_select_filters_by_kind_and_eval() -> None:
    cfgs = parse_configs(
        [
            {"name": "r", "kind": "runtime", "eval": ["retrieval"]},
            {"name": "g", "kind": "runtime", "eval": ["generation"]},
            {"name": "i", "kind": "index", "eval": ["retrieval"]},
        ]
    )
    got = {c.name for c in select(cfgs, eval_kind="retrieval", kind="runtime")}
    assert got == {"r"}


def test_real_configs_yaml_parses() -> None:
    pytest.importorskip("yaml")
    from eval.config import load_configs

    path = Path(__file__).resolve().parents[2] / "eval" / "configs.yaml"
    cfgs = load_configs(path)
    names = {c.name for c in cfgs}
    assert "baseline" in names
    # Phase-1 retrieval configs must exist and be runnable without an LLM.
    retrieval = select(cfgs, eval_kind="retrieval", kind="runtime")
    assert any(c.name == "baseline" for c in retrieval)
