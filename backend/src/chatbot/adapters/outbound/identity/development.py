from uuid import UUID

from chatbot.application.ports import ConversationRepository
from chatbot.domain.errors import UnknownUser
from chatbot.domain.models import UserProfile

DEVELOPMENT_USERS = {
    "alice": UUID("11111111-1111-4111-8111-111111111111"),
    "bob": UUID("22222222-2222-4222-8222-222222222222"),
}


class DevelopmentIdentity:
    def __init__(self, repository: ConversationRepository, *, enabled: bool, environment: str):
        if not enabled or environment not in {"local", "test"}:
            raise ValueError("Explicitly enabled local/test development identity is required")
        self.repository = repository

    async def resolve(self, credential: str | None) -> UserProfile:
        try:
            user_id = DEVELOPMENT_USERS[credential] if credential in DEVELOPMENT_USERS else UUID(credential or "")
        except (ValueError, TypeError):
            raise UnknownUser() from None
        user = await self.repository.profile(user_id)
        if user is None:
            raise UnknownUser()
        return user
