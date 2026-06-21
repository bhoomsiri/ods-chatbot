"""Postgres adapter for the ConversationStore port (SQLAlchemy 2.0 async).

Every query is scoped by ``user_id`` so ownership is enforced at the data layer:
a user can never read or mutate another's conversation. Single-conversation
operations return None/False for both "not found" and "not owned" — callers
cannot tell the difference, so existence is never leaked.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities import Citation, Conversation, Message
from app.infrastructure.db.models import ConversationRow, MessageRow

_DEFAULT_TITLE = "แชตใหม่"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_title(title: str) -> str:
    return title.strip()[:200] or _DEFAULT_TITLE


def _cit_to_dict(c: Citation) -> dict[str, Any]:
    return {
        "id": c.id,
        "source": c.source,
        "page": c.page,
        "score": c.score,
        "snippet": c.snippet,
        "image": c.image,
    }


def _dict_to_cit(d: dict[str, Any]) -> Citation:
    return Citation(
        id=str(d.get("id", "")),
        source=str(d.get("source", "")),
        page=d.get("page"),
        score=d.get("score"),
        snippet=d.get("snippet"),
        image=d.get("image"),
    )


def _to_conversation(row: ConversationRow) -> Conversation:
    return Conversation(
        id=row.id,
        user_id=row.user_id,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_message(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
        citations=[_dict_to_cit(c) for c in (row.citations or [])],
    )


class PostgresConversationStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def create(self, *, user_id: str, title: str) -> Conversation:
        now = _now()
        row = ConversationRow(
            id=uuid4().hex,
            user_id=user_id,
            title=_clean_title(title),
            created_at=now,
            updated_at=now,
        )
        async with self._sm() as session, session.begin():
            session.add(row)
        return _to_conversation(row)

    async def list_for_user(self, *, user_id: str) -> list[Conversation]:
        async with self._sm() as session:
            result = await session.execute(
                select(ConversationRow)
                .where(ConversationRow.user_id == user_id)
                .order_by(ConversationRow.updated_at.desc())
            )
            return [_to_conversation(r) for r in result.scalars().all()]

    async def get_messages(
        self, *, conversation_id: str, user_id: str
    ) -> list[Message] | None:
        async with self._sm() as session:
            conv = await session.get(ConversationRow, conversation_id)
            if conv is None or conv.user_id != user_id:
                return None
            result = await session.execute(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.created_at)
            )
            return [_to_message(r) for r in result.scalars().all()]

    async def add_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        citations: Sequence[Citation] = (),
    ) -> Message | None:
        now = _now()
        row = MessageRow(
            id=uuid4().hex,
            conversation_id=conversation_id,
            role=role,
            content=content,
            citations=[_cit_to_dict(c) for c in citations],
            created_at=now,
        )
        async with self._sm() as session, session.begin():
            conv = await session.get(ConversationRow, conversation_id)
            if conv is None or conv.user_id != user_id:
                return None
            session.add(row)
            conv.updated_at = now  # bump thread to top of the sidebar
        return _to_message(row)

    async def set_title(
        self, *, conversation_id: str, user_id: str, title: str
    ) -> bool:
        async with self._sm() as session, session.begin():
            result = await session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.user_id == user_id,
                )
                .values(title=_clean_title(title), updated_at=_now())
            )
        return bool(result.rowcount)

    async def delete(self, *, conversation_id: str, user_id: str) -> bool:
        async with self._sm() as session, session.begin():
            result = await session.execute(
                sa_delete(ConversationRow).where(
                    ConversationRow.id == conversation_id,
                    ConversationRow.user_id == user_id,
                )
            )
        return bool(result.rowcount)
