import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import secrets
import threading

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from chatbot.app import create_app
from chatbot.config import Settings
from chatbot.adapters.outbound.identity.passwords import Argon2Passwords
from chatbot.adapters.outbound.postgres.models import AuthSessionRecord, TurnRecord, User
from chatbot.adapters.outbound.rate_limit.auth import MemoryAuthLimiter
from chatbot.domain.errors import AuthBusy, AuthRateLimited
from tests.test_api import frames

ORIGIN = 'http://localhost:5173'
PASSWORD = 'a sufficiently long password'


@asynccontextmanager
async def application(url, **overrides):
    app = create_app(Settings(database_url=url, app_env='test', auth_mode='session',
                              auth_registration_limit=100, auth_login_limit=100,
                              simulated_chunk_delay_seconds=overrides.pop('delay', 0), **overrides))
    async with app.router.lifespan_context(app):
        yield app


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Origin': ORIGIN})


async def register(http, username='alice-auth', name='Alice'):
    response = await http.post('/v1/auth/register', json={
        'display_name': name, 'username': username, 'password': PASSWORD, 'password_confirmation': PASSWORD,
    })
    assert response.status_code == 201, response.text
    app = http._transport.app
    async with app.state.auth.repository.database.session() as sql, sql.begin():
        await sql.execute(update(User).where(User.username == username.strip().lower()).values(blocked=False))
    response = await http.post('/v1/auth/login', json={'username': username, 'password': PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    http.headers['Authorization'] = 'Bearer ' + body.pop('access_token')
    assert body.pop('token_type') == 'Bearer'
    return body


async def test_registration_login_storage_validation_and_restart(database, caplog):
    db, url = database
    async with application(url) as app, client(app) as http:
        session = await register(http, '  ALICE-auth  ', ' Alice & <rules> ')
        assert session['user']['username'] == 'alice-auth'
        assert session['user']['display_name'] == 'Alice & <rules>'
        token = http.headers['Authorization'].removeprefix('Bearer ')
        restored = await http.get('/v1/auth/session')
        assert restored.json() == session and restored.headers['cache-control'] == 'no-store'
        authorization = restored.request.headers['authorization']
        async with db.session() as sql:
            user = await sql.scalar(select(User).where(User.username == 'alice-auth'))
            stored = await sql.scalar(select(AuthSessionRecord).where(AuthSessionRecord.user_id == user.id))
            assert user.password_hash.startswith('$argon2id$') and PASSWORD not in user.password_hash
            assert token not in stored.token_verifier and len(stored.token_verifier) == 64
        duplicate = await http.post('/v1/auth/register', json={
            'display_name': 'Other', 'username': 'ALICE-AUTH', 'password': PASSWORD, 'password_confirmation': PASSWORD,
        })
        assert duplicate.status_code == 409
        async with client(app) as first, client(app) as second:
            payload = {'display_name': 'Concurrent', 'username': 'race-user',
                       'password': PASSWORD, 'password_confirmation': PASSWORD}
            raced = await asyncio.gather(first.post('/v1/auth/register', json=payload),
                                         second.post('/v1/auth/register', json=payload))
            assert sorted(result.status_code for result in raced) == [201, 409]
        for patch in ({'password': 'short'}, {'password_confirmation': 'DIFFERENT_SECRET'}, {'user_id': 'forged'}):
            response = await http.post('/v1/auth/register', json={
                'display_name': 'Safe', 'username': 'another-user', 'password': PASSWORD,
                'password_confirmation': PASSWORD, **patch,
            })
            assert response.status_code == 422
            assert PASSWORD not in response.text and 'DIFFERENT_SECRET' not in response.text
        async with client(app) as login:
            wrong = await login.post('/v1/auth/login', json={'username': 'alice-auth', 'password': 'incorrect'})
            missing = await login.post('/v1/auth/login', json={'username': 'not-present', 'password': 'incorrect'})
            assert wrong.status_code == missing.status_code == 401 and wrong.json() == missing.json()
            response = await login.post('/v1/auth/login', json={'username': 'ALICE-auth', 'password': PASSWORD})
            assert response.status_code == 200 and response.json()['access_token'] != token
            assert 'set-cookie' not in response.headers
            assert response.json()['token_type'] == 'Bearer'
            assert 'password_hash' not in response.text
    async with application(url) as restarted, client(restarted) as http:
        response = await http.get('/v1/auth/session', headers={'Authorization': authorization})
        assert response.status_code == 200
    assert PASSWORD not in caplog.text and token not in caplog.text


async def test_ownership_bearer_logout_replay_and_independent_device(database):
    _, url = database
    async with application(url) as app, client(app) as alice, client(app) as bob, client(app) as other_device:
        a, b = await register(alice), await register(bob, 'bob-auth', 'Bob')
        old_token = alice.headers['Authorization']
        response = await alice.post('/v1/chat/messages', json={'message': 'ALICE_PRIVATE'})
        assert frames(response)[-1][0] == 'completed' and response.headers['cache-control'] == 'no-store'
        history = await bob.get('/v1/chat/messages', headers={'X-Dev-User-Id': a['user']['id']}, params={'user_id': a['user']['id']})
        assert history.json() == []
        forged = await bob.post('/v1/chat/messages', json={'message': 'attempt', 'user_id': a['user']['id']})
        assert forged.status_code == 422
        for headers in ({'Origin': 'https://untrusted.test'}, {'Origin': ''}):
            denied = await alice.post('/v1/chat/messages', headers=headers, json={'message': 'denied'})
            assert denied.status_code == 403
        denied_logout = await alice.post('/v1/auth/logout', headers={'Origin': 'https://evil.test'}, json={})
        assert denied_logout.status_code == 403
        response = await other_device.post('/v1/auth/login', json={'username': 'alice-auth', 'password': PASSWORD})
        assert response.status_code == 200
        other_device.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
        assert (await alice.post('/v1/auth/logout', json={})).status_code == 204
        replay = await alice.get('/v1/chat/messages', headers={'Authorization': old_token})
        assert replay.status_code == 401
        assert (await other_device.get('/v1/chat/messages')).json()[0]['content'] == 'ALICE_PRIVATE'
        assert (await bob.get('/v1/chat/messages')).json() == []
        # The development header cannot replace a missing session in normal mode.
        assert (await alice.get('/v1/chat/messages', headers={'X-Dev-User-Id': 'alice'})).status_code == 401


async def test_expiry_rotation_limits_and_origin_guard(database):
    db, url = database
    async with application(url) as app, client(app) as http:
        denied = await http.post('/v1/auth/register', headers={'Origin': 'https://evil.test'}, json={})
        assert denied.status_code == 403
        await register(http)
        old = http.headers['Authorization']
        login = await http.post('/v1/auth/login', json={'username': 'alice-auth', 'password': PASSWORD})
        assert login.status_code == 200
        http.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
        assert (await http.get('/v1/auth/session', headers={'Authorization': old})).status_code == 401
        async with db.session() as sql, sql.begin():
            await sql.execute(update(AuthSessionRecord).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        assert (await http.get('/v1/auth/session')).status_code == 401
        http.headers['Authorization'] = 'Bearer ' + secrets.token_urlsafe(32)
        assert (await http.get('/v1/auth/session')).status_code == 401
        app.state.auth.login_limit = 1
        app.state.auth.limiter = MemoryAuthLimiter()
        wrong = {'username': 'alice-auth', 'password': 'wrong'}
        assert (await http.post('/v1/auth/login', json=wrong)).status_code == 401
        limit = await http.post('/v1/auth/login', headers={'X-Forwarded-For': 'another-ip'}, json=wrong)
        assert limit.status_code == 429 and limit.headers['retry-after'] == '60'


@pytest.mark.parametrize('action', ['logout', 'expire', 'block'])
async def test_revoking_a_running_stream_stops_generation_and_unlocks(database, action):
    db, url = database
    async with application(url, delay=0.1) as app, client(app) as http:
        await register(http)
        pending = asyncio.create_task(http.post('/v1/chat/messages', json={'message': 'waiting ' * 100}))
        for _ in range(100):
            async with db.session() as sql:
                turn = await sql.scalar(select(TurnRecord).where(TurnRecord.status == 'in_progress'))
            if turn:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail('Turn did not start')
        if action == 'logout':
            assert (await http.post('/v1/auth/logout', json={})).status_code == 204
        elif action == 'block':
            async with db.session() as sql, sql.begin():
                await sql.execute(update(User).where(User.username == 'alice-auth').values(blocked=True))
        else:
            async with db.session() as sql, sql.begin():
                await sql.execute(update(AuthSessionRecord).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        response = await asyncio.wait_for(pending, 4)
        events = frames(response)
        assert events[-1][0] == 'error' and events[-1][1]['code'] == 'unauthenticated'
        assert not any(name == 'completed' for name, _ in events)
        assert app.state.orchestrator.active == 0
        async with db.session() as sql:
            saved = await sql.get(TurnRecord, turn.id)
            assert saved.status == 'failed'


async def test_password_work_is_bounded_nonblocking_and_finishes_before_cancellation_releases_slot():
    passwords = Argon2Passwords()
    started = threading.Event()
    release = threading.Event()

    def slow_hash(value):
        started.set()
        release.wait(timeout=2)
        return 'fixture-hash'

    from types import SimpleNamespace
    passwords.hasher = SimpleNamespace(hash=slow_hash)
    first = asyncio.create_task(passwords.hash('test'))
    while not started.is_set():
        await asyncio.sleep(0.001)
    second = asyncio.create_task(passwords.hash('test'))
    await asyncio.sleep(0.01)
    with pytest.raises(AuthBusy):
        await passwords.hash('third')
    first.cancel()
    await asyncio.sleep(0.01)
    assert passwords.active == 2 and not first.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert passwords.active == 0


def test_auth_limit_storage_and_production_settings():
    limiter = MemoryAuthLimiter(capacity=1)
    limiter.check([('one', 1)])
    with pytest.raises(AuthRateLimited):
        limiter.check([('two', 1)])
    for overrides in ({'auth_mode': 'development'}, {'app_origin': 'http://example.com'}):
        settings = {'database_url': 'postgresql+asyncpg://unused', 'app_env': 'production',
                    'app_origin': 'https://example.com', **overrides}
        with pytest.raises(ValidationError):
            Settings(**settings)
