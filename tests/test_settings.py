import pytest

from leetcode_coach.settings import Settings


def test_accepts_own_provider_settings() -> None:
    settings = Settings.model_validate(
        {
            "leetcode_username": "ada",
            "LLM_API_KEY": "secret",
            "LLM_BASE_URL": "https://models.example/v1",
            "LLM_MODEL": "custom-coach",
        }
    )
    assert settings.llm_base_url == "https://models.example/v1"
    assert settings.llm_model == "custom-coach"
    assert settings.llm_api_key.get_secret_value() == "secret"


def test_accepts_s3_storage_settings() -> None:
    settings = Settings.model_validate(
        {
            "leetcode_username": "ada",
            "LLM_API_KEY": "secret",
            "STORAGE_BACKEND": "s3",
            "S3_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
            "S3_BUCKET": "coach",
            "S3_ACCESS_KEY_ID": "access",
            "S3_SECRET_ACCESS_KEY": "secret-storage",
            "S3_PREFIX": "private",
        }
    )
    assert settings.storage_backend == "s3"
    assert settings.s3_prefix == "private"


def test_s3_storage_requires_connection_settings() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="S3_ENDPOINT_URL"):
        Settings.model_validate(
            {
                "leetcode_username": "ada",
                "LLM_API_KEY": "secret",
                "STORAGE_BACKEND": "s3",
            }
        )
