import pytest
from sqlalchemy import insert, text, update

from chatbot.adapters.outbound.identity.development import DEVELOPMENT_USERS
from chatbot.adapters.outbound.postgres.database import Database
from chatbot.adapters.outbound.postgres.locks import PostgresConversationLock
from chatbot.adapters.outbound.postgres.models import Conversation, TurnRecord, User
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
    assert len(history.messages) == 1
    await repository.complete(turn, "response")
    second, history = await repository.begin(alice, "two")
    assert second.sequence == 2 and [m.content for m in history.messages] == ["one", "response", "two"]
    from uuid import uuid4
    with pytest.raises(Unavailable):
        async with db.session() as session, session.begin():
            await session.execute(insert(Conversation).values(id=uuid4(), user_id=alice))


async def test_transcript_metadata_and_profile_seed_preserve_user_values(database):
    from chatbot.adapters.outbound.postgres.seed import seed
    from chatbot.domain.agent import ModelItem

    db, _ = database
    repository = PostgresConversationRepository(db)
    alice = DEVELOPMENT_USERS["alice"]
    async with db.session() as session, session.begin():
        await session.execute(update(User).where(User.id == alice).values(display_name="Custom name"))
    await seed(db)
    assert (await repository.profile(alice)).display_name == "Custom name"
    turn, _ = await repository.begin(alice, "first")
    transcript = (ModelItem("provider_output", {"type": "reasoning", "encrypted_content": "opaque"}, "openai"),
                  ModelItem.message("assistant", "saved answer"))
    await repository.complete(turn, "saved answer", transcript=transcript, metadata={"model_calls": 2})
    _, history = await repository.begin(alice, "next")
    assert [message.content for message in history.messages] == ["first", "saved answer", "next"]
    assert history.items[1].data["transcript"] == [item.to_dict() for item in transcript]
    async with db.session() as session:
        record = await session.get(TurnRecord, turn.id)
        assert record.status == "completed" and record.execution_metadata == {"model_calls": 2}
        assert len(record.agent_transcript) == 2


async def test_upgrade_from_iteration_one_keeps_old_messages_and_checks_current_head(empty_database):
    import os
    import subprocess
    from uuid import uuid4

    db, url = empty_database
    environment = {**os.environ, "DATABASE_URL": url}

    def migrate(revision):
        subprocess.run(["alembic", "upgrade", revision], env=environment, check=True, capture_output=True)

    migrate("0001_initial")
    alice, conversation, turn, message_id = DEVELOPMENT_USERS["alice"], uuid4(), uuid4(), uuid4()
    async with db.session() as session, session.begin():
        await session.execute(text("INSERT INTO users(id) VALUES (:id)"), {"id": alice})
        await session.execute(text("INSERT INTO conversations(id,user_id) VALUES (:id,:user)"),
                              {"id": conversation, "user": alice})
        await session.execute(text("INSERT INTO turns(id,conversation_id,sequence,status) VALUES (:id,:conversation,1,'completed')"),
                              {"id": turn, "conversation": conversation})
        await session.execute(text("INSERT INTO messages(id,turn_id,position,role,content) VALUES (:id,:turn,0,'user','old message')"),
                              {"id": message_id, "turn": turn})
    repository = PostgresConversationRepository(db)
    with pytest.raises(Unavailable):
        await repository.ready()
    migrate("head")
    migrate("head")
    await repository.ready()
    assert (await repository.profile(alice)).display_name == "Alice"
    assert (await repository.messages(alice))[0].id == message_id
    async with db.session() as session:
        record = await session.get(TurnRecord, turn)
        assert record.agent_transcript == [] and record.execution_metadata == {}
