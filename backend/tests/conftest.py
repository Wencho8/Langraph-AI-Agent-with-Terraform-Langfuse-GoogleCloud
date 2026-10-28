import os
import subprocess
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from chatbot.adapters.outbound.postgres.database import Database
from chatbot.adapters.outbound.postgres.seed import seed


@pytest.fixture(autouse=True)
def offline_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_MODE", "direct")
    monkeypatch.setenv("MODEL", "simulated")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest_asyncio.fixture
async def empty_database():
    """An isolated DB in the existing Compose PostgreSQL; never truncate local chat data."""
    source = make_url(os.environ["DATABASE_URL"])
    name = "chatbot_test_" + uuid4().hex
    admin = create_async_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
    test_url = source.set(database=name).render_as_string(hide_password=False)
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    db = Database(test_url, 4)
    try:
        yield db, test_url
    finally:
        await db.close()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest_asyncio.fixture
async def database(empty_database):
    db, test_url = empty_database
    environment = {**os.environ, "DATABASE_URL": test_url}
    subprocess.run(["alembic", "upgrade", "head"], env=environment, check=True, capture_output=True)
    subprocess.run(["alembic", "upgrade", "head"], env=environment, check=True, capture_output=True)
    await seed(db)
    return db, test_url
