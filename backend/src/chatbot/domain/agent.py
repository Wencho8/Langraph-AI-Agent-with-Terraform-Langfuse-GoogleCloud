"""Provider-independent values exchanged by the application, graph, and models."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .models import Message, UserProfile


@dataclass(frozen=True)
class ModelItem:
    kind: Literal["message", "provider_output", "tool_result"]
    data: dict[str, Any]
    provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelItem":
        return cls(kind=value["kind"], data=value["data"], provider=value.get("provider"))

    @classmethod
    def message(cls, role: str, content: str, transcript: list | None = None) -> "ModelItem":
        data: dict[str, Any] = {"role": role, "content": content}
        if transcript:
            data["transcript"] = transcript
        return cls("message", data)


@dataclass(frozen=True)
class ChatHistory:
    messages: tuple[Message, ...]
    items: tuple[ModelItem, ...]

    @classmethod
    def from_messages(cls, messages) -> "ChatHistory":
        return cls(tuple(messages), tuple(ModelItem.message(m.role, m.content) for m in messages))


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelRequest:
    instructions: str
    profile_context: str | None
    items: tuple[ModelItem, ...]
    tools: tuple[ToolDefinition, ...] = ()


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None


def aggregate_usage(calls: list[dict], attempts: int) -> dict:
    usages = [call.get("usage", {}) for call in calls]
    complete = len(calls) == attempts and attempts > 0
    totals = {}
    for key in TokenUsage.__dataclass_fields__:
        values = [usage.get(key) for usage in usages]
        totals[key] = sum(values) if complete and all(v is not None for v in values) else None
    totals["complete"] = complete and all(
        totals[key] is not None for key in ("input_tokens", "output_tokens", "total_tokens")
    )
    return totals


@dataclass(frozen=True)
class ModelCompleted:
    text: str
    items: tuple[ModelItem, ...]
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    request_id: str | None = None


@dataclass(frozen=True)
class ModelCallStarted:
    count: int


@dataclass(frozen=True)
class ModelCallFinished:
    metrics: dict[str, Any]


@dataclass(frozen=True)
class ToolCallStarted:
    count: int


@dataclass(frozen=True)
class AgentCompleted:
    text: str
    transcript: tuple[ModelItem, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AgentRequest:
    user: UserProfile
    history: ChatHistory
    deadline: float
    check_lock: Callable[[], Awaitable[None]]


ModelEvent = TextDelta | ModelCompleted
AgentEvent = TextDelta | ModelCallStarted | ModelCallFinished | ToolCallStarted | AgentCompleted
