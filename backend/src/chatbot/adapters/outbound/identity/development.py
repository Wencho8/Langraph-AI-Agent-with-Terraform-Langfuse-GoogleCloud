from uuid import UUID

from chatbot.application.ports import ConversationRepository
from chatbot.domain.errors import UnknownUser

DEVELOPMENT_USERS = {
    "alice": UUID("11111111-1111-4111-8111-111111111111"),
    "bob": UUID("22222222-2222-4222-8222-222222222222"),
}


class DevelopmentIdentity:
    def __init__(self, repository: ConversationRepository, *, enabled: bool, environment: str):
        if not enabled or environment not in {"local", "test"}:
            raise ValueError("Iteration 01 requires explicitly enabled local/test development identity")
        self.repository = repository

    async def resolve(self, credential: str | None) -> UUID:
        try:
            user_id = DEVELOPMENT_USERS[credential] if credential in DEVELOPMENT_USERS else UUID(credential or "")
        except (ValueError, TypeError):
            raise UnknownUser() from None
        if not await self.repository.user_exists(user_id):
            raise UnknownUser()
        return user_id
