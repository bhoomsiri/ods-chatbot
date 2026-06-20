"""Rule-based intent classifier adapter.

Fast, deterministic, zero-cost input router. Only short-circuits messages that
are unambiguously a greeting; everything else is routed to RAG (which safely
refuses when there is no evidence). Swap in an LLM-based adapter later by
implementing the same IntentClassifier port — no use-case change required.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.entities import ChatTurn, IntentResult
from app.domain.intent import GREETING_RESPONSE, is_greeting


class RuleBasedIntentClassifier:
    async def classify(
        self, message: str, history: Sequence[ChatTurn]
    ) -> IntentResult:
        if is_greeting(message):
            return IntentResult(kind="greeting", direct_response=GREETING_RESPONSE)
        return IntentResult(kind="question", direct_response=None)
