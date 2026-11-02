"""Allowlisted async execution boundary; chart events are invocation-local."""

import json
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from chatbot.domain.agent import ToolCall, ToolDefinition
from chatbot.domain.presentation import ChartResult, ChartReady
from chatbot.domain.errors import InvalidToolCall, ToolFailed


@dataclass(frozen=True)
class Tool:
    definition: ToolDefinition
    handler: Callable[..., Awaitable[Any]]


def invalid_constant(value):
    raise ValueError("Non-finite JSON number")


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()):
        registered = {}
        for tool in tools:
            name = tool.definition.name
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) or name in registered:
                raise ValueError("Tool names must be valid and unique")
            Draft202012Validator.check_schema(tool.definition.parameters)
            registered[name] = tool
        self._tools = MappingProxyType(registered)
        self._events = []

    def take_events(self):
        events, self._events = self._events, []
        return events

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    async def execute(self, call: ToolCall) -> str:
        tool = self._tools.get(call.name)
        if tool is None:
            raise InvalidToolCall()
        try:
            arguments = json.loads(call.arguments, parse_constant=invalid_constant)
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be an object")
            Draft202012Validator(tool.definition.parameters).validate(arguments)
        except (ValueError, TypeError, ValidationError):
            raise InvalidToolCall() from None
        try:
            result = await tool.handler(**arguments)
            if isinstance(result, ChartResult):
                self._events.append(ChartReady(result.block))
                result = result.result
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            raise ToolFailed() from exc
