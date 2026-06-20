"""Pydantic v2 request/response DTOs for the API boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.entities import ChatTurn, Citation

Role = Literal["user", "assistant"]


class ChatTurnDTO(BaseModel):
    role: Role
    content: str

    def to_domain(self) -> ChatTurn:
        return ChatTurn(role=self.role, content=self.content)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurnDTO] = Field(default_factory=list)
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
