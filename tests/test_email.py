from __future__ import annotations

from email.message import EmailMessage
from typing import Any, Self, cast

from pydantic import SecretStr, ValidationError

from leetcode_coach.email import send_plan_email
from leetcode_coach.models import DayPlan, Recommendation, WeeklyPlan
from leetcode_coach.render import render_weekly_plan_email
from leetcode_coach.settings import Settings


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "leetcode_username": "ada",
            "llm_api_key": "llm-secret",
            "email_enabled": True,
            "email_to": "ada@example.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_username": "coach@gmail.com",
            "smtp_password": "app-password-secret",
        }
    )


def _plan() -> WeeklyPlan:
    recommendation = Recommendation(
        title="Two Sum", lc_id="1", url="https://leetcode.com/problems/two-sum/"
    )
    return WeeklyPlan.model_validate(
        {
            "learner_summary": "Build a consistent arrays practice habit.",
            "strengths": ["Array fundamentals"],
            "growth_areas": ["Two pointers"],
            "days": [
                DayPlan.model_validate(
                    {
                        "day": f"2026-09-{14 + offset:02d}",
                        "focus": "Arrays",
                        "review": [recommendation],
                        "practice": [recommendation],
                        "rationale": "Reinforce the core pattern.",
                    }
                )
                for offset in range(7)
            ],
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

    send_plan_email(
        plan="# Plan\n", weekly_plan=_plan(), filename="2026-09-14.md", settings=settings
    )


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
    send_plan_email(
        plan="# Weekly Plan\n",
        weekly_plan=_plan(),
        filename="2026-09-14.md",
        settings=_settings(),
    )

    assert len(sent) == 1
    assert sent[0]["To"] == "ada@example.com"
    payload = cast(list[Any], sent[0].get_payload())
    assert payload[0].get_content_type() == "multipart/alternative"
    assert "LeetCode Coach" in payload[0].get_payload()[1].get_content()
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

    send_plan_email(
        plan="# Plan\n", weekly_plan=_plan(), filename="plan.md", settings=settings
    )

    assert received == ["apppasswordsecret"]


def test_html_email_escapes_plan_content() -> None:
    plan = _plan()
    plan.learner_summary = "Practice <consistently> & reflect."
    plan.days[0].practice[0].title = 'Use <two pointers> & "verify"'

    body = render_weekly_plan_email(plan)

    assert "Practice &lt;consistently&gt; &amp; reflect." in body
    assert "Use &lt;two pointers&gt; &amp; &quot;verify&quot;" in body


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
