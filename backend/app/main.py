"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import chat, ingest
from app.core.providers import get_store
from app.core.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ods")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "Starting %s (env=%s, use_fakes=%s)",
        settings.app_name,
        settings.environment,
        settings.use_fakes,
    )
    try:
        get_store().ensure_collection()
    except Exception:  # noqa: BLE001 - never block startup on the vector store
        logger.exception("ensure_collection failed; continuing")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
