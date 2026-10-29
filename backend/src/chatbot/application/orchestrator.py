import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from time import monotonic
from uuid import UUID

import anyio

from chatbot.application.ports import AgentRunner, ConversationLock, ConversationRepository, LockLease, RateLimiter
from chatbot.domain.agent import (
    AgentCompleted, AgentEvent, AgentRequest, ModelCallFinished, ModelCallStarted,
    TextDelta, ToolCallStarted, aggregate_usage,
)
from chatbot.domain.errors import ChatError, InvalidModelResponse, Saturated, TurnTimedOut, Unavailable
from chatbot.domain.models import ChatEvent, Message, Turn, UserProfile

logger = logging.getLogger("chatbot")


def log_event(event: str, **fields):
    logger.info(json.dumps({"event": event, **fields}))


class ChatOrchestrator:
    def __init__(
        self, repository: ConversationRepository, locks: ConversationLock,
        agent: AgentRunner, limiter: RateLimiter, *, capacity: int,
        turn_timeout: float,
    ):
        self.repository = repository
        self.locks = locks
        self.agent = agent
        self.limiter = limiter
        self.capacity = capacity
        self.turn_timeout = turn_timeout
        self.active = 0

    async def history(self, user_id: UUID) -> list[Message]:
        return await self.repository.messages(user_id)

    async def open(self, user: UserProfile, text: str, request_id: str, *, check_access=None):
        self.limiter.check(user.id)
        # No await between checking and incrementing on this process's single event loop.
        if self.active >= self.capacity:
            raise Saturated()
        self.active += 1
        lease = None
        started = monotonic()
        deadline = asyncio.get_running_loop().time() + self.turn_timeout
        try:
            async with asyncio.timeout_at(deadline):
                if check_access is not None:
                    await check_access()
                lease = await self.locks.acquire(user.id)
                turn, history = await self.repository.begin(user.id, text)
            return ChatExecution(self, lease, turn, history, user, request_id, started, deadline, check_access)
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

    def __init__(self, owner, lease: LockLease, turn: Turn, history, user, request_id, started, deadline, check_access=None):
        self.owner = owner
        self.lease = lease
        self.turn = turn
        self.history = history
        self.user = user
        self.deadline = deadline
        self.request_id = request_id
        self.started = started
        self.closed = False
        self.completed = False
        self.error_code = "client_disconnected"
        self.first_chunk_ms = None
        self.model_calls = 0
        self.tool_calls = 0
        self.calls = []
        self.result = None
        self.check_access = check_access

    async def check(self):
        await self.lease.check()
        if self.check_access is not None:
            try:
                async with asyncio.timeout(2):
                    await self.check_access()
            except TimeoutError:
                raise Unavailable() from None

    def metadata(self):
        return {
            "provider": self.owner.agent.provider, "model": self.owner.agent.model_name,
            "prompt_revision": self.owner.agent.prompt_revision,
            "model_calls": self.model_calls, "tool_calls": self.tool_calls,
            "calls": self.calls, "usage": aggregate_usage(self.calls, self.model_calls),
        }

    async def _watch_lock(self, stop: asyncio.Event):
        while not stop.is_set():
            await self.check()
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                pass

    async def _chunks(self) -> AsyncIterator[AgentEvent]:
        """Race each model chunk with lock loss; always stop children before unlocking."""
        stop = asyncio.Event()
        watcher = asyncio.create_task(self._watch_lock(stop))
        next_chunk = None
        finished = False
        request = AgentRequest(self.user, self.history, self.deadline, self.check)
        async with aclosing(self.owner.agent.stream(request)) as stream:
            try:
                while True:
                    next_chunk = asyncio.create_task(anext(stream))
                    done, _ = await asyncio.wait({next_chunk, watcher}, return_when=asyncio.FIRST_COMPLETED)
                    if watcher in done:
                        watcher.result()  # raises if coordination was lost
                    try:
                        yield next_chunk.result()
                    except StopAsyncIteration:
                        finished = True
                        break
            finally:
                children = [task for task in (next_chunk, watcher) if task is not None]
                # A successful stream must let an in-flight DB check finish.
                # Cancelling its query can invalidate the connection that holds
                # the session lock, causing the final access check to fail.
                stop.set()
                for task in children:
                    if task is not watcher or not finished:
                        task.cancel()
                await asyncio.gather(*children, return_exceptions=True)
                if finished:
                    watcher.result()  # Preserve lock/access failures during shutdown.

    async def events(self) -> AsyncIterator[ChatEvent]:
        identifiers = {
            "request_id": self.request_id,
            "conversation_id": str(self.turn.conversation_id),
            "turn_id": str(self.turn.id),
        }
        try:
            yield ChatEvent("started", identifiers)
            async with asyncio.timeout_at(self.deadline):
                async with aclosing(self._chunks()) as stream:
                    async for event in stream:
                        if isinstance(event, TextDelta):
                            if self.first_chunk_ms is None:
                                self.first_chunk_ms = round((monotonic() - self.started) * 1000, 2)
                            yield ChatEvent("delta", {"text": event.text})
                        elif isinstance(event, ModelCallStarted):
                            self.model_calls = event.count
                        elif isinstance(event, ToolCallStarted):
                            self.tool_calls = event.count
                        elif isinstance(event, ModelCallFinished):
                            self.calls.append(event.metrics)
                        elif isinstance(event, AgentCompleted):
                            if self.result is not None:
                                raise InvalidModelResponse()
                            self.result = event
                if self.result is None:
                    raise InvalidModelResponse()
                await self.check()
                message = await self.owner.repository.complete(
                    self.turn, self.result.text, transcript=self.result.transcript, metadata=self.result.metadata
                )
                self.completed = True
            yield ChatEvent("completed", {
                **identifiers, "message_id": str(message.id), "text": message.content,
                "status": "completed", "metadata": self.result.metadata,
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
                            await self.owner.repository.finish(
                                self.turn, status, self.error_code, metadata=self.metadata()
                            )
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
                        model_duration_ms=sum(call["duration_ms"] for call in self.calls) if self.calls else None,
                        first_chunk_ms=self.first_chunk_ms, active_turns=self.owner.active,
                        **self.metadata(),
                    )
