import asyncio
from contextlib import aclosing

import httpx
import pytest

from chatbot.domain.agent import ModelCompleted, ModelItem, ModelRequest, TextDelta, ToolDefinition
from chatbot.domain.errors import (
    ContextLimit, InvalidModelResponse, OutputLimit, ProviderAuthentication,
    ProviderRateLimited, ProviderRefused, ProviderUnavailable,
)
from tests.fakes import OpenAIHarness, function, message, response_events


def request(*, items=None, tools=()):
    return ModelRequest("trusted instructions", "<user_profile>Alice</user_profile>",
                        items or (ModelItem.message("user", "How can I save?"),), tools)


async def test_responses_request_stream_usage_and_no_tools():
    harness = OpenAIHarness([response_events()], model="configured-model")
    try:
        events = [event async for event in harness.model.stream(request())]
        assert [type(event) for event in events] == [TextDelta, TextDelta, ModelCompleted]
        assert "".join(event.text for event in events[:-1]) == events[-1].text
        assert events[-1].usage.total_tokens == 15
        assert events[-1].usage.reasoning_tokens == 1
        assert events[-1].request_id == "req_fixture"
        sent = harness.requests[0]
        assert sent["model"] == "configured-model"
        assert sent["store"] is False and sent["stream"] is True
        assert sent["instructions"] == "trusted instructions"
        assert sent["include"] == ["reasoning.encrypted_content"]
        assert sent["max_output_tokens"] == 2048
        assert sent["input"][0] == {"role": "user", "content": "<user_profile>Alice</user_profile>"}
        assert "tools" not in sent and "previous_response_id" not in sent
        assert "temperature" not in sent
        assert harness.streams[0].closed
    finally:
        await harness.model.close()
    assert harness.client.is_closed()


async def test_function_fragments_and_opaque_continuation_replayed_without_duplicate_text():
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque-fixture"}
    call = function()
    harness = OpenAIHarness([
        response_events("", output=[reasoning, call]), response_events("The result is 4."),
        response_events("A follow-up."),
    ])
    definition = ToolDefinition("double", "Test only", {
        "type": "object", "properties": {"amount": {"type": "number"}},
        "required": ["amount"], "additionalProperties": False,
    })
    try:
        first = [event async for event in harness.model.stream(request(tools=(definition,)))]
        completed = first[-1]
        assert completed.tool_calls[0].arguments == '{"amount": 2}'
        assert completed.tool_calls[0].id == "call_1"
        assert harness.requests[0]["tools"][0]["strict"] is True
        result = ModelItem("tool_result", {"call_id": "call_1", "output": "4"}, "openai")
        second = [event async for event in harness.model.stream(request(
            items=(*request().items, *completed.items, result), tools=(definition,)
        ))]
        assert harness.requests[1]["input"][2:] == [reasoning, call, {
            "type": "function_call_output", "call_id": "call_1", "output": "4",
        }]
        transcript = (*completed.items, result, *second[-1].items)
        history = (
            *request().items,
            ModelItem.message("assistant", second[-1].text, [item.to_dict() for item in transcript]),
            ModelItem.message("user", "Follow-up"),
        )
        _ = [event async for event in harness.model.stream(request(items=history))]
        replay = harness.requests[2]["input"]
        assert sum(item.get("type") == "function_call" for item in replay) == 1
        assert sum(item.get("type") == "message" for item in replay) == 1
        assert {"role": "assistant", "content": second[-1].text} not in replay
    finally:
        await harness.model.close()


@pytest.mark.parametrize("events,error", [
    (response_events()[:-1], InvalidModelResponse),
    (response_events(status="failed"), InvalidModelResponse),
    (response_events(status="incomplete", reason="max_output_tokens"), OutputLimit),
    (response_events(status="incomplete", reason="content_filter"), InvalidModelResponse),
    ([{"type": "response.refusal.delta", "delta": "refused", "sequence_number": 0,
       "item_id": "msg_1", "output_index": 0, "content_index": 0}], ProviderRefused),
    (response_events()[:-1] + [httpx.ReadError("private connection details")], ProviderUnavailable),
])
async def test_partial_or_failed_stream_is_never_completion(events, error):
    harness = OpenAIHarness([events])
    seen = []
    try:
        with pytest.raises(error):
            async for event in harness.model.stream(request()):
                seen.append(event)
        assert not any(isinstance(event, ModelCompleted) for event in seen)
        assert harness.streams[0].closed
    finally:
        await harness.model.close()


@pytest.mark.parametrize("status,code,error", [
    (401, "invalid_api_key", ProviderAuthentication),
    (429, "insufficient_quota", ProviderRateLimited),
    (400, "context_length_exceeded", ContextLimit),
    (503, "server_error", ProviderUnavailable),
])
async def test_safe_provider_error_mapping_no_sdk_retries(status, code, error):
    harness = OpenAIHarness([{"error": {"message": "PRIVATE_PROVIDER_BODY", "type": "invalid_request_error",
                                         "code": code}}], status=status)
    try:
        with pytest.raises(error) as caught:
            _ = [event async for event in harness.model.stream(request())]
        assert "PRIVATE_PROVIDER_BODY" not in str(caught.value)
        assert len(harness.requests) == 1
    finally:
        await harness.model.close()


async def test_mismatched_function_fragments_and_text_are_rejected():
    for events in (
        response_events("", output=[function()]),
        response_events("different", output=[message("actual")]),
    ):
        if events[0]["type"] == "response.function_call_arguments.delta":
            events[0]["delta"] = "corrupt"
        harness = OpenAIHarness([events])
        try:
            with pytest.raises(InvalidModelResponse):
                _ = [event async for event in harness.model.stream(request())]
        finally:
            await harness.model.close()


async def test_cancellation_closes_provider_http_stream():
    harness = OpenAIHarness([response_events()], delay=0.02)
    try:
        async def consume():
            async with aclosing(harness.model.stream(request())) as stream:
                async for _ in stream:
                    pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert harness.streams[0].closed
    finally:
        await harness.model.close()
