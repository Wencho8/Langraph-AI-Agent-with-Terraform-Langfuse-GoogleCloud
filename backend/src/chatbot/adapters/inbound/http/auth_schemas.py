import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str = Field(max_length=128)
    password: SecretStr

    @field_validator("username")
    @classmethod
    def username_format(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,32}", value):
            raise ValueError("Use 3–32 letters, numbers, dots, underscores or hyphens")
        return value

    @field_validator("password")
    @classmethod
    def password_size(cls, value):
        if not 1 <= len(value.get_secret_value()) <= 128:
            raise ValueError("Password must contain 1–128 characters")
        return value


class Register(Login):
    display_name: str = Field(min_length=1, max_length=120)
    password_confirmation: SecretStr

    @field_validator("display_name", mode="before")
    @classmethod
    def name_format(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def passwords_match(self):
        password = self.password.get_secret_value()
        if len(password) < 15:
            raise ValueError("Use a password of at least 15 characters")
        if password != self.password_confirmation.get_secret_value():
            raise ValueError("Passwords must match")
        return self
