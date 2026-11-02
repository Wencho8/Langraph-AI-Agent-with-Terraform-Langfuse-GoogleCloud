from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID


@dataclass(frozen=True)
class UserProfile:
    id: UUID
    display_name: str | None = None


@dataclass(frozen=True)
class Message:
    id: UUID
    turn_id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    blocks: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Turn:
    id: UUID
    conversation_id: UUID
    sequence: int


@dataclass(frozen=True)
class ChatEvent:
    kind: Literal["started", "delta", "chart", "tool_status", "completed", "error"]
    data: dict[str, Any]
