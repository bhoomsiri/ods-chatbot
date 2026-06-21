"""Pydantic v2 request/response DTOs for the API boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.entities import ChatTurn, Citation, Conversation, Message

Role = Literal["user", "assistant"]


class ChatTurnDTO(BaseModel):
    role: Role
    content: str

    def to_domain(self) -> ChatTurn:
        return ChatTurn(role=self.role, content=self.content)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurnDTO] = Field(default_factory=list)
    # Existing thread to append to. None / omitted starts a new conversation
    # (the server creates one and returns its id via a "conversation" SSE event).
    conversation_id: str | None = Field(default=None, max_length=36)
    # Free-form tag values matching the Qdrant payload tags (category +
    # department). None / omitted = no filter on that dimension.
    category: str | None = Field(default=None, max_length=64)
    department: str | None = Field(default=None, max_length=64)


class CitationDTO(BaseModel):
    id: str
    source: str
    page: int | None = None
    score: float | None = None
    snippet: str | None = None
    image: str | None = None

    @classmethod
    def from_domain(cls, c: Citation) -> CitationDTO:
        return cls(
            id=c.id,
            source=c.source,
            page=c.page,
            score=c.score,
            snippet=c.snippet,
            image=c.image,
        )


class IngestResultDTO(BaseModel):
    filename: str
    status: Literal["success", "error"]
    chunks: int | None = None
    detail: str | None = None


# --- Conversation history DTOs ----------------------------------------------


class ConversationDTO(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, c: Conversation) -> ConversationDTO:
        return cls(
            id=c.id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )


class MessageDTO(BaseModel):
    id: str
    role: Role
    content: str
    created_at: datetime
    citations: list[CitationDTO] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, m: Message) -> MessageDTO:
        role: Role = "assistant" if m.role == "assistant" else "user"
        return cls(
            id=m.id,
            role=role,
            content=m.content,
            created_at=m.created_at,
            citations=[CitationDTO.from_domain(c) for c in m.citations],
        )


class ConversationDetailDTO(BaseModel):
    id: str
    title: str
    messages: list[MessageDTO]


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
