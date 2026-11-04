import asyncio

import anyio
from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from chatbot.application.ports import PasswordHasher
from chatbot.domain.errors import AuthBusy


class Argon2Passwords(PasswordHasher):
    """Two admitted CPU operations; cancellation waits for the hash before freeing its slot."""

    def __init__(self):
        self.hasher = Argon2PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1, type=Type.ID)
        self.active = 0

    async def _run(self, function, *args):
        if self.active >= 2:
            raise AuthBusy()
        self.active += 1
        task = asyncio.create_task(anyio.to_thread.run_sync(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        finally:
            self.active -= 1

    async def hash(self, password: str) -> str:
        return await self._run(self.hasher.hash, password)

    async def verify(self, encoded: str, password: str) -> bool:
        try:
            return await self._run(self.hasher.verify, encoded, password)
        except (VerificationError, InvalidHashError):
            return False
