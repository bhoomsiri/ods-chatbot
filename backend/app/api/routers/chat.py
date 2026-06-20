"""Chat router — thin controller. Streams the answer as Server-Sent Events."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.providers import get_answer_usecase
from app.domain.entities import ERROR_MESSAGE, QUOTA_MESSAGE, CitationsEvent, TokenEvent
from app.domain.errors import QuotaExceededError
from app.schemas.chat import ChatRequest, CitationDTO
from app.usecases.answer import AnswerQuestion

router = APIRouter(tags=["chat"])
logger = logging.getLogger("ods.chat")


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    body: ChatRequest,
    usecase: Annotated[AnswerQuestion, Depends(get_answer_usecase)],
) -> StreamingResponse:
    history = [t.to_domain() for t in body.history]

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in usecase.execute(
                body.message,
                history=history,
                category=body.category,
                department=body.department,
            ):
                if isinstance(event, TokenEvent):
                    yield _sse({"type": "token", "text": event.text})
                elif isinstance(event, CitationsEvent):
                    yield _sse(
                        {
                            "type": "citations",
                            "citations": [
                                CitationDTO.from_domain(c).model_dump()
                                for c in event.citations
                            ],
                        }
                    )
            yield _sse({"type": "done"})
        except QuotaExceededError:
            # Provider quota / rate limit (429) — reply gently, don't leak raw error.
            logger.warning("Gemini quota exceeded")
            yield _sse({"type": "token", "text": QUOTA_MESSAGE})
            yield _sse({"type": "done"})
        except Exception:  # noqa: BLE001 - never leak internal errors to the client
            logger.exception("chat pipeline failed")
            yield _sse({"type": "error", "detail": ERROR_MESSAGE})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
