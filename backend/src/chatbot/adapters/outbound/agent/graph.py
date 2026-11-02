import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from time import monotonic
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from chatbot.application.ports import ChatModel
from chatbot.application.tools import ToolRegistry
from chatbot.domain.agent import (
    AgentCompleted, AgentEvent, AgentRequest, ModelCallFinished, ModelCallStarted,
    ModelCompleted, ModelItem, ModelRequest, TextDelta, ToolCall, ToolCallStarted, ToolCallFinished, aggregate_usage,
)
from chatbot.domain.errors import ExecutionLimit, InvalidModelResponse, InvalidToolCall, ModelTimedOut, ToolTimedOut, TurnTimedOut
from chatbot.prompts.loader import Prompt, profile_context
from chatbot.domain.presentation import ChartReady, append_text


class AgentState(TypedDict):
    tools: ToolRegistry
    request: AgentRequest
    items: list[ModelItem]
    transcript: list[ModelItem]
    response: str
    pending: list[ToolCall]
    model_calls: int
    tool_calls: int
    seen_calls: list[str]
    calls: list[dict]


class LangGraphAgent:
    def __init__(
        self, model: ChatModel, *, prompt: Prompt, tools: ToolRegistry | None = None,
        max_model_calls: int = 4, max_tool_calls: int = 8, recursion_limit: int = 12,
        model_timeout: float = 20, tool_timeout: float = 5, tools_factory=None,
    ):
        self.provider, self.model_name, self.prompt_revision = model.provider, model.name, prompt.revision
        self.recursion_limit = recursion_limit
        self.reasoning_effort = getattr(model, "reasoning_effort", None)
        tools = tools if tools is not None else ToolRegistry()
        self.tools_factory = tools_factory or (lambda: tools)

        async def check(request):
            if asyncio.get_running_loop().time() >= request.deadline:
                raise TurnTimedOut()
            await request.check_lock()

        async def call_model(state: AgentState):
            await check(state["request"])
            remaining = state["request"].deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TurnTimedOut()
            count = state["model_calls"] + 1
            if count > max_model_calls:
                raise ExecutionLimit()
            writer = get_stream_writer()
            writer(ModelCallStarted(count))
            started = monotonic()
            completion = None
            parts = []
            model_request = ModelRequest(
                prompt.instructions, (profile_context(state["request"].user) or "") +
                "\n<runtime_date>" + datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date().isoformat() + "</runtime_date>",
                tuple(state["items"]), state["tools"].definitions,
            )
            try:
                async with asyncio.timeout(min(model_timeout, remaining)):
                    async with aclosing(model.stream(model_request)) as events:
                        async for event in events:
                            if completion is not None:
                                raise InvalidModelResponse()
                            if isinstance(event, TextDelta):
                                parts.append(event.text)
                                writer(event)
                            elif isinstance(event, ModelCompleted):
                                completion = event
                            else:
                                raise InvalidModelResponse()
            except TimeoutError as exc:
                if remaining <= model_timeout:
                    raise TurnTimedOut() from exc
                raise ModelTimedOut() from exc
            if completion is None or completion.text != "".join(parts):
                raise InvalidModelResponse()
            if not completion.tool_calls and not completion.text.strip():
                raise InvalidModelResponse()
            ids = [call.id for call in completion.tool_calls]
            if len(set(ids)) != len(ids) or set(ids).intersection(state["seen_calls"]):
                raise InvalidToolCall()
            metrics = {
                "duration_ms": round((monotonic() - started) * 1000, 2),
                "usage": asdict(completion.usage), "request_id": completion.request_id,
            }
            writer(ModelCallFinished(metrics))
            return {
                "items": [*state["items"], *completion.items],
                "transcript": [*state["transcript"], *completion.items],
                "response": state["response"] + completion.text, "pending": list(completion.tool_calls),
                "model_calls": count, "calls": [*state["calls"], metrics],
            }

        async def run_tools(state: AgentState):
            count, results = state["tool_calls"], []
            for call in state["pending"]:
                await check(state["request"])
                remaining = state["request"].deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TurnTimedOut()
                count += 1
                if count > max_tool_calls:
                    raise ExecutionLimit()
                get_stream_writer()(ToolCallStarted(count, call.id, call.name))
                tool_started, tool_status = monotonic(), "failed"
                try:
                    async with asyncio.timeout(min(tool_timeout, remaining)):
                        output = await state["tools"].execute(call)
                        parsed = json.loads(output)
                        tool_status = "failed" if isinstance(parsed, dict) and parsed.get("error") else "completed"
                        for event in state["tools"].take_events():
                            get_stream_writer()(event)
                except asyncio.CancelledError:
                    tool_status = "cancelled"
                    raise
                except TimeoutError as exc:
                    if remaining <= tool_timeout:
                        raise TurnTimedOut() from exc
                    raise ToolTimedOut() from exc
                finally:
                    get_stream_writer()(ToolCallFinished(call.id, call.name, tool_status,
                                                        round((monotonic() - tool_started) * 1000, 2)))
                results.append(ModelItem("tool_result", {"call_id": call.id, "output": output}, self.provider))
            return {
                "items": [*state["items"], *results],
                "transcript": [*state["transcript"], *results],
                "seen_calls": [*state["seen_calls"], *[call.id for call in state["pending"]]],
                "pending": [], "tool_calls": count,
            }

        graph = StateGraph(AgentState)
        graph.add_node("model", call_model)
        graph.add_node("tools", run_tools)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", lambda state: "tools" if state["pending"] else END)
        graph.add_edge("tools", "model")
        self.graph = graph.compile()

    async def stream(self, request: AgentRequest) -> AsyncIterator[AgentEvent]:
        final = None
        blocks = []
        try:
            stream = self.graph.astream(
                {"request": request, "tools": self.tools_factory(), "items": list(request.history.items), "transcript": [],
                 "response": "", "pending": [], "model_calls": 0, "tool_calls": 0,
                 "seen_calls": [], "calls": []},
                config={"recursion_limit": self.recursion_limit}, stream_mode=["custom", "values"],
            )
            async with aclosing(stream):
                async for mode, event in stream:
                    if mode == "custom":
                        if isinstance(event, TextDelta):
                            append_text(blocks, event.text)
                        elif isinstance(event, ChartReady):
                            blocks.append(event.block)
                        yield event
                    else:
                        final = event
        except GraphRecursionError as exc:
            raise ExecutionLimit() from exc
        if final is None or final["pending"]:
            raise InvalidModelResponse()
        yield AgentCompleted(final["response"], tuple(final["transcript"]), {
            "provider": self.provider, "model": self.model_name, "prompt_revision": self.prompt_revision,
            "model_calls": final["model_calls"], "tool_calls": final["tool_calls"],
            "calls": final["calls"], "usage": aggregate_usage(final["calls"], final["model_calls"]),
            "reasoning_effort": getattr(self, "reasoning_effort", None),
        }, tuple(blocks))
