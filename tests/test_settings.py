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
