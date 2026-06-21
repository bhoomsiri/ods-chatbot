"""Shared FastAPI dependencies."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.settings import get_settings

# Stand-in identity until Clerk lands. The frontend generates a stable per-browser
# id (localStorage) and sends it as X-Client-Id; conversations are scoped to it.
# When Clerk is added, replace this with JWT verification that returns the Clerk
# user id (sub) — every conversation query already keys on the returned value.
ANONYMOUS_USER = "anonymous"


async def get_current_user(
    x_client_id: Annotated[str | None, Header()] = None,
) -> str:
    client = (x_client_id or "").strip()
    return client or ANONYMOUS_USER


async def require_admin(
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    """Guard privileged endpoints (ingest). When ODS_ADMIN_KEY is set, the
    X-Admin-Key header must match it; otherwise reject. When it is unset, allow
    (local dev) but warn — a public deploy must configure the key."""
    admin_key = get_settings().admin_key
    if not admin_key:
        logging.getLogger("ods.auth").warning(
            "ODS_ADMIN_KEY is not set — /ingest is UNPROTECTED. Set it before "
            "exposing this deployment."
        )
        return
    if (x_admin_key or "").strip() != admin_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin key required")
