#!/usr/bin/env python3
"""
bertscore_aggregate.py — เติม BERTScore F1 (aggregate) ต่อ config ลง _summary_addmetrics.json

ทำไมต้องมีสคริปต์นี้: score-only pass เดิมคำนวณ sanity + spot-check ได้ แต่ไม่ได้
เติมค่าเฉลี่ยต่อ config (bertscore_f1 = None ทั้ง 9) สคริปต์นี้เติมให้ครบ — offline,
ไม่เรียก API/เครดิต ใช้แค่ดาวน์โหลดโมเดล xlm-roberta-large ครั้งเดียว

วิธีใช้ (จาก repo root หรือจากโฟลเดอร์ benchmark/ ก็ได้):
    pip install bert-score
    python benchmark/bertscore_aggregate.py
"""
from __future__ import annotations
import json, csv, sys, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../benchmark
REPO = HERE.parent                               # repo root
RUNS = REPO / "backend" / "eval" / "runs"
GOLD_CSV = HERE / "gold.csv"
SUMMARY = RUNS / "_summary_addmetrics.json"

MODEL = "xlm-roberta-large"
LANG = "th"

def load_gold() -> dict[int, str]:
    g = {}
    with open(GOLD_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            g[int(r["id"])] = (r.get("gold_answer") or "").strip()
    return g

def load_answers(cfg_dir: Path) -> dict[int, str]:
    ans = {}
    p = cfg_dir / "results.jsonl"
    if not p.exists():
        return ans
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        a = (d.get("answer") or "").strip()
        if a:
            ans[d["item_id"]] = a
    return ans

def main() -> None:
    try:
        from bert_score import score as bert_score
    except ImportError:
        sys.exit("ต้องติดตั้งก่อน:  pip install bert-score")

    if not SUMMARY.exists():
        sys.exit(f"ไม่พบไฟล์: {SUMMARY}")
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    bb = summary["bleu_bertscore_generation"]
    gold = load_gold()

    # sanity: identical → F1 ~ 1.0
    _, _, f_id = bert_score(["ทดสอบข้อความเดียวกัน"], ["ทดสอบข้อความเดียวกัน"],
                            model_type=MODEL, lang=LANG, rescale_with_baseline=False, verbose=False)
    print(f"[sanity] BERTScore identical F1 = {float(f_id.mean()):.4f} (ควร ~1.0)")

    per_item_out = {}
    for cfg in list(bb.keys()):                 # keys เช่น gen_baseline, gen_E8_model_pro
        cfg_dir = RUNS / cfg
        ans = load_answers(cfg_dir)
        pairs = [(ans[i], gold[i]) for i in sorted(ans) if i in gold and gold[i]]
        if not pairs:
            print(f"  {cfg:<24} ไม่มีคำตอบให้คิด — ข้าม")
            continue
        cands, refs = zip(*pairs)
        _, _, F1 = bert_score(list(cands), list(refs), model_type=MODEL, lang=LANG,
                              rescale_with_baseline=False, verbose=False)
        f1s = [float(x) for x in F1]
        mean_f1 = round(statistics.fmean(f1s), 4)
        bb[cfg]["bertscore_f1"] = mean_f1
        bb[cfg]["bertscore_n"] = len(f1s)
        per_item_out[cfg] = [round(x, 4) for x in f1s]
        print(f"  {cfg:<24} n={len(f1s):>2}  BERTScore_F1(mean) = {mean_f1}")

    # provenance + coverage
    filled = sum(1 for v in bb.values() if v.get("bertscore_f1") is not None)
    summary.setdefault("provenance", {})["bertscore_aggregate_added"] = True
    summary["bertscore_per_item"] = per_item_out
    all_f1 = [v["bertscore_f1"] for v in bb.values() if v.get("bertscore_f1") is not None]
    assert filled == len(bb), f"ยังไม่ครบ: {filled}/{len(bb)}"
    assert all(0.0 <= x <= 1.0 for x in all_f1), "มีค่าหลุดช่วง [0,1]"
    print(f"\n[coverage] bertscore filled {filled}/{len(bb)} | range {min(all_f1):.4f}-{max(all_f1):.4f}")

    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"เขียนกลับแล้ว: {SUMMARY}")

if __name__ == "__main__":
    main()
