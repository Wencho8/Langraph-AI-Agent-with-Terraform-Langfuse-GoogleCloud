from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from chatbot.domain.auth import Account, AuthSession
from chatbot.domain.errors import UsernameTaken
from chatbot.domain.models import UserProfile
from .models import AuthSessionRecord, User


class PostgresAuthRepository:
    def __init__(self, database):
        self.database = database

    async def account(self, username):
        async with self.database.session() as db:
            row = await db.scalar(select(User).where(User.username == username))
            return Account(row.id, row.username, row.display_name, row.password_hash) if row else None

    @staticmethod
    async def _session(db, session, verifier, previous):
        if previous:
            await db.execute(update(AuthSessionRecord).where(
                AuthSessionRecord.token_verifier == previous, AuthSessionRecord.revoked_at.is_(None),
            ).values(revoked_at=func.now()))
        db.add(AuthSessionRecord(id=session.id, user_id=session.user.id, token_verifier=verifier,
                                 csrf_token=session.csrf_token, expires_at=session.expires_at))

    async def create(self, account, session, verifier, previous):
        async with self.database.session() as db, db.begin():
            created = await db.scalar(insert(User).values(
                id=account.id, username=account.username, display_name=account.display_name,
                password_hash=account.password_hash,
            ).on_conflict_do_nothing(index_elements=[User.username]).returning(User.id))
            if created is None:
                raise UsernameTaken()
            await self._session(db, session, verifier, previous)

    async def login(self, session, verifier, previous):
        async with self.database.session() as db, db.begin():
            await self._session(db, session, verifier, previous)

    @staticmethod
    def _valid():
        return (AuthSessionRecord.revoked_at.is_(None), AuthSessionRecord.expires_at > func.now())

    async def resolve(self, verifier):
        async with self.database.session() as db:
            row = (await db.execute(select(AuthSessionRecord, User).join(User).where(
                AuthSessionRecord.token_verifier == verifier, *self._valid(),
            ))).first()
            if row is None:
                return None
            session, user = row
            return AuthSession(session.id, UserProfile(user.id, user.display_name), user.username,
                               session.csrf_token, session.expires_at)

    async def active(self, session_id, user_id):
        async with self.database.session() as db:
            return await db.scalar(select(AuthSessionRecord.id).where(
                AuthSessionRecord.id == session_id, AuthSessionRecord.user_id == user_id, *self._valid(),
            )) is not None

    async def revoke(self, verifier):
        async with self.database.session() as db, db.begin():
            await db.execute(update(AuthSessionRecord).where(
                AuthSessionRecord.token_verifier == verifier, AuthSessionRecord.revoked_at.is_(None),
            ).values(revoked_at=func.now()))
