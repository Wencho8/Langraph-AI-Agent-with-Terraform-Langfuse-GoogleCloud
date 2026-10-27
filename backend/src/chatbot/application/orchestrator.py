import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from time import monotonic
from uuid import UUID

import anyio

from chatbot.application.ports import AgentRunner, ConversationLock, ConversationRepository, LockLease, RateLimiter
from chatbot.domain.errors import ChatError, ModelTimedOut, Saturated, TurnTimedOut
from chatbot.domain.models import ChatEvent, Message, Turn

logger = logging.getLogger("chatbot")


def log_event(event: str, **fields):
    logger.info(json.dumps({"event": event, **fields}))


class ChatOrchestrator:
    def __init__(
        self, repository: ConversationRepository, locks: ConversationLock,
        agent: AgentRunner, limiter: RateLimiter, *, capacity: int,
        turn_timeout: float, model_timeout: float,
    ):
        self.repository = repository
        self.locks = locks
        self.agent = agent
        self.limiter = limiter
        self.capacity = capacity
        self.turn_timeout = turn_timeout
        self.model_timeout = model_timeout
        self.active = 0

    async def history(self, user_id: UUID) -> list[Message]:
        return await self.repository.messages(user_id)

    async def open(self, user_id: UUID, text: str, request_id: str):
        self.limiter.check(user_id)
        # No await between checking and incrementing on this process's single event loop.
        if self.active >= self.capacity:
            raise Saturated()
        self.active += 1
        lease = None
        started = monotonic()
        try:
            async with asyncio.timeout(self.turn_timeout):
                lease = await self.locks.acquire(user_id)
                turn, messages = await self.repository.begin(user_id, text)
            return ChatExecution(self, lease, turn, messages, request_id, started)
        except BaseException as exc:
            with anyio.CancelScope(shield=True):
                try:
                    if lease is not None:
                        await lease.release()
                finally:
                    self.active -= 1
            if isinstance(exc, TimeoutError):
                raise TurnTimedOut() from exc
            raise


class ChatExecution:
    """Owns admission and the lease until the HTTP response finishes or is cancelled."""

    def __init__(self, owner, lease: LockLease, turn: Turn, messages, request_id, started):
        self.owner = owner
        self.lease = lease
        self.turn = turn
        self.messages = messages
        self.request_id = request_id
        self.started = started
        self.closed = False
        self.completed = False
        self.error_code = "client_disconnected"
        self.first_chunk_ms = None
        self.model_duration_ms = None
        self.model_calls = 0

    async def _watch_lock(self):
        while True:
            await self.lease.check()
            await asyncio.sleep(0.5)

    async def _chunks(self) -> AsyncIterator[str]:
        """Race each model chunk with lock loss; always stop children before unlocking."""
        watcher = asyncio.create_task(self._watch_lock())
        next_chunk = None
        async with aclosing(self.owner.agent.stream(self.messages)) as stream:
            try:
                while True:
                    next_chunk = asyncio.create_task(anext(stream))
                    done, _ = await asyncio.wait({next_chunk, watcher}, return_when=asyncio.FIRST_COMPLETED)
                    if watcher in done:
                        watcher.result()  # raises if coordination was lost
                    try:
                        yield next_chunk.result()
                    except StopAsyncIteration:
                        break
            finally:
                children = [task for task in (next_chunk, watcher) if task is not None]
                for task in children:
                    task.cancel()
                await asyncio.gather(*children, return_exceptions=True)

    async def _model_chunks(self):
        self.model_calls += 1
        try:
            async with asyncio.timeout(self.owner.model_timeout):
                async with aclosing(self._chunks()) as stream:
                    async for chunk in stream:
                        yield chunk
        except TimeoutError as exc:
            raise ModelTimedOut() from exc

    async def events(self) -> AsyncIterator[ChatEvent]:
        identifiers = {
            "request_id": self.request_id,
            "conversation_id": str(self.turn.conversation_id),
            "turn_id": str(self.turn.id),
        }
        try:
            yield ChatEvent("started", identifiers)
            parts = []
            async with asyncio.timeout_at(self.started + self.owner.turn_timeout):
                model_started = monotonic()
                async with aclosing(self._model_chunks()) as stream:
                    async for chunk in stream:
                        if self.first_chunk_ms is None:
                            self.first_chunk_ms = round((monotonic() - self.started) * 1000, 2)
                        parts.append(chunk)
                        yield ChatEvent("delta", {"text": chunk})
                self.model_duration_ms = round((monotonic() - model_started) * 1000, 2)
                await self.lease.check()
                message = await self.owner.repository.complete(self.turn, "".join(parts))
                self.completed = True
            yield ChatEvent("completed", {
                **identifiers, "message_id": str(message.id), "text": message.content,
                "status": "completed",
            })
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = TurnTimedOut() if isinstance(exc, TimeoutError) else exc
            if not isinstance(error, ChatError):
                # Avoid logging DB parameters, prompts, or provider exception bodies.
                log_event("execution_exception", exception_type=type(error).__name__, **identifiers)
                error = ChatError()
            self.error_code = error.code
            yield ChatEvent("error", {**identifiers, "code": error.code, "message": error.message})
        finally:
            await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        # Starlette cancels response tasks on disconnect. Shield finite cleanup from that scope.
        with anyio.CancelScope(shield=True):
            try:
                if not self.completed:
                    status = "cancelled" if self.error_code == "client_disconnected" else "failed"
                    try:
                        async with asyncio.timeout(5):
                            await self.owner.repository.finish(self.turn, status, self.error_code)
                    except Exception as exc:
                        log_event("turn_cleanup_failed", exception_type=type(exc).__name__, turn_id=str(self.turn.id))
            finally:
                try:
                    await self.lease.release()
                finally:
                    self.owner.active -= 1
                    log_event(
                        "turn_finished", request_id=self.request_id, turn_id=str(self.turn.id),
                        status="completed" if self.completed else self.error_code,
                        duration_ms=round((monotonic() - self.started) * 1000, 2),
                        model_duration_ms=self.model_duration_ms, first_chunk_ms=self.first_chunk_ms,
                        provider="simulated", model="deterministic", model_calls=self.model_calls,
                        tool_calls=0, token_usage=None, active_turns=self.owner.active,
                    )
