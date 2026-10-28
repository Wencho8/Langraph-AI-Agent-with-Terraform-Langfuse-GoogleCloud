import asyncio
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import pool, text

from chatbot.adapters.outbound.postgres.connections import PostgresConnections
from chatbot.adapters.outbound.postgres.database import Database
from chatbot.config import DatabaseSettings
from chatbot.domain.errors import Unavailable


def cloud_settings(**overrides):
    values = dict(
        database_mode="cloud_sql", database_url=None,
        cloud_sql_instance="fixture-project:us-central1:fixture-instance",
        database_name="chatbot", database_user="runtime@fixture-project.iam",
    )
    return DatabaseSettings(**(values | overrides))


@pytest.mark.parametrize("overrides", [
    {"cloud_sql_instance": None}, {"cloud_sql_instance": "not-an-instance-name"},
    {"database_name": None}, {"database_name": " "}, {"database_name": " chatbot"},
    {"database_user": None}, {"database_user": "runtime@fixture-project.iam.gserviceaccount.com"},
    {"database_url": "postgresql+asyncpg://localhost/local"},
    {"database_pool_size": 0}, {"database_pool_size": 17},
    {"database_connect_timeout_seconds": 0},
])
def test_cloud_settings_reject_incomplete_ambiguous_or_unbounded_configuration(overrides):
    with pytest.raises(ValidationError):
        cloud_settings(**overrides)


def test_direct_url_is_required_and_credentials_are_not_in_settings_repr():
    for value in (None, "sqlite:///local", "postgresql://localhost/local"):
        with pytest.raises(ValidationError):
            DatabaseSettings(database_mode="direct", database_url=value)
    settings = DatabaseSettings(database_mode="direct", database_url="postgresql+asyncpg://user:private-password@db/chatbot")
    assert "private-password" not in repr(settings)


async def test_direct_mode_does_not_discover_google_credentials(monkeypatch):
    import google.auth
    import google.cloud.sql.connector

    forbidden = Mock(side_effect=AssertionError("Local mode must not use Google credentials"))
    monkeypatch.setattr(google.auth, "default", forbidden)
    monkeypatch.setattr(google.cloud.sql.connector, "create_async_connector", forbidden)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/work-or-personal-credentials.json")
    settings = DatabaseSettings(database_mode="direct", database_url="postgresql+asyncpg://unused/local")
    db = await Database.open(settings, capacity=4)
    assert db.engine.url.host == "unused"
    assert db.engine.pool.size() == 6 and db.lock_engine.pool.size() == 4
    assert db.engine.pool._max_overflow == db.lock_engine.pool._max_overflow == 0
    await db.close()
    forbidden.assert_not_called()


async def test_cloud_engine_and_locks_use_async_creator_with_iam_and_no_password(monkeypatch):
    import google.cloud.sql.connector as sdk

    connector = SimpleNamespace(connect_async=AsyncMock(return_value=object()), close_async=AsyncMock())
    loops = []

    async def create_connector(**kwargs):
        loops.append(asyncio.get_running_loop())
        assert kwargs == dict(ip_type=sdk.IPTypes.PUBLIC, enable_iam_auth=True,
                              refresh_strategy="LAZY", timeout=10)
        return connector

    monkeypatch.setattr(sdk, "create_async_connector", create_connector)
    engines = Mock()
    monkeypatch.setattr("chatbot.adapters.outbound.postgres.connections.create_async_engine", engines)
    connections = await PostgresConnections.open(cloud_settings())
    connections.engine(pool_size=6)
    connections.engine(pool_size=4, autocommit=True)
    for call in engines.call_args_list:
        assert call.args == ("postgresql+asyncpg://",)
        assert call.kwargs["max_overflow"] == 0
        await call.kwargs["async_creator"]()
    assert engines.call_args_list[1].kwargs["isolation_level"] == "AUTOCOMMIT"
    assert connector.connect_async.await_count == 2
    connector.connect_async.assert_awaited_with(
        "fixture-project:us-central1:fixture-instance", "asyncpg",
        user="runtime@fixture-project.iam", db="chatbot", timeout=10,
        server_settings={"statement_timeout": "5000"},
    )
    assert loops == [asyncio.get_running_loop()]
    await connections.close()
    connector.close_async.assert_awaited_once()


async def test_cloud_failure_becomes_unavailable_without_direct_fallback(monkeypatch):
    import asyncpg
    import google.cloud.sql.connector as sdk

    connector = SimpleNamespace(connect_async=AsyncMock(side_effect=RuntimeError("IAM unavailable")),
                                close_async=AsyncMock())
    monkeypatch.setattr(sdk, "create_async_connector", AsyncMock(return_value=connector))
    direct = AsyncMock(side_effect=AssertionError("No direct fallback"))
    monkeypatch.setattr(asyncpg, "connect", direct)
    db = await Database.open(cloud_settings(), capacity=4)
    try:
        with pytest.raises(Unavailable):
            async with db.session() as session:
                await session.execute(text("SELECT 1"))
        direct.assert_not_called()
    finally:
        await db.close()
    connector.close_async.assert_awaited_once()


async def test_connector_cancellation_is_not_converted_to_an_error(monkeypatch):
    connector = SimpleNamespace(connect_async=AsyncMock(side_effect=asyncio.CancelledError()), close_async=AsyncMock())
    connections = PostgresConnections(cloud_settings(), connector)
    engines = Mock()
    monkeypatch.setattr("chatbot.adapters.outbound.postgres.connections.create_async_engine", engines)
    connections.engine(pool_size=2)
    with pytest.raises(asyncio.CancelledError):
        await engines.call_args.kwargs["async_creator"]()
    await connections.close()


