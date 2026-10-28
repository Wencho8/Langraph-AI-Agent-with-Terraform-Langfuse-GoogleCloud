from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Shared by the API and Alembic; migrations do not need auth/model settings."""

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    database_mode: Literal["direct", "cloud_sql"] = "direct"
    database_url: str | None = Field(default=None, repr=False)
    database_pool_size: int = Field(default=6, ge=2, le=16)
    database_connect_timeout_seconds: float = Field(default=10, gt=0, le=60)
    cloud_sql_instance: str | None = Field(default=None, pattern=r"^[^:\s]+:[^:\s]+:[^:\s]+$")
    database_name: str | None = Field(default=None, min_length=1, max_length=63)
    database_user: str | None = Field(default=None, min_length=1, max_length=63)

    @model_validator(mode="after")
    def validate_database(self):
        if self.database_mode == "direct":
            if not self.database_url or not self.database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("Direct database mode requires DATABASE_URL using postgresql+asyncpg://")
        else:
            if self.database_url:
                raise ValueError("Do not set DATABASE_URL in cloud_sql mode; no direct fallback is allowed")
            if not self.cloud_sql_instance or not self.database_name or not self.database_user:
                raise ValueError("Cloud SQL mode requires CLOUD_SQL_INSTANCE, DATABASE_NAME and DATABASE_USER")
            if self.database_name != self.database_name.strip() or not self.database_name.strip():
                raise ValueError("DATABASE_NAME must not be blank or contain surrounding whitespace")
            if self.database_user != self.database_user.strip() or not self.database_user.endswith(".iam"):
                raise ValueError("DATABASE_USER must be the PostgreSQL IAM service-account username ending in .iam")
        return self

    @property
    def sqlalchemy_url(self) -> str:
        # Cloud connection parameters belong to async_creator, not a password URL.
        return self.database_url if self.database_mode == "direct" else "postgresql+asyncpg://"


class Settings(DatabaseSettings):
    app_env: Literal["local", "test", "production"] = "local"
    auth_mode: Literal["session", "development"] = "session"
    app_origin: str = "http://localhost:5173"
    session_ttl_seconds: int = Field(default=86400, ge=60, le=2592000)
    session_cookie_secure: bool = False
    auth_login_limit: int = Field(default=10, ge=1)
    auth_registration_limit: int = Field(default=5, ge=1)
    max_active_turns: int = Field(default=4, ge=1, le=32)
    rate_limit_requests: int = Field(default=20, ge=1)
    rate_limit_window_seconds: float = Field(default=60, gt=0)
    turn_timeout_seconds: float = Field(default=30, gt=0)
    model_timeout_seconds: float = Field(default=20, gt=0)
    simulated_chunk_delay_seconds: float = Field(default=0.04, ge=0, le=10)
    model: str = "simulated"
    openai_api_key: SecretStr | None = None
    model_max_output_tokens: int = Field(default=2048, ge=1)
    tool_timeout_seconds: float = Field(default=5, gt=0)
    max_model_calls: int = Field(default=4, ge=1)
    max_tool_calls: int = Field(default=8, ge=1)
    graph_recursion_limit: int = Field(default=12, ge=2)

    @field_validator("model")
    @classmethod
    def parse_model(cls, value: str) -> str:
        value = value.strip()
        if value == "simulated":
            return value
        if value == "openai":
            return "openai:gpt-6.1-terra"
        provider, separator, name = value.partition(":")
        if provider.strip() != "openai" or not separator or not name.strip():
            raise ValueError("MODEL must be simulated, openai, or openai:<model-id>")
        return f"{provider.strip()}:{name.strip()}"

    @property
    def model_provider(self) -> str:
        return self.model.partition(":")[0]

    @property
    def model_name(self) -> str:
        return self.model.partition(":")[2] if self.model_provider != "simulated" else "deterministic"

    @model_validator(mode="after")
    def validate_runtime(self):
        if self.auth_mode == "development" and self.app_env not in {"local", "test"}:
            raise ValueError("Development identity is allowed only in local/test")
        origin = urlsplit(self.app_origin)
        if origin.scheme not in {"http", "https"} or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            raise ValueError("APP_ORIGIN must be an exact http(s) origin without a path")
        if self.app_env == "production" and (origin.scheme != "https" or not self.session_cookie_secure):
            raise ValueError("Production requires HTTPS APP_ORIGIN and secure session cookies")
        if self.model_timeout_seconds > self.turn_timeout_seconds:
            raise ValueError("Model timeout must not exceed the total turn timeout")
        if self.model_provider == "openai" and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when MODEL selects OpenAI")
        return self
