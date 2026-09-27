"""Phase 2 — generation ablation (calls the answer LLM + a judge).

Decides the knobs retrieval@k cannot separate — E5 (rerank_top_k) and E7
(query_transform) — by scoring the GENERATED answer: faithfulness (grounding),
answer relevancy, plus context-count and an output-token cost estimate. Also
covers E8 (answer_model) and E9 (temperature).

Cost note: this calls Gemini (answer model + a fixed judge model) and runs the
local embedder/reranker, so run it in the demo-down window. Latency cuts a
warmup prefix; stochastic judges use ``repeats`` and report mean ± sd + a
bootstrap 95% CI.

Usage (from backend/):
    python -m eval.run_generation --only baseline E5_rrtopk_5 E7_qt_off
    python -m eval.run_generation --limit 5 --warmup 1   # quick / cheap
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import get_settings
from app.usecases.answer import AnswerQuestion
from eval.config import ExperimentConfig, load_configs, select
from eval.datasets import load_eval_items
from eval.datatypes import EvalItem
from eval.metrics.llm_judge import Judge, bootstrap_ci, mean_sd
from eval.pipeline import build_judge, build_retriever

CONFIGS_PATH = Path(__file__).resolve().parent / "configs.yaml"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
# Rough chars-per-output-token for Thai; only used for RELATIVE cost comparison.
CHARS_PER_TOKEN = 3.0


async def _score_item(
    retriever: AnswerQuestion, judge: Judge, item: EvalItem
) -> dict[str, object]:
    try:
        gen = await retriever.generate(item.question)
    except Exception as exc:  # noqa: BLE001 - record, don't abort the sweep
        return {"item_id": item.id, "status": "error", "error": str(exc)[:200]}

    rec: dict[str, object] = {
        "item_id": item.id,
        "status": gen.status,
        "n_evidence": len(gen.evidence),
        "out_tokens_est": round(len(gen.answer) / CHARS_PER_TOKEN, 1),
        "guardrail_allowed": gen.guardrail_allowed,
        "answer": gen.answer,
    }
    if gen.status == "answered":
        contexts = [c.chunk.text for c in gen.evidence]
        # Guard each judge call: a single judge hiccup (rate limit, empty
        # response) drops that one score, never the whole sweep.
        try:
            rec["faithfulness"] = await judge.faithfulness(
                answer=gen.answer, contexts=contexts
            )
        except Exception as exc:  # noqa: BLE001
            rec["faithfulness_error"] = str(exc)[:120]
        try:
            rec["answer_relevancy"] = await judge.answer_relevancy(
                question=item.question, answer=gen.answer
            )
        except Exception as exc:  # noqa: BLE001
            rec["answer_relevancy_error"] = str(exc)[:120]
    return rec


async def run_config(
    cfg: ExperimentConfig, items: list[EvalItem], *, warmup: int
) -> list[dict[str, object]]:
    retriever = build_retriever(cfg, allow_llm=True)
    judge = build_judge(allow_llm=True)
    loop = asyncio.get_event_loop()

    # Warm up GPU kernels / model caches so the first timed item isn't an outlier.
    for item in items[: max(0, warmup)]:
        await retriever.generate(item.question)

    records: list[dict[str, object]] = []
    for _ in range(cfg.repeats):
        for item in items:
            start = loop.time()
            rec = await _score_item(retriever, judge, item)
            rec["latency_ms"] = round((loop.time() - start) * 1000.0, 1)
            records.append(rec)
    return records


def _floats(records: list[dict[str, object]], key: str) -> list[float]:
    out: list[float] = []
    for r in records:
        v = r.get(key)
        if isinstance(v, int | float):
            out.append(float(v))
    return out


def aggregate(
    cfg: ExperimentConfig, records: list[dict[str, object]]
) -> dict[str, object]:
    answered = [r for r in records if r.get("status") == "answered"]
    faith = _floats(answered, "faithfulness")
    relev = _floats(answered, "answer_relevancy")
    f_mean, f_sd = mean_sd(faith)
    r_mean, r_sd = mean_sd(relev)
    lat = _floats(records, "latency_ms")
    n = len(records)
    return {
        "config": cfg.name,
        "knob": cfg.knob,
        "n": n,
        "repeats": cfg.repeats,
        "answer_model": cfg.query.answer_model,
        "reformulate": cfg.query.reformulate,
        "rerank_top_k": cfg.query.rerank_top_k,
        "temperature": cfg.query.temperature,
        "answered_rate": round(len(answered) / n, 4) if n else 0.0,
        "error_rate": round(sum(1 for r in records if r.get("status") == "error") / n, 4)
        if n
        else 0.0,
        "faithfulness_mean": round(f_mean, 4),
        "faithfulness_sd": round(f_sd, 4),
        "faithfulness_ci95": [round(x, 4) for x in bootstrap_ci(faith)],
        "answer_relevancy_mean": round(r_mean, 4),
        "answer_relevancy_sd": round(r_sd, 4),
        "answer_relevancy_ci95": [round(x, 4) for x in bootstrap_ci(relev)],
        "n_evidence_mean": round(statistics.fmean(_floats(answered, "n_evidence")), 2)
        if answered
        else 0.0,
        "out_tokens_est_mean": round(
            statistics.fmean(_floats(answered, "out_tokens_est")), 1
        )
        if answered
        else 0.0,
        "latency_ms_p50": round(statistics.median(lat), 1) if lat else 0.0,
    }


def _print_table(rows: list[dict[str, object]]) -> None:
    cols = [
        "faithfulness_mean",
        "answer_relevancy_mean",
        "n_evidence_mean",
        "out_tokens_est_mean",
        "answered_rate",
        "latency_ms_p50",
    ]
    header = f"{'config':<16}{'knob':<22}" + "".join(f"{c[:14]:>16}" for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        line = f"{str(r['config']):<16}{str(r['knob']):<22}"
        line += "".join(f"{float(r[c]):>16.4f}" for c in cols)  # type: ignore[arg-type]
        print(line)


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-2 generation ablation")
    parser.add_argument("--configs", default=str(CONFIGS_PATH))
    parser.add_argument("--out", default=str(RUNS_DIR))
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    configs = select(load_configs(args.configs), eval_kind="generation", kind="runtime")
    if args.only:
        wanted = set(args.only)
        configs = [c for c in configs if c.name in wanted]
    if not configs:
        print("no matching generation configs")
        return 1

    items = load_eval_items()
    if args.limit:
        items = items[: args.limit]

    s = get_settings()
    print(
        f"phase-2 generation | {len(configs)} configs x {len(items)} questions "
        f"| use_fakes={s.use_fakes} judge=fixed"
    )

    rows: list[dict[str, object]] = []
    for cfg in configs:
        print(f"  [run ] {cfg.name} ({cfg.knob}) repeats={cfg.repeats}")
        records = asyncio.run(run_config(cfg, items, warmup=args.warmup))
        _write(out_dir / f"gen_{cfg.name}" / "results.jsonl", records)
        rows.append(aggregate(cfg, records))

    summary = {
        "phase": "generation",
        "generated_at": datetime.now(UTC).isoformat(),
        "use_fakes": s.use_fakes,
        "chars_per_token": CHARS_PER_TOKEN,
        "rows": rows,
    }
    summary_path = out_dir / "_summary_generation.json"
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
