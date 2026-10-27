from collections.abc import AsyncIterator, Sequence
from typing import Literal, Protocol
from uuid import UUID

from chatbot.domain.agent import AgentEvent, AgentRequest, ChatHistory, ModelEvent, ModelItem, ModelRequest
from chatbot.domain.models import Message, Turn, UserProfile


class ConversationRepository(Protocol):
    async def ready(self) -> None: ...
    async def profile(self, user_id: UUID) -> UserProfile | None: ...
    async def messages(self, user_id: UUID) -> list[Message]: ...
    async def begin(self, user_id: UUID, text: str) -> tuple[Turn, ChatHistory]: ...
    async def complete(
        self, turn: Turn, text: str, *, transcript: Sequence[ModelItem] = (), metadata: dict | None = None
    ) -> Message: ...
    async def finish(
        self, turn: Turn, status: Literal["failed", "cancelled"], code: str, *, metadata: dict | None = None
    ) -> None: ...


class AgentRunner(Protocol):
    provider: str
    model_name: str
    prompt_revision: str

    def stream(self, request: AgentRequest) -> AsyncIterator[AgentEvent]: ...


class ChatModel(Protocol):
    provider: str
    name: str

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
    async def close(self) -> None: ...


class LockLease(Protocol):
    async def check(self) -> None: ...
    async def release(self) -> None: ...


class ConversationLock(Protocol):
    async def acquire(self, user_id: UUID) -> LockLease: ...


class IdentityProvider(Protocol):
    async def resolve(self, credential: str | None) -> UserProfile: ...


class RateLimiter(Protocol):
    def check(self, user_id: UUID) -> None: ...
