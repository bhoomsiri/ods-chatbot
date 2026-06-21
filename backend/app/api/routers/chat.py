"""Chat router — thin controller. Streams the answer as Server-Sent Events and
persists both the user message and the assistant answer into the conversation
history (best-effort: a history-DB failure never blocks answering)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.providers import get_answer_usecase, get_conversation_store
from app.domain.entities import (
    ERROR_MESSAGE,
    QUOTA_MESSAGE,
    Citation,
    CitationsEvent,
    TokenEvent,
)
from app.domain.errors import QuotaExceededError
from app.domain.ports import ConversationStore
from app.schemas.chat import ChatRequest, CitationDTO
from app.usecases.answer import AnswerQuestion

router = APIRouter(tags=["chat"])
logger = logging.getLogger("ods.chat")


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _title_from(message: str) -> str:
    """First line of the opening question, trimmed — the thread's display title."""
    first = message.strip().splitlines()[0] if message.strip() else "แชตใหม่"
    return first[:60]


@router.post("/chat")
async def chat(
    body: ChatRequest,
    usecase: Annotated[AnswerQuestion, Depends(get_answer_usecase)],
    store: Annotated[ConversationStore, Depends(get_conversation_store)],
    user: Annotated[str, Depends(get_current_user)],
) -> StreamingResponse:
    history = [t.to_domain() for t in body.history]

    async def _ensure_conversation() -> tuple[str | None, str]:
        """Resolve the target thread and persist the user message. Returns the
        conversation id (None if persistence is unavailable) and its title."""
        title = _title_from(body.message)
        try:
            conv_id = body.conversation_id
            if conv_id is None:
                conv = await store.create(user_id=user, title=title)
                conv_id, title = conv.id, conv.title
            saved = await store.add_message(
                conversation_id=conv_id, user_id=user, role="user",
                content=body.message,
            )
            if saved is None:
                # Unknown/foreign id — start a fresh thread instead of leaking.
                conv = await store.create(user_id=user, title=title)
                conv_id, title = conv.id, conv.title
                await store.add_message(
                    conversation_id=conv_id, user_id=user, role="user",
                    content=body.message,
                )
            return conv_id, title
        except Exception:  # noqa: BLE001 - history is best-effort
            logger.exception("persist user message failed; answering without history")
            return None, title

    async def _persist_assistant(
        conv_id: str | None, content: str, citations: Sequence[Citation]
    ) -> None:
        if conv_id is None or not content.strip():
            return
        try:
            await store.add_message(
                conversation_id=conv_id, user_id=user, role="assistant",
                content=content, citations=citations,
            )
        except Exception:  # noqa: BLE001 - history is best-effort
            logger.exception("persist assistant message failed")

    async def event_stream() -> AsyncIterator[str]:
        conv_id, title = await _ensure_conversation()
        if conv_id is not None:
            yield _sse({"type": "conversation", "id": conv_id, "title": title})

        parts: list[str] = []
        citations: list[Citation] = []
        try:
            async for event in usecase.execute(
                body.message,
                history=history,
                category=body.category,
                department=body.department,
            ):
                if isinstance(event, TokenEvent):
                    parts.append(event.text)
                    yield _sse({"type": "token", "text": event.text})
                elif isinstance(event, CitationsEvent):
                    citations = list(event.citations)
                    yield _sse(
                        {
                            "type": "citations",
                            "citations": [
                                CitationDTO.from_domain(c).model_dump()
                                for c in event.citations
                            ],
                        }
                    )
            await _persist_assistant(conv_id, "".join(parts), citations)
            yield _sse({"type": "done"})
        except QuotaExceededError:
            # Provider quota / rate limit (429) — reply gently, don't leak raw error.
            logger.warning("Gemini quota exceeded")
            await _persist_assistant(conv_id, QUOTA_MESSAGE, ())
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
