import asyncio

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func

from chatbot.adapters.outbound.identity.development import DEVELOPMENT_USERS
from chatbot.config import Settings
from .database import Database
from .models import User


async def seed(database: Database):
    async with database.session() as session, session.begin():
        for name, user_id in DEVELOPMENT_USERS.items():
            statement = insert(User).values(id=user_id, display_name=name.title())
            await session.execute(statement.on_conflict_do_update(
                index_elements=[User.id], set_={"display_name": func.coalesce(User.display_name, statement.excluded.display_name)}
            ))


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
