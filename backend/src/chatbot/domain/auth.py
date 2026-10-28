from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .models import UserProfile


@dataclass(frozen=True)
class Account:
    id: UUID
    username: str
    display_name: str
    password_hash: str


@dataclass(frozen=True)
class AuthSession:
    id: UUID
    user: UserProfile
    username: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionGrant:
    token: str
    session: AuthSession
