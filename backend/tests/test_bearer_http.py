"""HTTP transport checks with mocked auth storage; no database or external requests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from chatbot.app import create_app
from chatbot.config import Settings
from chatbot.domain.auth import AuthSession, SessionGrant
from chatbot.domain.errors import Unauthorized
from chatbot.domain.models import UserProfile
from tests.test_orchestrator import orchestrator

ORIGIN = 'https://frontend.example'
TOKEN = 'a' * 43


@pytest.fixture
async def http():
    settings = Settings(database_url='postgresql+asyncpg://unused', app_env='test', app_origin=ORIGIN)
    app = create_app(settings)
    session = AuthSession(uuid4(), UserProfile(uuid4(), 'Alice'), 'alice', 'unused-csrf',
                          datetime.now(timezone.utc) + timedelta(days=1))
    revoked = set()

    async def resolve(token):
        if token != TOKEN or token in revoked:
            raise Unauthorized()
        return session

    async def logout(token):
        revoked.add(token)

    app.state.settings = settings
    app.state.auth = SimpleNamespace(
        login=AsyncMock(return_value=SessionGrant(TOKEN, session)), resolve=AsyncMock(side_effect=resolve),
        logout=AsyncMock(side_effect=logout), check=AsyncMock(),
    )
    app.state.orchestrator, _, _ = orchestrator()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://api.example',
                                 headers={'Origin': ORIGIN}) as client:
        yield client


async def test_login_bearer_history_stream_and_logout_replay(http, caplog):
    response = await http.post('/v1/auth/login', json={'username': 'alice', 'password': 'fixture-password'})
    assert response.status_code == 200
    assert response.json()['access_token'] == TOKEN and response.json()['token_type'] == 'Bearer'
    assert 'set-cookie' not in response.headers and 'csrf_token' not in response.json()
    http.headers['Authorization'] = 'Bearer ' + TOKEN
    assert (await http.get('/v1/auth/session')).json()['user']['username'] == 'alice'
    response = await http.post('/v1/chat/messages', json={'message': 'Hello'})
    assert response.headers['content-type'].startswith('text/event-stream')
    assert 'event: started' in response.text and 'event: completed' in response.text
    assert response.headers['access-control-allow-origin'] == ORIGIN
    assert len((await http.get('/v1/chat/messages')).json()) == 2
    assert (await http.post('/v1/auth/logout', json={})).status_code == 204
    assert (await http.get('/v1/auth/session')).status_code == 401
    assert TOKEN not in caplog.text


@pytest.mark.parametrize('authorization', ['', 'Basic abc', 'Bearer', 'Bearer wrong', 'Bearer a b'])
async def test_cookie_cannot_replace_missing_or_invalid_bearer(http, authorization):
    response = await http.get('/v1/auth/session', headers={'Authorization': authorization, 'Cookie': '__session=' + TOKEN})
    assert response.status_code == 401
    assert response.headers['access-control-allow-origin'] == ORIGIN


async def test_cors_preflight_and_rejected_origin(http):
    headers = {'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'}
    response = await http.options('/v1/chat/messages', headers=headers)
    assert response.status_code == 200 and response.headers['access-control-allow-origin'] == ORIGIN
    assert 'authorization' in response.headers['access-control-allow-headers'].lower()
    assert 'access-control-allow-credentials' not in response.headers
    response = await http.options('/v1/chat/messages', headers={**headers, 'Origin': 'https://evil.example'})
    assert response.status_code == 400 and 'access-control-allow-origin' not in response.headers
    response = await http.post('/v1/auth/login', headers={'Origin': 'https://evil.example'}, json={})
    assert response.status_code == 403
