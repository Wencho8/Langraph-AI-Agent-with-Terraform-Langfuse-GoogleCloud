"""Offline SDK fixtures: real OpenAI parsing over a mocked HTTP transport."""

import asyncio
import json

import httpx
from openai import AsyncOpenAI

from chatbot.adapters.outbound.models.openai import OpenAIModel


def message(text, identifier="msg_1"):
    return {"type": "message", "id": identifier, "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}]}


def function(call_id="call_1", arguments='{"amount": 2}', name="double"):
    return {"type": "function_call", "id": "fc_" + call_id, "status": "completed",
            "call_id": call_id, "name": name, "arguments": arguments}


def response_events(text="Save regularly.", *, output=None, usage=True, status="completed", reason=None):
    output = [message(text)] if output is None else output
    response = {
        "id": "resp_fixture", "object": "response", "created_at": 1, "status": status,
        "model": "fixture-model", "output": output, "error": None,
        "incomplete_details": {"reason": reason} if reason else None,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                  "input_tokens_details": {"cached_tokens": 2},
                  "output_tokens_details": {"reasoning_tokens": 1}} if usage else None,
    }
    events = []
    if text:
        middle = max(1, len(text) // 2)
        for part in (text[:middle], text[middle:]):
            if part:
                events.append({"type": "response.output_text.delta", "item_id": "msg_1",
                               "output_index": 0, "content_index": 0, "delta": part, "logprobs": []})
    for item in output:
        if item["type"] == "function_call":
            arguments = item["arguments"]
            for part in (arguments[:3], arguments[3:]):
                events.append({"type": "response.function_call_arguments.delta",
                               "item_id": item["id"], "output_index": 0, "delta": part})
            events.append({"type": "response.function_call_arguments.done", "item_id": item["id"],
                           "output_index": 0, "arguments": arguments, "name": item["name"]})
    events.append({"type": f"response.{status}", "response": response})
    return [{**event, "sequence_number": index} for index, event in enumerate(events)]


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, events, delay=0):
        self.events, self.delay, self.closed = events, delay, False

    async def __aiter__(self):
        for event in self.events:
            await asyncio.sleep(self.delay)
            if isinstance(event, Exception):
                raise event
            yield ("data: " + json.dumps(event) + "\n\n").encode()

    async def aclose(self):
        self.closed = True


class OpenAIHarness:
    def __init__(self, replies, *, delay=0, status=200, model="fixture-model"):
        self.requests, self.streams = [], []

        def handle(request):
            self.requests.append(json.loads(request.content))
            reply = replies(self.requests[-1]) if callable(replies) else replies[len(self.requests) - 1]
            if status != 200:
                return httpx.Response(status, json=reply)
            stream = FixtureStream(reply, delay)
            self.streams.append(stream)
            return httpx.Response(200, stream=stream, headers={
                "Content-Type": "text/event-stream", "x-request-id": "req_fixture",
            })

        self.client = AsyncOpenAI(api_key="offline-fixture-key", max_retries=0,
                                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        self.model = OpenAIModel(self.client, model=model, max_output_tokens=2048)
