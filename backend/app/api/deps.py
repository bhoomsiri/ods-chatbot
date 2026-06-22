"""Shared FastAPI dependencies."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.settings import get_settings

# Conversations are scoped to whatever this returns. Identity sources, in order:
#  1. Cloudflare Access — the signed-in Google email, injected by the edge as
#     `Cf-Access-Authenticated-User-Email` on every request to the protected
#     domain (forwarded through Next's /api rewrite). This makes history follow
#     the *user* across browsers/devices.
#  2. X-Client-Id — a stable per-browser id (localStorage) for when there's no
#     Cloudflare in front (local dev / fake mode).
#  3. anonymous — last resort.
# NOTE: the email header is trusted because the backend is only reachable behind
# the tunnel/edge (not published to the internet). For a hardened deploy, verify
# the `Cf-Access-Jwt-Assertion` JWT against the team's public keys instead.
ANONYMOUS_USER = "anonymous"


async def get_current_user(
    cf_access_authenticated_user_email: Annotated[str | None, Header()] = None,
    x_client_id: Annotated[str | None, Header()] = None,
) -> str:
    email = (cf_access_authenticated_user_email or "").strip().lower()
    if email:
        return email
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
