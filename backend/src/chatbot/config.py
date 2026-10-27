from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    app_env: Literal["local", "test", "production"] = "local"
    dev_identity_enabled: bool = False
    max_active_turns: int = Field(default=4, ge=1, le=32)
    rate_limit_requests: int = Field(default=20, ge=1)
    rate_limit_window_seconds: float = Field(default=60, gt=0)
    turn_timeout_seconds: float = Field(default=30, gt=0)
    model_timeout_seconds: float = Field(default=20, gt=0)
    simulated_chunk_delay_seconds: float = Field(default=0.04, ge=0, le=10)
    max_model_calls: int = Field(default=1, ge=1)
    graph_recursion_limit: int = Field(default=4, ge=2)

    @model_validator(mode="after")
    def validate_runtime(self):
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")
        if self.dev_identity_enabled and self.app_env not in {"local", "test"}:
            raise ValueError("Development identity is allowed only in local/test")
        if self.model_timeout_seconds > self.turn_timeout_seconds:
            raise ValueError("Model timeout must not exceed the total turn timeout")
        return self
