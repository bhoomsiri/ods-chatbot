"""Domain-level errors. Adapters translate vendor exceptions into these so the
use case and API never depend on a vendor's exception types.
"""

from __future__ import annotations


class QuotaExceededError(Exception):
    """The LLM provider rejected the request due to quota / rate limits (429)."""
