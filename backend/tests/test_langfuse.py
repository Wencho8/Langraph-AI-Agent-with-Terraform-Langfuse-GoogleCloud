import json
from uuid import uuid4

import pytest
import pytest_asyncio
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from chatbot.adapters.outbound.agent.graph import LangGraphAgent
from chatbot.adapters.outbound.observability import langfuse
from chatbot.config import Settings
from chatbot.domain.agent import ToolCall
from chatbot.domain.models import UserProfile
from chatbot.prompts.loader import load_prompt
from tests.test_agent import ScriptedModel, answer, registry, tool_reply
from tests.test_orchestrator import consume, orchestrator


PREFIX = "langfuse.observation"
META = f"{PREFIX}.metadata"
DATABASE_URL = "postgresql+asyncpg://example/test"


@pytest_asyncio.fixture
async def tracing(monkeypatch):
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(langfuse, "Langfuse", lambda **kwargs: Langfuse(span_exporter=exporter, **kwargs))
    adapter = langfuse.LangfuseTracing.from_settings(Settings(
        database_url=DATABASE_URL, app_env="test", langfuse_public_key=f"pk-lf-{uuid4()}",
        langfuse_secret_key="offline-secret", langfuse_base_url="https://us.cloud.langfuse.com",
    ))
    assert adapter is not None
    try:
        yield adapter, exporter
    finally:
        await adapter.close()


async def test_turn_exports_nested_metrics_without_chat_content(tracing):
    adapter, exporter = tracing
    service, _, _ = orchestrator()
    service.tracing = adapter

    async def double(amount):
        return {"private-tool-result": amount * 2}

    model = ScriptedModel([
        tool_reply(ToolCall("private-tool-id-a", "double", '{"amount": 123456789}'),
                   ToolCall("private-tool-id-b", "double", '{"amount": 2}')),
        answer("private-answer"),
    ])
    model.reasoning_effort = "high"
    service.agent = LangGraphAgent(model, prompt=load_prompt(), tools=registry(double))
    user = UserProfile(uuid4(), "private-user-name")
    execution = await service.open(user, "private-question", "test-request")
    frames = await consume(execution)
    assert frames[-1].data["text"] == "private-answer"
    adapter.client.flush()
    spans = sorted(exporter.get_finished_spans(), key=lambda span: span.start_time)
    assert [span.name for span in spans] == ["chat-turn", "model-call", "double", "double", "model-call"]
    root, first, *tools, last = spans
    assert all(span.parent == root.context and span.end_time >= span.start_time for span in spans[1:])
    assert root.resource.attributes["langfuse.environment"] == "test"
    attrs = root.attributes
    assert json.loads(attrs[f"{META}.request_id"]) == "test-request"
    assert json.loads(attrs[f"{META}.turn_id"]) == str(execution.turn.id)
    assert json.loads(attrs[f"{META}.total_tokens"]) == 30
    assert json.loads(attrs[f"{META}.input_tokens"]) == 20
    assert json.loads(attrs[f"{META}.output_tokens"]) == 10
    assert json.loads(attrs[f"{META}.usage_complete"]) is True
    assert json.loads(attrs[f"{META}.duration_ms"]) >= json.loads(attrs[f"{META}.first_chunk_ms"]) >= 0
    for generation in (first, last):
        assert json.loads(generation.attributes[f"{PREFIX}.usage_details"]) == {"input": 10, "output": 5, "total": 15}
        assert json.loads(generation.attributes[f"{PREFIX}.model.parameters"]) == {"reasoning_effort": "high"}
    assert f"{PREFIX}.completion_start_time" not in first.attributes
    assert f"{PREFIX}.completion_start_time" in last.attributes
    assert all(span.attributes[f"{PREFIX}.status_message"] == "completed" for span in tools)
    assert all(f"{PREFIX}.input" not in span.attributes and f"{PREFIX}.output" not in span.attributes for span in spans)
    exported = str([dict(span.attributes) for span in spans])
    for sensitive in ("private-", "123456789", "offline-secret", str(user.id)):
        assert sensitive not in exported


@pytest.mark.parametrize("cancel", [False, True])
async def test_interrupted_turn_ends_trace_without_inventing_tokens(tracing, cancel):
    adapter, exporter = tracing
    service, _, _ = orchestrator(delay=0.04, model_timeout=1 if cancel else 0.01)
    service.tracing = adapter
    execution = await service.open(UserProfile(uuid4()), "test", "interrupted")
    if cancel:
        events = execution.events()
        await anext(events)
        assert (await anext(events)).kind == "delta"
        await events.aclose()
    else:
        assert (await consume(execution))[-1].data["code"] == "model_timeout"
    adapter.client.flush()
    generation, root = exporter.get_finished_spans()
    status = "cancelled" if cancel else "timed_out"
    assert generation.attributes[f"{PREFIX}.status_message"] == root.attributes[f"{PREFIX}.status_message"] == status
    assert f"{PREFIX}.usage_details" not in generation.attributes
    assert json.loads(root.attributes[f"{META}.usage_complete"]) is False


async def test_tracing_sdk_failure_does_not_interrupt_chat(tracing, monkeypatch, caplog):
    def broken_start(**kwargs):
        raise RuntimeError("private provider error")

    adapter, _ = tracing
    monkeypatch.setattr(adapter.client, "start_observation", broken_start)
    service, _, locks = orchestrator()
    service.tracing = adapter
    execution = await service.open(UserProfile(uuid4()), "test", "sdk-failure")
    assert (await consume(execution))[-1].kind == "completed"
    assert not locks.held
    assert "langfuse_observation_start_failed" in caplog.text
    assert "private provider error" not in caplog.text


def test_no_client_is_created_without_credentials(monkeypatch):
    def unexpected(**kwargs):
        pytest.fail("Unconfigured tracing should not create a client")

    monkeypatch.setattr(langfuse, "Langfuse", unexpected)
    assert langfuse.LangfuseTracing.from_settings(Settings(database_url=DATABASE_URL)) is None
