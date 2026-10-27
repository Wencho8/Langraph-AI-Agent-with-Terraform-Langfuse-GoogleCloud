from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chatbot.domain.errors import Unavailable


class Database:
    def __init__(self, url: str, capacity: int):
        options = dict(pool_pre_ping=True, pool_timeout=2, max_overflow=0)
        connect_args = {"server_settings": {"statement_timeout": "5000"}}
        self.engine = create_async_engine(url, pool_size=capacity + 2, connect_args=connect_args, **options)
        # Session locks require a dedicated connection, not a long-running transaction.
        self.lock_engine = create_async_engine(
            url, pool_size=capacity, isolation_level="AUTOCOMMIT", connect_args=connect_args, **options
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self):
        try:
            async with self.sessions() as session:
                yield session
        except (SQLAlchemyError, OSError) as exc:
            raise Unavailable() from exc

    async def close(self):
        await self.lock_engine.dispose()
        await self.engine.dispose()
