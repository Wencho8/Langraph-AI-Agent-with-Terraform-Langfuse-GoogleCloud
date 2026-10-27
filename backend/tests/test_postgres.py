import pytest
from sqlalchemy import insert

from chatbot.adapters.outbound.identity.development import DEVELOPMENT_USERS
from chatbot.adapters.outbound.postgres.database import Database
from chatbot.adapters.outbound.postgres.locks import PostgresConversationLock
from chatbot.adapters.outbound.postgres.models import Conversation
from chatbot.adapters.outbound.postgres.repository import PostgresConversationRepository
from chatbot.domain.errors import SessionBusy, Unavailable


async def test_real_locks_coordinate_independent_connection_pools(database):
    db, url = database
    other = Database(url, 2)
    first = await PostgresConversationLock(db).acquire(DEVELOPMENT_USERS["alice"])
    try:
        with pytest.raises(SessionBusy):
            await PostgresConversationLock(other).acquire(DEVELOPMENT_USERS["alice"])
        independent = await PostgresConversationLock(other).acquire(DEVELOPMENT_USERS["bob"])
        await independent.release()
        await first.check()
        await first.release()
        reacquired = await PostgresConversationLock(other).acquire(DEVELOPMENT_USERS["alice"])
        await reacquired.release()
    finally:
        await first.release()
        await other.close()


async def test_migrated_schema_persistence_and_unique_conversation(database):
    db, _ = database
    repository = PostgresConversationRepository(db)
    await repository.ready()
    alice = DEVELOPMENT_USERS["alice"]
    turn, history = await repository.begin(alice, "one")
    assert len(history) == 1
    await repository.complete(turn, "response")
    second, history = await repository.begin(alice, "two")
    assert second.sequence == 2 and [m.content for m in history] == ["one", "response", "two"]
    from uuid import uuid4
    with pytest.raises(Unavailable):
        async with db.session() as session, session.begin():
            await session.execute(insert(Conversation).values(id=uuid4(), user_id=alice))
