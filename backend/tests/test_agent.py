import asyncio
from contextlib import aclosing
from uuid import uuid4

import pytest

from chatbot.adapters.outbound.agent.graph import LangGraphAgent
from chatbot.application.tools import Tool, ToolRegistry
from chatbot.domain.agent import (
    AgentCompleted, AgentRequest, ChatHistory, ModelCompleted, ModelItem,
    TextDelta, TokenUsage, ToolCall, ToolDefinition,
)
from chatbot.domain.errors import ExecutionLimit, InvalidToolCall, ModelTimedOut, ToolTimedOut, TurnTimedOut
from chatbot.domain.models import UserProfile
from chatbot.prompts.loader import load_prompt


class ScriptedModel:
    provider, name = "fixture", "offline-model"

    def __init__(self, replies, delay=0):
        self.replies, self.delay, self.requests, self.closed_streams = replies, delay, [], 0

    async def stream(self, request):
        self.requests.append(request)
        try:
            await asyncio.sleep(self.delay)
            reply = self.replies[len(self.requests) - 1]
            if reply.text:
                yield TextDelta(reply.text)
            yield reply
        finally:
            self.closed_streams += 1


def tool_reply(*calls):
    return ModelCompleted("", tuple(ModelItem("provider_output", {"call_id": call.id}, "fixture")
                                    for call in calls), tuple(calls), TokenUsage(10, 5, 15))


def answer(text="The answer is 4."):
    return ModelCompleted(text, (ModelItem.message("assistant", text),), usage=TokenUsage(10, 5, 15))


def registry(handler):
    definition = ToolDefinition("double", "Test only", {
        "type": "object", "properties": {"amount": {"type": "integer"}},
        "required": ["amount"], "additionalProperties": False,
    })
    return ToolRegistry([Tool(definition, handler)])


def agent_request(name="Alice", timeout=2):
    async def check():
        pass

    return AgentRequest(UserProfile(uuid4(), name), ChatHistory((), (ModelItem.message("user", "hello"),)),
                        asyncio.get_running_loop().time() + timeout, check)


async def test_multiple_and_repeated_tools_have_independent_results_and_actual_usage():
    invoked = []

    async def double(amount):
        invoked.append(amount)
        return amount * 2

    model = ScriptedModel([
        tool_reply(ToolCall("a", "double", '{"amount": 2}'), ToolCall("b", "double", '{"amount": 3}')),
        tool_reply(ToolCall("c", "double", '{"amount": 4}')), answer(),
    ])
    agent = LangGraphAgent(model, prompt=load_prompt(), tools=registry(double))
    events = [event async for event in agent.stream(agent_request())]
    final = events[-1]
    assert isinstance(final, AgentCompleted)
    assert invoked == [2, 3, 4]
    assert final.metadata["model_calls"] == 3 and final.metadata["tool_calls"] == 3
    assert final.metadata["usage"]["total_tokens"] == 45
    assert final.metadata["usage"]["cached_tokens"] is None
    outputs = [item.data for item in model.requests[2].items if item.kind == "tool_result"]
    assert outputs == [{"call_id": "a", "output": "4"}, {"call_id": "b", "output": "6"},
                       {"call_id": "c", "output": "8"}]
    assert len(final.transcript) == 7
    assert all(request.instructions == load_prompt().instructions for request in model.requests)


@pytest.mark.parametrize("call", [
    ToolCall("a", "unknown", "{}"), ToolCall("a", "double", '{"amount":'),
    ToolCall("a", "double", '{"amount": "wrong"}'), ToolCall("a", "double", "[]"),
    ToolCall("a", "double", '{"amount": 2, "extra": 1}'), ToolCall("a", "double", '{"amount": NaN}'),
])
async def test_invalid_calls_never_invoke_handlers(call):
    invoked = []

    async def double(**arguments):
        invoked.append(arguments)

    agent = LangGraphAgent(ScriptedModel([tool_reply(call)]), prompt=load_prompt(), tools=registry(double))
    with pytest.raises(InvalidToolCall):
        _ = [event async for event in agent.stream(agent_request())]
    assert not invoked


