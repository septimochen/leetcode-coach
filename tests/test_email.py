from __future__ import annotations

from email.message import EmailMessage
from typing import Any, Self, cast

from pydantic import SecretStr, ValidationError

from leetcode_coach.email import send_plan_email
from leetcode_coach.settings import Settings


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "leetcode_username": "ada",
            "llm_api_key": "llm-secret",
            "email_enabled": True,
            "email_to": "ada@example.com",
            "smtp_username": "coach@gmail.com",
            "smtp_password": "app-password-secret",
        }
    )


def test_email_delivery_is_disabled_by_default(monkeypatch: Any) -> None:
    def fail_if_called(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("SMTP should not be contacted")

    monkeypatch.setattr("leetcode_coach.email.smtplib.SMTP_SSL", fail_if_called)
    settings = Settings.model_validate(
        {
            "leetcode_username": "ada",
            "llm_api_key": "llm-secret",
            "email_enabled": False,
        }
    )

    send_plan_email(plan="# Plan\n", filename="2026-09-14.md", settings=settings)


def test_gmail_email_sends_markdown_attachment(monkeypatch: Any) -> None:
    sent: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, context: Any) -> None:
            assert host == "smtp.gmail.com"
            assert port == 465
            assert context is not None

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            assert username == "coach@gmail.com"
            assert password == "app-password-secret"

        def send_message(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr("leetcode_coach.email.smtplib.SMTP_SSL", FakeSMTP)
    send_plan_email(plan="# Weekly Plan\n", filename="2026-09-14.md", settings=_settings())

    assert len(sent) == 1
    assert sent[0]["To"] == "ada@example.com"
    payload = cast(list[Any], sent[0].get_payload())
    assert payload[1].get_filename() == "2026-09-14.md"
    assert "# Weekly Plan" in payload[1].get_payload(decode=True).decode()


def test_gmail_app_password_spaces_are_removed(monkeypatch: Any) -> None:
    received: list[str] = []

    class FakeSMTP:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            received.append(password)

        def send_message(self, message: EmailMessage) -> None:
            pass

    monkeypatch.setattr("leetcode_coach.email.smtplib.SMTP_SSL", FakeSMTP)
    settings = _settings()
    settings.smtp_password = SecretStr("app pass word secret")

    send_plan_email(plan="# Plan\n", filename="plan.md", settings=settings)

    assert received == ["apppasswordsecret"]


def test_email_settings_require_credentials() -> None:
    try:
        Settings.model_validate(
            {
                "leetcode_username": "ada",
                "llm_api_key": "llm-secret",
                "email_enabled": True,
                "email_to": None,
                "smtp_username": None,
                "smtp_password": None,
            }
        )
    except ValidationError as error:
        assert "EMAIL_TO" in str(error)
    else:
        raise AssertionError("Expected email settings validation to fail")
