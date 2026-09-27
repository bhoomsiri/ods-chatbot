"""KG-compare Phase 3 (Hierarchical add-on) — judge ONLY the Hierarchical run
with the SAME Claude judge, then MERGE it into the 3-way comparison without
re-judging (or altering) the existing vector / graphrag results.

Reuses ``score.score_run`` + ``score.aggregate`` (identical metrics) and the same
``ClaudeJudge``. Backs up ``scored.jsonl`` and ``_summary_comparison.json`` before
writing. Vector/GraphRAG rows are read back verbatim and preserved.

Run inside the backend container (needs ANTHROPIC_API_KEY):
    docker compose exec backend python -m eval.kg_compare.score_hierarchical
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from eval.datasets import load_eval_items
from eval.kg_compare.claude_judge import ClaudeJudge
from eval.kg_compare.score import _load, aggregate, score_run

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs" / "kg_compare"
HIER = RUNS / "hierarchical" / "results.jsonl"
PC_STATS = RUNS / "hierarchical" / "pc_build_stats.json"
SCORED = RUNS / "scored.jsonl"
SUMMARY = RUNS / "_summary_comparison.json"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def main() -> int:
    gold = {it.id: it for it in load_eval_items()}
    hier = _load(HIER)

    print("judging Hierarchical with Claude (same judge as vector/graphrag)…")
    judge = ClaudeJudge()
    scored_hier = score_run("hierarchical", hier, gold, judge)

    # --- merge scored.jsonl: keep vector/graphrag verbatim, drop any prior hier ---
    if SCORED.exists():
        shutil.copy2(SCORED, SCORED.with_suffix(".jsonl.pre_hier.bak"))
    prior = [r for r in _read_jsonl(SCORED) if r.get("rag") != "hierarchical"]
    with SCORED.open("w", encoding="utf-8") as fh:
        for r in prior + scored_hier:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # --- merge _summary_comparison.json: add hierarchical, keep the rest ---
    if SUMMARY.exists():
        shutil.copy2(SUMMARY, SUMMARY.with_suffix(".json.pre_hier.bak"))
    summ = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else {}
    summaries = [s for s in summ.get("summaries", []) if s.get("rag") != "hierarchical"]
    summaries.append(aggregate("hierarchical", scored_hier))
    summ["summaries"] = summaries

    pc_stats = (
        json.loads(PC_STATS.read_text(encoding="utf-8")) if PC_STATS.exists() else {}
    )
    summ.setdefault("cost_by_method", {})
    summ["cost_by_method"]["hierarchical"] = {
        "index_llm_calls": pc_stats.get("index_llm_calls", 0),
        "index_tokens_est": pc_stats.get("index_tokens_est", 0),
        "n_parents": pc_stats.get("n_parents"),
        "n_children": pc_stats.get("n_children"),
        "build_seconds": pc_stats.get("build_seconds"),
    }
    SUMMARY.write_text(json.dumps(summ, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Hierarchical summary ===")
    h = next(s for s in summaries if s["rag"] == "hierarchical")
    for role in ("in_subset", "rejection", "out_of_subset"):
        a = h[role]
        print(
            f"  {role:>13}: behavior_ok={a['correct_behavior_rate']} "
            f"correctness={a['mean_correctness_answered']} "
            f"faith={a['mean_faithfulness_answered']} bleu={a['mean_bleu_answered']} "
            f"halluc={a['hallucinations']}"
        )
    print(f"\nmerged -> {SCORED}\nmerged -> {SUMMARY}")
    print("(vector/graphrag rows preserved verbatim; backups written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
