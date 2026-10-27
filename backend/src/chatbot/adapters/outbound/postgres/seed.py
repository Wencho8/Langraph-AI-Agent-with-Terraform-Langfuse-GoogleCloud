import asyncio

from sqlalchemy.dialects.postgresql import insert

from chatbot.adapters.outbound.identity.development import DEVELOPMENT_USERS
from chatbot.config import Settings
from .database import Database
from .models import User


async def seed(database: Database):
    async with database.session() as session, session.begin():
        for user_id in DEVELOPMENT_USERS.values():
            await session.execute(insert(User).values(id=user_id).on_conflict_do_nothing())


async def main():
    settings = Settings()
    if settings.app_env not in {"local", "test"}:
        raise RuntimeError("Development seed is local/test only")
    database = Database(settings.database_url, settings.max_active_turns)
    try:
        await seed(database)
        for name, user_id in DEVELOPMENT_USERS.items():
            print(f"{name}: {user_id}")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
