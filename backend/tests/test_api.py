import json

import httpx
import pytest
from pydantic import ValidationError

from chatbot.app import create_app
from chatbot.config import Settings


def frames(response):
    return [
        (block.splitlines()[0].removeprefix("event: "), json.loads(block.splitlines()[1].removeprefix("data: ")))
        for block in response.text.strip().split("\n\n")
    ]


async def test_http_stream_history_isolation_and_restart(database):
    _, url = database
    settings = Settings(database_url=url, app_env="test", dev_identity_enabled=True, simulated_chunk_delay_seconds=0)
    app = create_app(settings)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200
        assert (await client.get("/v1/chat/messages")).status_code == 401
        assert (await client.get("/v1/chat/messages", headers={"X-Dev-User-Id": "unknown"})).status_code == 401
        alice = {"X-Dev-User-Id": "alice"}
        invalid = await client.post("/v1/chat/messages", headers=alice, json={"message": "  "})
        assert invalid.status_code == 422
        response = await client.post("/v1/chat/messages", headers=alice, json={"message": "hello"})
        assert response.status_code == 200
        events = frames(response)
        assert events[0][0] == "started" and events[-1][0] == "completed"
        assert sum(event == "delta" for event, _ in events) > 1
        history = (await client.get("/v1/chat/messages", headers=alice)).json()
        assert [message["role"] for message in history] == ["user", "assistant"]
        assert (await client.get("/v1/chat/messages", headers={"X-Dev-User-Id": "bob"})).json() == []
        response = await client.post("/v1/chat/messages", headers=alice, json={"message": "second"})
        assert "Received 3 messages" in frames(response)[-1][1]["text"]
    # Recreate the application to verify persistence outside graph/process state.
    restarted = create_app(settings)
    async with restarted.router.lifespan_context(restarted), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        assert len((await client.get("/v1/chat/messages", headers=alice)).json()) == 4


async def test_rate_limit_and_readiness_failure(database):
    _, url = database
    app = create_app(Settings(
        database_url=url, app_env="test", dev_identity_enabled=True,
        simulated_chunk_delay_seconds=0, rate_limit_requests=1,
    ))
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"X-Dev-User-Id": "alice"}
        assert (await client.post("/v1/chat/messages", headers=headers, json={"message": "one"})).status_code == 200
        assert (await client.post("/v1/chat/messages", headers=headers, json={"message": "two"})).status_code == 429
        from chatbot.domain.errors import Unavailable

        async def unavailable():
            raise Unavailable()

        app.state.repository.ready = unavailable
        assert (await client.get("/health/ready")).status_code == 503
        assert (await client.get("/health/live")).status_code == 200


def test_development_auth_refused_in_production():
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+asyncpg://unused", app_env="production", dev_identity_enabled=True)


async def test_mocked_openai_http_persistence_profiles_history_and_failure(database, monkeypatch, caplog):
    from sqlalchemy import select
    from chatbot.adapters.outbound.postgres.models import TurnRecord
    from tests.fakes import OpenAIHarness, response_events

    db, url = database

    def reply(body):
        if body["input"][-1].get("content") == "fail":
            return response_events("partial", status="incomplete", reason="max_output_tokens")
        return response_events("A complete finance answer.")

    harness = OpenAIHarness(reply)
    monkeypatch.setattr("chatbot.app.create_model", lambda settings: harness.model)
    app = create_app(Settings(database_url=url, app_env="test", dev_identity_enabled=True,
                              model="openai:fixture-model", openai_api_key="offline-fixture-key"))
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert harness.requests == []
        assert (await client.get("/health/ready")).status_code == 200
        assert harness.requests == []
        alice, bob = {"X-Dev-User-Id": "alice"}, {"X-Dev-User-Id": "bob"}
        first = frames(await client.post("/v1/chat/messages", headers=alice, json={"message": "PRIVATE_CHAT_BODY"}))
        assert first[-1][0] == "completed"
        metadata = first[-1][1]["metadata"]
        assert metadata["usage"]["total_tokens"] == 15
        assert metadata["model_calls"] == 1 and metadata["tool_calls"] == 0
        await client.post("/v1/chat/messages", headers=alice, json={"message": "follow-up"})
        await client.post("/v1/chat/messages", headers=bob, json={"message": "bob only"})
        failed = frames(await client.post("/v1/chat/messages", headers=alice, json={"message": "fail"}))
        assert failed[-1][0] == "error" and failed[-1][1]["code"] == "output_limit"
        assert not any(kind == "completed" for kind, _ in failed)
        history = (await client.get("/v1/chat/messages", headers=alice)).json()
        assert [item["role"] for item in history] == ["user", "assistant", "user", "assistant", "user"]
        assert len(harness.requests[1]["input"]) == 4  # Profile, first user, raw assistant, new user.
        assert len(harness.requests[2]["input"]) == 2
        assert "Alice" in harness.requests[0]["input"][0]["content"]
        assert "Bob" in harness.requests[2]["input"][0]["content"]
        async with db.session() as session:
            records = list((await session.scalars(select(TurnRecord))).all())
            completed = [record for record in records if record.status == "completed"]
            assert len(completed) == 3 and completed[0].agent_transcript
            assert completed[0].execution_metadata["usage"]["total_tokens"] == 15
            failure = next(record for record in records if record.status == "failed")
            assert failure.agent_transcript == []
            assert failure.execution_metadata["model_calls"] == 1
            assert failure.execution_metadata["usage"]["total_tokens"] is None
    assert harness.client.is_closed() and all(stream.closed for stream in harness.streams)
    assert "PRIVATE_CHAT_BODY" not in caplog.text and "offline-fixture-key" not in caplog.text
