from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    database_url: str
    app_env: Literal["local", "test", "production"] = "local"
    dev_identity_enabled: bool = False
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
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg://")
        if self.dev_identity_enabled and self.app_env not in {"local", "test"}:
            raise ValueError("Development identity is allowed only in local/test")
        if self.model_timeout_seconds > self.turn_timeout_seconds:
            raise ValueError("Model timeout must not exceed the total turn timeout")
        if self.model_provider == "openai" and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when MODEL selects OpenAI")
        return self