@pytest.mark.parametrize("limits,expected_models,expected_tools", [
    ({"max_model_calls": 1}, 1, 1),
    ({"max_tool_calls": 1}, 1, 1),
    ({"recursion_limit": 2}, 1, 1),
])
async def test_model_tool_and_graph_budgets(limits, expected_models, expected_tools):
    invoked = []

    async def double(amount):
        invoked.append(amount)
        return amount * 2

    # Multiple calls ensure tool count and graph step count are different bounds.
    calls = [ToolCall("a", "double", '{"amount": 1}')]
    if "max_tool_calls" in limits:
        calls.append(ToolCall("b", "double", '{"amount": 2}'))
    model = ScriptedModel([tool_reply(*calls), answer()])
    agent = LangGraphAgent(model, prompt=load_prompt(), tools=registry(double), **limits)
    with pytest.raises(ExecutionLimit):
        _ = [event async for event in agent.stream(agent_request())]
    assert len(model.requests) == expected_models and len(invoked) == expected_tools


@pytest.mark.parametrize("kind,error", [("model", ModelTimedOut), ("tool", ToolTimedOut), ("turn", TurnTimedOut)])
async def test_operation_timeouts_and_total_deadline_cancel_work(kind, error):
    cancelled = []

    async def slow_tool(amount):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)

    model = ScriptedModel([tool_reply(ToolCall("a", "double", '{"amount": 1}')), answer()],
                          delay=0.04 if kind == "model" else 0)
    agent = LangGraphAgent(model, prompt=load_prompt(), tools=registry(slow_tool),
                          model_timeout=0.01 if kind == "model" else 1,
                          tool_timeout=0.01 if kind == "tool" else 1)
    with pytest.raises(error):
        _ = [event async for event in agent.stream(agent_request(timeout=0.01 if kind == "turn" else 2))]
    assert model.closed_streams == len(model.requests)
    if kind != "model":
        assert cancelled == [True]


async def test_shared_graph_keeps_profiles_separate_and_empty_registry_terminates():
    model = ScriptedModel([answer(), answer()], delay=0.01)
    agent = LangGraphAgent(model, prompt=load_prompt())

    async def run(name):
        return [event async for event in agent.stream(agent_request(name))]

    alice, bob = await asyncio.gather(run("Alice"), run("Bob"))
    assert "Alice" in model.requests[0].profile_context and "Bob" not in model.requests[0].profile_context
    assert "Bob" in model.requests[1].profile_context and "Alice" not in model.requests[1].profile_context
    assert all(request.tools == () for request in model.requests)
    assert alice[-1].metadata["tool_calls"] == bob[-1].metadata["tool_calls"] == 0


async def test_disconnect_during_tool_stops_handler_before_unlocking():
    from chatbot.adapters.outbound.rate_limit.memory import MemoryRateLimiter
    from chatbot.application.orchestrator import ChatOrchestrator
    from tests.test_orchestrator import Locks, Repository

    repository, locks = Repository(), Locks()
    user = UserProfile(uuid4())
    started = asyncio.Event()
    stopped = []

    async def slow_tool(amount):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(user.id in locks.held)

    model = ScriptedModel([tool_reply(ToolCall("a", "double", '{"amount": 1}'))])
    agent = LangGraphAgent(model, prompt=load_prompt(), tools=registry(slow_tool))
    service = ChatOrchestrator(repository, locks, agent, MemoryRateLimiter(20, 60), capacity=4, turn_timeout=2)
    execution = await service.open(user, "hello", "request")

    async def consume():
        async with aclosing(execution.events()) as events:
            async for _ in events:
                pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped == [True]
    assert not locks.held and service.active == 0


async def test_duplicate_call_ids_are_rejected_before_second_execution():
    invoked = []

    async def double(amount):
        invoked.append(amount)
        return amount * 2

    call = ToolCall("same", "double", '{"amount": 1}')
    agent = LangGraphAgent(ScriptedModel([tool_reply(call), tool_reply(call)]),
                          prompt=load_prompt(), tools=registry(double))
    with pytest.raises(InvalidToolCall):
        _ = [event async for event in agent.stream(agent_request())]
    assert invoked == [1]
