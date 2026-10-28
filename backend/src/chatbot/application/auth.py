import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from chatbot.application.ports import AuthLimiter, AuthRepository, PasswordHasher
from chatbot.domain.auth import Account, AuthSession, SessionGrant
from chatbot.domain.errors import AccountBlocked, InvalidCredentials, Unauthorized
from chatbot.domain.models import UserProfile

logger = logging.getLogger("chatbot")


def token_verifier(token: str | None) -> str | None:
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class AuthService:
    def __init__(self, repository: AuthRepository, passwords: PasswordHasher, limiter: AuthLimiter,
                 *, ttl: int, login_limit: int, registration_limit: int):
        self.repository, self.passwords, self.limiter = repository, passwords, limiter
        self.ttl, self.login_limit, self.registration_limit = ttl, login_limit, registration_limit
        self.dummy_hash = None

    async def initialize(self):
        self.dummy_hash = await self.passwords.hash(secrets.token_urlsafe(32))

    def grant(self, user: UserProfile, username: str) -> SessionGrant:
        session = AuthSession(uuid4(), user, username, secrets.token_urlsafe(32),
                              datetime.now(timezone.utc) + timedelta(seconds=self.ttl))
        return SessionGrant(secrets.token_urlsafe(32), session)

    async def register(self, name: str, username: str, password: str, client: str, previous: str | None):
        self.limiter.check([("register:ip:" + client, self.registration_limit)])
        account = Account(uuid4(), username, name, await self.passwords.hash(password))
        await self.repository.create(account, None, None, None)
        logger.info(json.dumps({"event": "auth_registered", "user_id": str(account.id)}))
        return None

    async def login(self, username: str, password: str, client: str, previous: str | None):
        self.limiter.check([("login:ip:" + client, self.login_limit), ("login:user:" + username, self.login_limit)])
        account = await self.repository.account(username)
        valid = await self.passwords.verify(account.password_hash if account else self.dummy_hash, password)
        if account is None or not valid:
            logger.info(json.dumps({"event": "auth_login_failed", "code": "invalid_credentials"}))
            raise InvalidCredentials()
        if account.blocked:
            raise AccountBlocked()
        grant = self.grant(UserProfile(account.id, account.display_name), username)
        await self.repository.login(grant.session, token_verifier(grant.token), token_verifier(previous))
        # Resolve fresh role/access state after the transactional login check.
        grant = SessionGrant(grant.token, await self.resolve(grant.token))
        logger.info(json.dumps({"event": "auth_login_succeeded", "user_id": str(account.id)}))
        return grant

    async def optional(self, token: str | None) -> AuthSession | None:
        verifier = token_verifier(token)
        return await self.repository.resolve(verifier) if verifier else None

    async def resolve(self, token: str | None) -> AuthSession:
        session = await self.optional(token)
        if session is None:
            raise Unauthorized()
        return session

    async def check(self, session: AuthSession):
        if not await self.repository.active(session.id, session.user.id):
            raise Unauthorized()

    async def logout(self, token: str | None):
        verifier = token_verifier(token)
        if verifier:
            await self.repository.revoke(verifier)
        logger.info(json.dumps({"event": "auth_logout"}))


    async def list_accounts(self, token, offset=0):
        session = await self.resolve(token)
        return await self.repository.list_accounts(session.user.id, offset, 100)

    async def set_blocked(self, token, user_id, blocked):
        session = await self.resolve(token)
        await self.repository.set_blocked(session.user.id, user_id, blocked)
