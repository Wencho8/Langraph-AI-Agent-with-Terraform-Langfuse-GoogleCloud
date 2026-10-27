from datetime import datetime, timezone
from uuid import uuid4

import pytest

from chatbot.adapters.outbound.agent.graph import LangGraphAgent
from chatbot.adapters.outbound.agent.simulated_model import SimulatedModel
from chatbot.adapters.outbound.rate_limit.memory import MemoryRateLimiter
from chatbot.application.orchestrator import ChatOrchestrator
from chatbot.domain.errors import SessionBusy, Saturated, Unavailable
from chatbot.domain.models import Message, Turn


class Repository:
    def __init__(self):
        self.history = {}
        self.status = {}
        self.fail_save = False

    async def messages(self, user_id):
        return list(self.history.get(user_id, []))

    async def begin(self, user_id, text):
        turn = Turn(uuid4(), user_id, 1)
        self.status[turn.id] = "in_progress"
        self.history.setdefault(user_id, []).append(
            Message(uuid4(), turn.id, "user", text, datetime.now(timezone.utc))
        )
        return turn, list(self.history[user_id])

    async def complete(self, turn, text):
        if self.fail_save:
            raise Unavailable()
        message = Message(uuid4(), turn.id, "assistant", text, datetime.now(timezone.utc))
        self.history[turn.conversation_id].append(message)
        self.status[turn.id] = "completed"
        return message

    async def finish(self, turn, status, code):
        self.status[turn.id] = status


class Locks:
    def __init__(self):
        self.held = set()
        self.lost = False

    async def acquire(self, user_id):
        if user_id in self.held:
            raise SessionBusy()
        self.held.add(user_id)
        owner = self

        class Lease:
            async def check(self):
                if owner.lost:
                    raise Unavailable()

            async def release(self):
                owner.held.discard(user_id)

        return Lease()


def orchestrator(*, delay=0, capacity=4, model_timeout=1):
    repository, locks = Repository(), Locks()
    agent = LangGraphAgent(SimulatedModel(delay), max_model_calls=1, recursion_limit=4)
    service = ChatOrchestrator(
        repository, locks, agent, MemoryRateLimiter(100, 60),
        capacity=capacity, turn_timeout=2, model_timeout=model_timeout,
    )
    return service, repository, locks


async def consume(execution):
    return [event async for event in execution.events()]


async def test_full_history_and_independent_users():
    service, repository, _ = orchestrator()
    alice, bob = uuid4(), uuid4()
    first = await consume(await service.open(alice, "first", "a1"))
    second = await consume(await service.open(alice, "second", "a2"))
    other = await consume(await service.open(bob, "bob only", "b1"))
    assert first[0].kind == "started" and first[-1].kind == "completed"
    assert "Received 3 messages" in second[-1].data["text"]
    assert "Received 1 messages" in other[-1].data["text"]
    assert [m.content for m in repository.history[alice] if m.role == "user"] == ["first", "second"]
    assert service.active == 0


async def test_busy_first_message_capacity_and_release():
    service, _, locks = orchestrator(capacity=2)
    alice, bob = uuid4(), uuid4()
    first = await service.open(alice, "one", "1")
    with pytest.raises(SessionBusy):
        await service.open(alice, "overlap", "2")
    second = await service.open(bob, "two", "3")
    with pytest.raises(Saturated):
        await service.open(uuid4(), "three", "4")
    await first.close()
    await second.close()
    assert service.active == 0 and not locks.held
    await consume(await service.open(alice, "retry", "5"))


async def test_model_timeout_is_terminal_error_and_unlocks():
    service, repository, locks = orchestrator(delay=0.1, model_timeout=0.02)
    events = await consume(await service.open(uuid4(), "slow", "1"))
    assert events[-1].kind == "error" and events[-1].data["code"] == "model_timeout"
    assert list(repository.status.values()) == ["failed"]
    assert not locks.held and service.active == 0


async def test_total_deadline_is_distinct_from_model_timeout():
    service, repository, locks = orchestrator(delay=0.1, model_timeout=1)
    service.turn_timeout = 0.02
    events = await consume(await service.open(uuid4(), "deadline", "1"))
    assert events[-1].data["code"] == "turn_timeout"
    assert list(repository.status.values()) == ["failed"]
    assert not locks.held and service.active == 0


async def test_save_failure_does_not_emit_completed():
    service, repository, locks = orchestrator()
    repository.fail_save = True
    events = await consume(await service.open(uuid4(), "hello", "1"))
    assert "delta" in [event.kind for event in events]
    assert events[-1].kind == "error"
    assert "completed" not in [event.kind for event in events]
    assert not locks.held and service.active == 0


async def test_closing_stream_cancels_graph_before_unlocking():
    service, repository, locks = orchestrator(delay=0.01)
    execution = await service.open(uuid4(), "cancel me", "1")
    events = execution.events()
    assert (await anext(events)).kind == "started"
    assert (await anext(events)).kind == "delta"
    await events.aclose()
    assert list(repository.status.values()) == ["cancelled"]
    assert not locks.held and service.active == 0


async def test_lock_loss_stops_a_waiting_model():
    service, repository, locks = orchestrator(delay=0.1)
    execution = await service.open(uuid4(), "many words to keep streaming alive for a while", "1")
    events = execution.events()
    await anext(events)
    await anext(events)
    locks.lost = True
    remaining = [event async for event in events]
    assert remaining[-1].kind == "error"
    assert remaining[-1].data["code"] == "dependency_unavailable"
    assert list(repository.status.values()) == ["failed"]
    assert not locks.held and service.active == 0
