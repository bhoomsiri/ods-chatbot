"""Pipeline wiring for the E10 reformulate-model knob (no network).

Verifies ``build_query_analyzer`` binds the analyzer to the config's
``reformulate_model`` rather than the env, and that fake mode / missing-key
paths behave. ``GeminiQueryAnalyzer`` construction is lazy (the model handle is
built on first use), so asserting on ``_model_name`` touches no network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.infrastructure.fakes import FakeQueryAnalyzer
from eval import pipeline
from eval.config import parse_configs


def _cfg(model: str = "gemini-2.5-flash", *, reformulate: bool = True):
    [c] = parse_configs(
        [{"name": "x", "query": {"reformulate_model": model, "reformulate": reformulate}}]
    )
    return c


def test_fake_mode_returns_passthrough_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "get_settings", lambda: SimpleNamespace(use_fakes=True))
    analyzer = pipeline.build_query_analyzer(_cfg())
    assert isinstance(analyzer, FakeQueryAnalyzer)


def test_analyzer_binds_config_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(use_fakes=False, gemini_api_key="test-key"),
    )
    analyzer = pipeline.build_query_analyzer(_cfg("gemini-2.5-flash"))
    # bound to the config knob, not ODS_GEMINI_REFORMULATE_MODEL
    assert analyzer._model_name == "gemini-2.5-flash"

    baseline_analyzer = pipeline.build_query_analyzer(_cfg("gemini-2.5-flash-lite"))
    assert baseline_analyzer._model_name == "gemini-2.5-flash-lite"


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(use_fakes=False, gemini_api_key=None),
    )
    with pytest.raises(RuntimeError, match="ODS_GEMINI_API_KEY"):
        pipeline.build_query_analyzer(_cfg())
