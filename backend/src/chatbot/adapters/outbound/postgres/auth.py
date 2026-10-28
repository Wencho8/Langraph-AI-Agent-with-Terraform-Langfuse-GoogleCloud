from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from chatbot.domain.auth import Account, AuthSession
from chatbot.domain.errors import AccountBlocked, Forbidden, UnknownUser, UsernameTaken
from chatbot.domain.models import UserProfile
from .models import AuthSessionRecord, User


class PostgresAuthRepository:
    def __init__(self, database):
        self.database = database

    async def account(self, username):
        async with self.database.session() as db:
            row = await db.scalar(select(User).where(User.username == username))
            return Account(row.id, row.username, row.display_name, row.password_hash, row.is_admin, row.blocked) if row else None

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
            if session is not None:
                await self._session(db, session, verifier, previous)

    async def login(self, session, verifier, previous):
        async with self.database.session() as db, db.begin():
            user = await db.scalar(select(User).where(User.id == session.user.id).with_for_update())
            if user is None or user.blocked:
                raise AccountBlocked()
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
            if user.blocked:
                raise AccountBlocked()
            return AuthSession(session.id, UserProfile(user.id, user.display_name), user.username,
                               session.csrf_token, session.expires_at, user.is_admin)

    async def active(self, session_id, user_id):
        async with self.database.session() as db:
            return await db.scalar(select(AuthSessionRecord.id).join(User).where(
                User.blocked.is_(False),
                AuthSessionRecord.id == session_id, AuthSessionRecord.user_id == user_id, *self._valid(),
            )) is not None

    async def revoke(self, verifier):
        async with self.database.session() as db, db.begin():
            await db.execute(update(AuthSessionRecord).where(
                AuthSessionRecord.token_verifier == verifier, AuthSessionRecord.revoked_at.is_(None),
            ).values(revoked_at=func.now()))


    @staticmethod
    async def _admin(db, actor_id):
        actor = await db.scalar(select(User).where(User.id == actor_id).with_for_update())
        if actor is None or actor.blocked or not actor.is_admin:
            raise Forbidden()

    async def list_accounts(self, actor_id, offset=0, limit=100):
        async with self.database.session() as db, db.begin():
            await self._admin(db, actor_id)
            users = (await db.scalars(select(User).where(User.username.is_not(None))
                     .order_by(User.created_at, User.id).offset(offset).limit(limit))).all()
            return [{"id": str(u.id), "username": u.username, "display_name": u.display_name,
                     "is_admin": u.is_admin, "blocked": u.blocked} for u in users]

    async def set_blocked(self, actor_id, user_id, blocked):
        async with self.database.session() as db, db.begin():
            await self._admin(db, actor_id)
            if actor_id == user_id:
                raise Forbidden()
            target = await db.scalar(select(User).where(User.id == user_id).with_for_update())
            if target is None:
                raise UnknownUser()
            target.blocked = blocked
            if blocked:
                await db.execute(update(AuthSessionRecord).where(
                    AuthSessionRecord.user_id == user_id, AuthSessionRecord.revoked_at.is_(None)
                ).values(revoked_at=func.now()))
