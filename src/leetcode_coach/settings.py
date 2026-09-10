from __future__ import annotations

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    leetcode_username: str
    # `OPENAI_API_KEY` remains supported for existing OpenAI deployments.
    llm_api_key: SecretStr = Field(
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY")
    )
    # Set this to any provider's OpenAI-compatible API root, usually ending in `/v1`.
    llm_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL")
    )
    # Both values are optional: public profiles usually work without them.
    leetcode_session: SecretStr | None = None
    leetcode_csrf_token: SecretStr | None = None
    llm_model: str = Field(
        default="gpt-5-mini", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL")
    )
    output_dir: str = "data/plans"
