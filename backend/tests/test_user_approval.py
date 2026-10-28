import os
import subprocess
from uuid import uuid4

from sqlalchemy import select, text, update

from chatbot.adapters.outbound.postgres.models import User
from tests.test_auth import application, client, register, PASSWORD


async def test_upgrade_blocks_existing_accounts_and_revokes_existing_sessions(empty_database):
    db, url = empty_database
    environment = {**os.environ, 'DATABASE_URL': url}
    subprocess.run(['alembic', 'upgrade', '0003_auth_sessions'], env=environment, check=True, capture_output=True)
    user_id, session_id = uuid4(), uuid4()
    async with db.session() as sql, sql.begin():
        await sql.execute(text("INSERT INTO users(id, username, password_hash) VALUES (:id, 'existing', 'hash')"), {'id': user_id})
        await sql.execute(text("""INSERT INTO auth_sessions(id, user_id, token_verifier, csrf_token, expires_at)
            VALUES (:id, :user, :verifier, :csrf, now() + interval '1 day')"""),
            {'id': session_id, 'user': user_id, 'verifier': 'a' * 64, 'csrf': 'b' * 43})
    subprocess.run(['alembic', 'upgrade', 'head'], env=environment, check=True, capture_output=True)
    subprocess.run(['alembic', 'upgrade', 'head'], env=environment, check=True, capture_output=True)
    async with db.session() as sql:
        user = await sql.get(User, user_id)
        assert user.blocked and not user.is_admin and user.username == 'existing'
        assert await sql.scalar(text('SELECT revoked_at IS NOT NULL FROM auth_sessions WHERE id = :id'), {'id': session_id})


async def test_pending_registration_never_grants_access(database):
    db, url = database
    async with application(url) as app, client(app) as http:
        payload = dict(display_name='Pending', username='pending', password=PASSWORD, password_confirmation=PASSWORD)
        response = await http.post('/v1/auth/register', json=payload)
        assert response.status_code == 201 and response.json()['status'] == 'pending_approval'
        assert '__session' not in http.cookies
        async with db.session() as sql:
            user = await sql.scalar(select(User).where(User.username == 'pending'))
            assert user.blocked and not user.is_admin
        response = await http.post('/v1/auth/login', json={'username': 'pending', 'password': PASSWORD})
        assert response.status_code == 401 and response.json()['code'] == 'account_blocked'
        wrong = await http.post('/v1/auth/login', json={'username': 'pending', 'password': 'wrong'})
        assert wrong.status_code == 401 and wrong.json()['code'] == 'invalid_credentials'
        assert (await http.get('/v1/chat/messages')).status_code == 401
        forged = await http.post('/v1/auth/register', json={**payload, 'username': 'forged', 'is_admin': True, 'blocked': False})
        assert forged.status_code == 422


async def test_admin_approval_blocking_revocation_and_role_rechecks(database):
    db, url = database
    async with application(url) as app, client(app) as admin, client(app) as user:
        a = await register(admin, 'administrator')
        u = await register(user, 'ordinary')
        actor_id, target_id = a['user']['id'], u['user']['id']
        endpoint = '/v1/auth/admin/users/' + target_id + '/access'
        assert (await user.get('/v1/auth/admin/users')).status_code == 403
        assert (await user.post(endpoint, json={'blocked': False})).status_code == 403
        async with db.session() as sql, sql.begin():
            await sql.execute(update(User).where(User.username == 'administrator').values(is_admin=True))
        assert (await admin.get('/v1/auth/session')).json()['user']['is_admin'] is True
        listed = await admin.get('/v1/auth/admin/users')
        assert listed.status_code == 200 and len(listed.json()) == 2
        assert all('password_hash' not in row for row in listed.json())
        assert (await admin.post(endpoint, headers={'X-CSRF-Token': ''}, json={'blocked': True})).status_code == 403
        assert (await admin.post(endpoint, json={'blocked': True, 'is_admin': True})).status_code == 422
        self_url = '/v1/auth/admin/users/' + actor_id + '/access'
        assert (await admin.post(self_url, json={'blocked': True})).status_code == 403
        old_cookie = user.cookies['__session']
        assert (await admin.post(endpoint, json={'blocked': True})).status_code == 204
        assert (await user.get('/v1/chat/messages')).status_code == 401
        assert (await user.post('/v1/chat/messages', json={'message': 'must not call model'})).status_code == 401
        assert (await admin.post(endpoint, json={'blocked': False})).status_code == 204
        assert (await user.get('/v1/auth/session', headers={'Cookie': '__session=' + old_cookie})).status_code == 401
        assert (await user.post('/v1/auth/login', json={'username': 'ordinary', 'password': PASSWORD})).status_code == 200
        async with db.session() as sql, sql.begin():
            await sql.execute(update(User).where(User.username == 'administrator').values(is_admin=False))
        assert (await admin.get('/v1/auth/admin/users')).status_code == 403
        assert (await admin.post(endpoint, json={'blocked': True})).status_code == 403
