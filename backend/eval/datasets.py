"""Dataset loaders.

The files under ``datasets/`` are byte-identical copies of the canonical sets in
the repo's ``benchmark/`` folder (``questions.json``, ``gold.csv``,
``oos_questions.json``). They are copied here, not referenced, because the
backend container mounts only ``backend/`` — ``benchmark/`` is not on its
filesystem. Do NOT author new questions here; re-copy from ``benchmark/`` if the
canonical set changes.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from eval.datatypes import EvalItem, OOSItem

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
QSET_PATH = DATASETS_DIR / "qset.json"
GOLD_PATH = DATASETS_DIR / "gold.csv"
OOS_PATH = DATASETS_DIR / "oos.json"
GOLD_SOURCES_PATH = DATASETS_DIR / "gold_sources.json"


def _parse_pages(raw: str) -> frozenset[int]:
    """``"103;1"`` -> ``{103, 1}``; ignores blanks/non-numeric tokens."""
    pages: set[int] = set()
    for token in raw.replace(",", ";").split(";"):
        token = token.strip()
        if token.isdigit():
            pages.add(int(token))
    return frozenset(pages)


def load_gold() -> dict[int, EvalItem]:
    """Load gold.csv keyed by question id."""
    rows: dict[int, EvalItem] = {}
    with GOLD_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            qid = int(row["id"])
            rows[qid] = EvalItem(
                id=qid,
                category=row.get("category", "").strip(),
                question=row["question"].strip(),
                gold_pages=_parse_pages(row.get("gold_pages", "")),
                gold_answer=row.get("gold_answer", "").strip(),
                source_doc=row.get("source_doc", "").strip(),
            )
    return rows


def load_gold_sources() -> tuple[dict[int, frozenset[str]], frozenset[int]]:
    """Load the source-document ground truth + the rejection-only id set."""
    raw = json.loads(GOLD_SOURCES_PATH.read_text(encoding="utf-8"))
    sources = {
        int(qid): frozenset(stems) for qid, stems in raw.get("sources", {}).items()
    }
    rejection_only = frozenset(int(i) for i in raw.get("_rejection_only", []))
    return sources, rejection_only


def load_eval_items() -> list[EvalItem]:
    """Join qset.json (question order) with gold.csv (answers + pages) and the
    source-document ground truth by id.

    qset is the source of truth for which questions to run; gold supplies the
    answer/pages. Raises if a qset id is missing from gold (datasets drifted).
    """
    gold = load_gold()
    gold_sources, rejection_only = load_gold_sources()
    qset = json.loads(QSET_PATH.read_text(encoding="utf-8"))
    items: list[EvalItem] = []
    for entry in qset:
        qid = int(entry["id"])
        g = gold.get(qid)
        if g is None:
            raise ValueError(f"qset id {qid} has no row in gold.csv")
        # Prefer qset's question text (it is the canonical prompt); keep gold's
        # answer/pages.
        items.append(
            EvalItem(
                id=qid,
                category=str(entry.get("category", g.category)),
                question=str(entry["question"]).strip(),
                gold_pages=g.gold_pages,
                gold_sources=gold_sources.get(qid, frozenset()),
                gold_answer=g.gold_answer,
                source_doc=g.source_doc,
                is_rejection_test=qid in rejection_only,
            )
        )
    return items


def load_oos_items() -> list[OOSItem]:
    raw = json.loads(OOS_PATH.read_text(encoding="utf-8"))
    return [
        OOSItem(
            id=str(e["id"]),
            type=str(e.get("type", "")),
            question=str(e["question"]).strip(),
            expected=str(e.get("expected", "")),
            difficulty=str(e.get("difficulty", "")),
        )
        for e in raw
    ]
