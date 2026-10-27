import asyncio
import hashlib
from uuid import UUID

from sqlalchemy import text

from chatbot.domain.errors import SessionBusy, Unavailable
from .database import Database


class PostgresLease:
    def __init__(self, connection, key: int, backend_pid: int):
        self.connection = connection
        self.key = key
        self.backend_pid = backend_pid
        self.released = False
        self.operation = asyncio.Lock()

    async def check(self):
        try:
            if self.connection.closed or self.connection.invalidated:
                raise Unavailable()
            async with self.operation:
                pid = await self.connection.scalar(text("SELECT pg_backend_pid()"))
            if pid != self.backend_pid:
                raise Unavailable()
        except Exception as exc:
            raise Unavailable() from exc

    async def release(self):
        if self.released:
            return
        self.released = True
        try:
            if self.connection.invalidated:
                return
            unlocked = await self.connection.scalar(
                text("SELECT pg_advisory_unlock(:key)"), {"key": self.key}
            )
            if not unlocked:
                await self.connection.invalidate()
        except Exception:
            # Never return a potentially locked physical connection to the pool.
            await self.connection.invalidate()
        finally:
            await self.connection.close()


class PostgresConversationLock:
    def __init__(self, database: Database):
        self.database = database

    async def acquire(self, user_id: UUID) -> PostgresLease:
        key = int.from_bytes(hashlib.blake2b(user_id.bytes, digest_size=8).digest(), "big", signed=True)
        connection = None
        try:
            connection = await self.database.lock_engine.connect()
            acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            if not acquired:
                raise SessionBusy()
            pid = await connection.scalar(text("SELECT pg_backend_pid()"))
            return PostgresLease(connection, key, pid)
        except BaseException as exc:
            if connection is not None:
                # Acquisition may have succeeded just before cancellation: discard it.
                await connection.invalidate()
                await connection.close()
            if isinstance(exc, (SessionBusy, Unavailable)) or not isinstance(exc, Exception):
                raise
            raise Unavailable() from exc
