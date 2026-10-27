from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from chatbot.domain.models import Message, Turn
from .database import Database
from .models import Conversation, MessageRecord, TurnRecord, User


def to_message(row: MessageRecord) -> Message:
    return Message(row.id, row.turn_id, row.role, row.content, row.created_at)


class PostgresConversationRepository:
    def __init__(self, database: Database):
        self.database = database

    async def ready(self):
        async with self.database.session() as session:
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "0001_initial":
                from chatbot.domain.errors import Unavailable
                raise Unavailable()
            for model in (User, Conversation, TurnRecord, MessageRecord):
                await session.execute(select(model).limit(0))

    async def user_exists(self, user_id: UUID) -> bool:
        async with self.database.session() as session:
            return await session.scalar(select(User.id).where(User.id == user_id)) is not None

    @staticmethod
    async def _messages(session, user_id: UUID) -> list[Message]:
        rows = await session.scalars(
            select(MessageRecord)
            .join(TurnRecord, MessageRecord.turn_id == TurnRecord.id)
            .join(Conversation, TurnRecord.conversation_id == Conversation.id)
            .where(Conversation.user_id == user_id)
            .order_by(TurnRecord.sequence, MessageRecord.position)
        )
        return [to_message(row) for row in rows]

    async def messages(self, user_id: UUID) -> list[Message]:
        async with self.database.session() as session:
            return await self._messages(session, user_id)

    async def begin(self, user_id: UUID, text: str) -> tuple[Turn, list[Message]]:
        # Caller holds the user-scoped lock, including for the first conversation.
        async with self.database.session() as session, session.begin():
            await session.execute(
                insert(Conversation).values(id=uuid4(), user_id=user_id)
                .on_conflict_do_nothing(index_elements=[Conversation.user_id])
            )
            conversation_id = await session.scalar(select(Conversation.id).where(Conversation.user_id == user_id))
            sequence = 1 + (await session.scalar(
                select(func.max(TurnRecord.sequence)).where(TurnRecord.conversation_id == conversation_id)
            ) or 0)
            turn = Turn(uuid4(), conversation_id, sequence)
            session.add(TurnRecord(id=turn.id, conversation_id=conversation_id, sequence=sequence, status="in_progress"))
            await session.flush()
            session.add(MessageRecord(id=uuid4(), turn_id=turn.id, position=0, role="user", content=text))
            await session.flush()
            history = await self._messages(session, user_id)
        return turn, history

    async def complete(self, turn: Turn, text: str) -> Message:
        async with self.database.session() as session, session.begin():
            row = MessageRecord(id=uuid4(), turn_id=turn.id, position=1, role="assistant", content=text)
            session.add(row)
            await session.execute(update(TurnRecord).where(TurnRecord.id == turn.id).values(
                status="completed", finished_at=datetime.now(timezone.utc)
            ))
            await session.flush()
            await session.refresh(row)
            message = to_message(row)
        return message

    async def finish(self, turn: Turn, status: str, code: str):
        async with self.database.session() as session, session.begin():
            await session.execute(update(TurnRecord).where(
                TurnRecord.id == turn.id, TurnRecord.status == "in_progress"
            ).values(status=status, error_code=code, finished_at=datetime.now(timezone.utc)))
