from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from chatbot.domain.agent import ChatHistory, ModelItem
from chatbot.domain.errors import Unavailable
from chatbot.domain.models import Message, Turn, UserProfile
from .database import Database
from .models import Conversation, MessageRecord, TurnRecord, User


def to_message(row: MessageRecord) -> Message:
    return Message(row.id, row.turn_id, row.role, row.content, row.created_at)


class PostgresConversationRepository:
    def __init__(self, database: Database):
        self.database = database
        configuration = Path("alembic.ini")
        if not configuration.is_file():
            configuration = Path("backend/alembic.ini")
        self.schema_head = ScriptDirectory.from_config(Config(str(configuration))).get_current_head()

    async def ready(self):
        async with self.database.session() as session:
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != self.schema_head:
                raise Unavailable()
            for model in (User, Conversation, TurnRecord, MessageRecord):
                await session.execute(select(model).limit(0))

    async def profile(self, user_id: UUID) -> UserProfile | None:
        async with self.database.session() as session:
            user = await session.get(User, user_id)
            return UserProfile(user.id, user.display_name) if user is not None else None

    @staticmethod
    async def _history(session, user_id: UUID) -> ChatHistory:
        rows = await session.execute(
            select(MessageRecord, TurnRecord.agent_transcript)
            .join(TurnRecord, MessageRecord.turn_id == TurnRecord.id)
            .join(Conversation, TurnRecord.conversation_id == Conversation.id)
            .where(Conversation.user_id == user_id)
            .order_by(TurnRecord.sequence, MessageRecord.position)
        )
        messages, items = [], []
        for row, transcript in rows:
            message = to_message(row)
            messages.append(message)
            items.append(ModelItem.message(
                message.role, message.content, transcript if message.role == "assistant" else None
            ))
        return ChatHistory(tuple(messages), tuple(items))

    async def messages(self, user_id: UUID) -> list[Message]:
        async with self.database.session() as session:
            return list((await self._history(session, user_id)).messages)

    async def begin(self, user_id: UUID, text: str) -> tuple[Turn, ChatHistory]:
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
            history = await self._history(session, user_id)
        return turn, history

    async def complete(self, turn: Turn, text: str, *, transcript=(), metadata=None) -> Message:
        async with self.database.session() as session, session.begin():
            row = MessageRecord(id=uuid4(), turn_id=turn.id, position=1, role="assistant", content=text)
            session.add(row)
            await session.execute(update(TurnRecord).where(TurnRecord.id == turn.id).values(
                status="completed", finished_at=datetime.now(timezone.utc),
                agent_transcript=[item.to_dict() for item in transcript], execution_metadata=metadata or {},
            ))
            await session.flush()
            await session.refresh(row)
            message = to_message(row)
        return message

    async def finish(self, turn: Turn, status: str, code: str, *, metadata=None):
        async with self.database.session() as session, session.begin():
            await session.execute(update(TurnRecord).where(
                TurnRecord.id == turn.id, TurnRecord.status == "in_progress"
            ).values(status=status, error_code=code, finished_at=datetime.now(timezone.utc),
                     execution_metadata=metadata or {}))
