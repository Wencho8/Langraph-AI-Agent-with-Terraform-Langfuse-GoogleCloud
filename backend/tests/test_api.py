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