async def test_cleanup_disposes_both_pools_before_connector_even_when_dispose_fails(monkeypatch):
    events = []

    async def lock_dispose():
        events.append("locks")
        raise RuntimeError("dispose failed")

    async def main_dispose():
        events.append("sessions")

    async def connector_close():
        events.append("connector")

    factory = SimpleNamespace(
        engine=Mock(side_effect=[SimpleNamespace(dispose=main_dispose), SimpleNamespace(dispose=lock_dispose)]),
        close=connector_close,
    )
    monkeypatch.setattr(PostgresConnections, "open", AsyncMock(return_value=factory))
    db = await Database.open(cloud_settings(), capacity=4)
    with pytest.raises(RuntimeError, match="dispose failed"):
        await db.close()
    assert events == ["locks", "sessions", "connector"]


async def test_migration_engine_has_no_pool_and_no_api_statement_timeout(monkeypatch):
    connector = SimpleNamespace(connect_async=AsyncMock(), close_async=AsyncMock())
    connections = PostgresConnections(cloud_settings(), connector)
    engines = Mock()
    monkeypatch.setattr("chatbot.adapters.outbound.postgres.connections.create_async_engine", engines)
    connections.engine(statement_timeout_ms=None)
    assert engines.call_args.kwargs["poolclass"] is pool.NullPool
    assert "pool_size" not in engines.call_args.kwargs
    await engines.call_args.kwargs["async_creator"]()
    assert "server_settings" not in connector.connect_async.call_args.kwargs
    await connections.close()


def test_alembic_cloud_setup_does_not_require_model_key_or_web_auth_settings(monkeypatch):
    import alembic.context as context

    monkeypatch.setenv("DATABASE_MODE", "cloud_sql")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CLOUD_SQL_INSTANCE", "fixture-project:us-central1:fixture-instance")
    monkeypatch.setenv("DATABASE_NAME", "chatbot")
    monkeypatch.setenv("DATABASE_USER", "migrations@fixture-project.iam")
    monkeypatch.setenv("MODEL", "unsupported-model-without-a-key")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_ORIGIN", "invalid-for-the-web-app")
    monkeypatch.setattr(context, "config", SimpleNamespace(config_file_name=None), raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    configured, migrated = Mock(), Mock()
    monkeypatch.setattr(context, "configure", configured)
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    monkeypatch.setattr(context, "run_migrations", migrated)

    class Connection:
        async def run_sync(self, callback):
            callback(self)

    @asynccontextmanager
    async def connect():
        yield Connection()

    engine = SimpleNamespace(connect=connect, dispose=AsyncMock())
    factory = SimpleNamespace(engine=Mock(return_value=engine), close=AsyncMock())
    opened = AsyncMock(return_value=factory)
    monkeypatch.setattr(PostgresConnections, "open", opened)
    runpy.run_path(str(Path(__file__).parents[1] / "migrations/env.py"))
    assert opened.call_args.args[0].database_mode == "cloud_sql"
    factory.engine.assert_called_once_with(statement_timeout_ms=None)
    configured.assert_called_once()
    migrated.assert_called_once()
    engine.dispose.assert_awaited_once()
    factory.close.assert_awaited_once()


async def test_cloud_pools_preserve_real_postgres_advisory_lock_and_session_behavior(database, monkeypatch):
    """Use real local PostgreSQL under a fake connector, never contact Google."""
    import asyncpg
    import google.cloud.sql.connector as sdk
    from chatbot.adapters.outbound.identity.development import DEVELOPMENT_USERS
    from chatbot.adapters.outbound.postgres.locks import PostgresConversationLock
    from chatbot.adapters.outbound.postgres.repository import PostgresConversationRepository
    from chatbot.domain.errors import SessionBusy

    local_db, url = database
    observed = []

    async def local_connect(instance, driver, **kwargs):
        observed.append((instance, driver, kwargs))
        return await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"),
                                     timeout=kwargs["timeout"], server_settings=kwargs.get("server_settings", {}))

    connector = SimpleNamespace(connect_async=AsyncMock(side_effect=local_connect), close_async=AsyncMock())
    monkeypatch.setattr(sdk, "create_async_connector", AsyncMock(return_value=connector))
    cloud_db = await Database.open(cloud_settings(), capacity=4)
    lock = None
    try:
        alice = DEVELOPMENT_USERS["alice"]
        lock = await PostgresConversationLock(cloud_db).acquire(alice)
        with pytest.raises(SessionBusy):
            await PostgresConversationLock(local_db).acquire(alice)
        await lock.check()
        repository = PostgresConversationRepository(cloud_db)
        turn, _ = await repository.begin(alice, "through mocked connector")
        await repository.complete(turn, "persisted locally")
        assert (await repository.messages(alice))[-1].content == "persisted locally"
        await lock.release()
        reacquired = await PostgresConversationLock(local_db).acquire(alice)
        await reacquired.release()
        assert observed and all(item[2]["user"] == "runtime@fixture-project.iam" for item in observed)
    finally:
        if lock is not None:
            await lock.release()
        await cloud_db.close()
    connector.close_async.assert_awaited_once()
