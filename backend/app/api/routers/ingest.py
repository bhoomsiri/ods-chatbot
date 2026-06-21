"""Ingest router — thin controller for uploading knowledge-base documents."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import require_admin
from app.core.providers import get_ingest_usecase
from app.schemas.chat import IngestResultDTO
from app.usecases.ingest import IngestDocument

router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    response_model=list[IngestResultDTO],
    dependencies=[Depends(require_admin)],
)
async def ingest(
    usecase: Annotated[IngestDocument, Depends(get_ingest_usecase)],
    files: Annotated[list[UploadFile], File()],
    category: Annotated[str | None, Form()] = None,
) -> list[IngestResultDTO]:
    results: list[IngestResultDTO] = []
    for f in files:
        filename = f.filename or "unnamed"
        try:
            content = await f.read()
            report = await run_in_threadpool(
                usecase.execute, content, filename, category=category
            )
            results.append(
                IngestResultDTO(filename=filename, status="success", chunks=report.chunks)
            )
        except Exception as exc:  # noqa: BLE001 - report per-file failures
            results.append(
                IngestResultDTO(filename=filename, status="error", detail=str(exc))
            )
    return results
