"""Output guardrail adapter (pure Python, no external deps).

Enforces CLAUDE.md §5: an answer must be grounded with at least one citation
and must not attempt to diagnose/prescribe.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.entities import Citation, GuardrailVerdict

# Heuristic phrases that suggest the model is diagnosing/prescribing rather than
# relaying manual content. Kept conservative to avoid false positives on Thai
# informational text.
_DIAGNOSIS_PATTERNS = [
    r"คุณเป็นโรค",
    r"คุณน่าจะเป็น",
    r"วินิจฉัยว่า(?:คุณ|ท่าน)",
    r"สั่งจ่ายยา",
    r"ให้รับประทานยา\S*\s*\d+\s*(?:เม็ด|มก|มิลลิกรัม)",
]
_DIAGNOSIS_RE = re.compile("|".join(_DIAGNOSIS_PATTERNS))


class CitationGuardrail:
    def validate(self, answer: str, citations: Sequence[Citation]) -> GuardrailVerdict:
        if not citations:
            return GuardrailVerdict(allowed=False, reason="missing_citation")
        if _DIAGNOSIS_RE.search(answer):
            return GuardrailVerdict(allowed=False, reason="diagnosis_attempt")
        return GuardrailVerdict(allowed=True)
