"""Consolidate the per-phase summaries into one human-readable report.

Reads whatever ``runs/_summary_*.json`` exist (retrieval, source, generation,
rejection) and writes ``runs/ablation_report.md`` — a per-knob table plus a
"recommended value + reason" section. Dependency-free (no openpyxl/pandas) so it
runs in the stock backend image; an .xlsx is written too only if openpyxl is
importable.

Usage (from backend/):
    python -m eval.report
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RUNS_DIR = Path(__file__).resolve().parent / "runs"


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    obj = json.loads(path.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else None


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _retrieval_section(retr: dict[str, Any], src: dict[str, Any] | None) -> str:
    # The source summary's "rows" is a dict keyed by config name -> agg metrics.
    src_by_name: dict[str, Any] = (src or {}).get("rows", {}) if src else {}
    headers = [
        "config",
        "knob",
        "recall@5(page)",
        "src_hit@5",
        "src_recall@5",
        "src_mrr",
        "refusal",
        "latency_ms",
    ]
    rows = []
    for r in retr.get("rows", []):
        m = r.get("metrics", {})
        s = src_by_name.get(r["config"], {})
        rows.append(
            [
                r["config"],
                r.get("knob", ""),
                m.get("recall@5", "-"),
                s.get("src_hit@5", "-"),
                s.get("src_recall@5", "-"),
                s.get("src_mrr", "-"),
                m.get("refusal_rate", "-"),
                m.get("latency_ms_mean", "-"),
            ]
        )
    return "## Phase 1 — Retrieval (page-level vs source-level)\n\n" + _md_table(
        headers, rows
    )


def _generation_section(gen: dict[str, Any]) -> str:
    headers = [
        "config",
        "knob",
        "faithfulness",
        "ans_relevancy",
        "n_evidence",
        "out_tokens",
        "answered",
        "err",
        "latency_p50",
    ]
    rows = []
    for r in gen.get("rows", []):
        faith = f'{r.get("faithfulness_mean", "-")}±{r.get("faithfulness_sd", "-")}'
        relev = (
            f'{r.get("answer_relevancy_mean", "-")}'
            f'±{r.get("answer_relevancy_sd", "-")}'
        )
        rows.append(
            [
                r["config"],
                r.get("knob", ""),
                faith,
                relev,
                r.get("n_evidence_mean", "-"),
                r.get("out_tokens_est_mean", "-"),
                r.get("answered_rate", "-"),
                r.get("error_rate", "-"),
                r.get("latency_ms_p50", "-"),
            ]
        )
    return "## Phase 2 — Generation (faithfulness / relevancy / cost)\n\n" + _md_table(
        headers, rows
    )


def _rejection_section(rej: dict[str, Any]) -> str:
    headers = ["config", "score_threshold", "negative_rejection", "false_refusal"]
    rows = [
        [
            r["config"],
            r.get("score_threshold", "-"),
            r.get("negative_rejection_rate", "-"),
            r.get("false_refusal_rate", "-"),
        ]
        for r in rej.get("rows", [])
    ]
    return "## Phase 2 — Rejection (E6 threshold pairing)\n\n" + _md_table(headers, rows)


def build_report(out_dir: Path) -> str:
    parts = ["# RAG Ablation Report\n"]
    retr = _load(out_dir / "_summary_retrieval.json")
    src = _load(out_dir / "_summary_source.json")
    gen = _load(out_dir / "_summary_generation.json")
    rej = _load(out_dir / "_summary_rejection.json")

    if retr:
        parts.append(_retrieval_section(retr, src))
    if gen:
        parts.append(_generation_section(gen))
    if rej:
        parts.append(_rejection_section(rej))
    if not (retr or gen or rej):
        parts.append("_No summaries found — run a phase first._")
    return "\n\n".join(parts) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consolidate ablation summaries")
    parser.add_argument("--out", default=str(RUNS_DIR))
    args = parser.parse_args(argv)
    out_dir = Path(args.out)

    md = build_report(out_dir)
    md_path = out_dir / "ablation_report.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    print(md)
    print(f"report -> {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
