"""Conversations router — list / read / rename / delete chat history.

Thin controller. Identity comes from get_current_user (X-Client-Id today, Clerk
later); the store scopes every operation by it, so a 404 covers both "missing"
and "not yours".
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_current_user
from app.core.providers import get_conversation_store
from app.domain.ports import ConversationStore
from app.schemas.chat import (
    ConversationDetailDTO,
    ConversationDTO,
    MessageDTO,
    RenameRequest,
)

router = APIRouter(tags=["conversations"])

StoreDep = Annotated[ConversationStore, Depends(get_conversation_store)]
UserDep = Annotated[str, Depends(get_current_user)]


@router.get("/conversations", response_model=list[ConversationDTO])
async def list_conversations(store: StoreDep, user: UserDep) -> list[ConversationDTO]:
    convs = await store.list_for_user(user_id=user)
    return [ConversationDTO.from_domain(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailDTO)
async def get_conversation(
    conversation_id: str, store: StoreDep, user: UserDep
) -> ConversationDetailDTO:
    messages = await store.get_messages(
        conversation_id=conversation_id, user_id=user
    )
    if messages is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    convs = await store.list_for_user(user_id=user)
    title = next((c.title for c in convs if c.id == conversation_id), "")
    return ConversationDetailDTO(
        id=conversation_id,
        title=title,
        messages=[MessageDTO.from_domain(m) for m in messages],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationDTO)
async def rename_conversation(
    conversation_id: str, body: RenameRequest, store: StoreDep, user: UserDep
) -> ConversationDTO:
    ok = await store.set_title(
        conversation_id=conversation_id, user_id=user, title=body.title
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    convs = await store.list_for_user(user_id=user)
    conv = next((c for c in convs if c.id == conversation_id), None)
    if conv is None:  # deleted between calls — treat as gone
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return ConversationDTO.from_domain(conv)


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_conversation(
    conversation_id: str, store: StoreDep, user: UserDep
) -> Response:
    ok = await store.delete(conversation_id=conversation_id, user_id=user)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
