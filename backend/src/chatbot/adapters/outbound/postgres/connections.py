"""Connection setup shared by API pools, advisory locks, and Alembic."""

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from chatbot.config import DatabaseSettings


class PostgresConnections:
    def __init__(self, settings: DatabaseSettings, connector=None):
        self.settings = settings
        self.connector = connector

    @classmethod
    async def open(cls, settings: DatabaseSettings):
        connector = None
        if settings.database_mode == "cloud_sql":
            # Direct/local mode does not import the SDK or discover Google credentials.
            from google.cloud.sql.connector import IPTypes, create_async_connector

            connector = await create_async_connector(
                ip_type=IPTypes.PUBLIC,
                enable_iam_auth=True,
                refresh_strategy="LAZY",
                timeout=settings.database_connect_timeout_seconds,
            )
        return cls(settings, connector)

    def engine(
        self,
        *,
        pool_size: int | None = None,
        autocommit: bool = False,
        statement_timeout_ms: int | None = 5000,
    ) -> AsyncEngine:
        options = {}
        if pool_size is None:
            options["poolclass"] = pool.NullPool
        else:
            options.update(pool_size=pool_size, max_overflow=0, pool_timeout=2, pool_pre_ping=True)
        if autocommit:
            options["isolation_level"] = "AUTOCOMMIT"

        connect_args = {"timeout": self.settings.database_connect_timeout_seconds}
        if statement_timeout_ms is not None:
            connect_args["server_settings"] = {"statement_timeout": str(statement_timeout_ms)}

        if self.connector is None:
            return create_async_engine(self.settings.sqlalchemy_url, connect_args=connect_args, **options)

        async def connect():
            try:
                return await self.connector.connect_async(
                    self.settings.cloud_sql_instance,
                    "asyncpg",
                    user=self.settings.database_user,
                    db=self.settings.database_name,
                    **connect_args,
                )
            except Exception as exc:
                # Convert connector/auth errors into the existing unavailable path.
                # Cancellation is intentionally not caught.
                raise OSError("Cloud SQL connection could not be established") from exc

        return create_async_engine(self.settings.sqlalchemy_url, async_creator=connect, **options)

    async def close(self):
        if self.connector is not None:
            await self.connector.close_async()
