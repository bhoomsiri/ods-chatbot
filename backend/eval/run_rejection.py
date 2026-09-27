"""Phase 2 — negative-rejection ablation, paired with the E6 threshold sweep.

For each evidence-filter threshold (baseline + E6 variants) measure:
- negative_rejection_rate on the 12 out-of-scope questions (higher = better;
  the bot must decline off-manual questions), and
- false_refusal_rate on the in-scope gold questions (lower = better; a refusal
  here is a missed answerable question).

Raising ``score_threshold`` trades these off, so the two are reported together to
pick the cut that keeps refusals honest without dropping good evidence.

Refusal is decided from ``retrieve()`` alone (out-of-scope, or no evidence after
the threshold), so this NEVER calls the answer LLM — only the cheap reformulator.
The in-scope "no such data" probe (id 30) is excluded from false-refusal (its
correct behavior is to refuse).

Usage (from backend/):
    python -m eval.run_rejection
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import get_settings
from app.usecases.answer import AnswerQuestion
from eval.config import ExperimentConfig, load_configs, select
from eval.datasets import load_eval_items, load_oos_items
from eval.metrics.rejection import false_refusal_rate, negative_rejection_rate
from eval.pipeline import build_retriever

CONFIGS_PATH = Path(__file__).resolve().parent / "configs.yaml"
RUNS_DIR = Path(__file__).resolve().parent / "runs"


async def _refused(retriever: AnswerQuestion, question: str) -> bool:
    """True if the pipeline would decline (out-of-scope, or no evidence)."""
    outcome = await retriever.retrieve(question)
    if outcome.direct_response is not None:
        return False  # greeting/chit-chat is not a refusal
    if not outcome.in_scope:
        return True
    return not outcome.evidence


async def run_config(
    cfg: ExperimentConfig,
    oos_questions: list[str],
    inscope_questions: list[str],
) -> dict[str, object]:
    retriever = build_retriever(cfg, allow_llm=True)
    oos_flags = [await _refused(retriever, q) for q in oos_questions]
    inscope_flags = [await _refused(retriever, q) for q in inscope_questions]
    return {
        "config": cfg.name,
        "knob": cfg.knob,
        "score_threshold": cfg.query.score_threshold,
        "n_oos": len(oos_flags),
        "n_inscope": len(inscope_flags),
        "negative_rejection_rate": round(negative_rejection_rate(oos_flags), 4),
        "false_refusal_rate": round(false_refusal_rate(inscope_flags), 4),
    }


def _print_table(rows: list[dict[str, object]]) -> None:
    cols = ["score_threshold", "negative_rejection_rate", "false_refusal_rate"]
    header = f"{'config':<16}{'knob':<22}" + "".join(f"{c[:18]:>22}" for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        line = f"{str(r['config']):<16}{str(r['knob']):<22}"
        line += "".join(f"{float(r[c]):>22.4f}" for c in cols)  # type: ignore[arg-type]
        print(line)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-2 rejection ablation (E6)")
    parser.add_argument("--configs", default=str(CONFIGS_PATH))
    parser.add_argument("--out", default=str(RUNS_DIR))
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    configs = select(load_configs(args.configs), eval_kind="rejection", kind="runtime")
    # The baseline threshold belongs in the sweep even though it is tagged only
    # for retrieval/generation — include it so the E6 cut has its reference point.
    baseline = [c for c in load_configs(args.configs) if c.name == "baseline"]
    configs = baseline + [c for c in configs if c.name != "baseline"]
    if args.only:
        wanted = set(args.only)
        configs = [c for c in configs if c.name in wanted]
    if not configs:
        print("no matching rejection configs")
        return 1

    oos = [o.question for o in load_oos_items()]
    inscope = [it.question for it in load_eval_items() if not it.is_rejection_test]

    s = get_settings()
    print(
        f"phase-2 rejection | {len(configs)} thresholds | "
        f"oos={len(oos)} in-scope={len(inscope)} | use_fakes={s.use_fakes}"
    )

    rows: list[dict[str, object]] = []
    for cfg in configs:
        print(f"  [run ] {cfg.name} (thr={cfg.query.score_threshold})")
        rows.append(asyncio.run(run_config(cfg, oos, inscope)))

    summary = {
        "phase": "rejection",
        "generated_at": datetime.now(UTC).isoformat(),
        "use_fakes": s.use_fakes,
        "rows": rows,
    }
    summary_path = out_dir / "_summary_rejection.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    _print_table(rows)
    print(f"\nsummary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
