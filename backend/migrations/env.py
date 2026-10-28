import asyncio
from logging.config import fileConfig

from alembic import context

from chatbot.adapters.outbound.postgres.connections import PostgresConnections
from chatbot.adapters.outbound.postgres.models import Base
from chatbot.config import DatabaseSettings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    connections = await PostgresConnections.open(DatabaseSettings())
    engine = None
    try:
        # A migration uses one connection, not the API or advisory-lock pools.
        # DDL must not inherit the API's five-second statement timeout.
        engine = connections.engine(statement_timeout_ms=None)
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        try:
            if engine is not None:
                await engine.dispose()
        finally:
            await connections.close()


if context.is_offline_mode():
    context.configure(url=DatabaseSettings().sqlalchemy_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
