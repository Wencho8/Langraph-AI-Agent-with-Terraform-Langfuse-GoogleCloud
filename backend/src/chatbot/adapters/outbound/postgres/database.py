from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from chatbot.config import DatabaseSettings
from chatbot.domain.errors import Unavailable
from .connections import PostgresConnections


class Database:
    def __init__(self, url: str, capacity: int, *, pool_size: int | None = None, connections=None):
        # Keep the explicit direct constructor for local adapter/integration callers.
        self.connections = connections or PostgresConnections(
            DatabaseSettings(database_mode="direct", database_url=url)
        )
        self.engine = self.connections.engine(pool_size=pool_size if pool_size is not None else capacity + 2)
        # Session locks require a dedicated connection, not a long-running transaction.
        self.lock_engine = self.connections.engine(pool_size=capacity, autocommit=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @classmethod
    async def open(cls, settings: DatabaseSettings, capacity: int):
        connections = await PostgresConnections.open(settings)
        try:
            return cls(settings.sqlalchemy_url, capacity, pool_size=settings.database_pool_size, connections=connections)
        except BaseException:
            await connections.close()
            raise

    @asynccontextmanager
    async def session(self):
        try:
            async with self.sessions() as session:
                yield session
        except (SQLAlchemyError, OSError) as exc:
            raise Unavailable() from exc

    async def close(self):
        try:
            await self.lock_engine.dispose()
        finally:
            try:
                await self.engine.dispose()
            finally:
                await self.connections.close()
