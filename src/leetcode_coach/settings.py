from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
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
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_prefix: str = ""
    email_enabled: bool = False
    email_to: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_security: Literal["ssl", "starttls"] = "ssl"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    # Logging: DEBUG, INFO, WARNING, ERROR, or CRITICAL. Overridden by --log-level.
    log_level: str = Field(
        default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "LLM_LOG_LEVEL")
    )
    # Optional log file, appended in addition to stderr. Relative to the working directory.
    log_file: str | None = None

    @model_validator(mode="after")
    def validate_storage(self) -> Settings:
        """Require the R2/S3 connection settings only when S3 storage is selected."""
        if self.storage_backend == "s3":
            missing = [
                name
                for name, value in {
                    "S3_ENDPOINT_URL": self.s3_endpoint_url,
                    "S3_BUCKET": self.s3_bucket,
                    "S3_ACCESS_KEY_ID": self.s3_access_key_id,
                    "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    "S3 storage requires: " + ", ".join(missing)
                )
        if self.email_enabled:
            missing = [
                name
                for name, value in {
                    "EMAIL_TO": self.email_to,
                    "SMTP_USERNAME": self.smtp_username,
                    "SMTP_PASSWORD": self.smtp_password,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(
                    "Email delivery requires: " + ", ".join(missing)
                )
        return self
