"""Send generated plans through an authenticated SMTP account."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from .log import get_logger
from .models import WeeklyPlan
from .render import render_weekly_plan_email
from .settings import Settings

logger = get_logger(__name__)


def send_plan_email(
    *, plan: str, weekly_plan: WeeklyPlan, filename: str, settings: Settings
) -> None:
    """Email a rich weekly-plan summary and its Markdown attachment when enabled."""
    if not settings.email_enabled:
        return
    assert settings.email_to is not None
    assert settings.smtp_username is not None
    assert settings.smtp_password is not None

    recipients = [
        address.strip()
        for address in settings.email_to.split(",")
        if address.strip()
    ]
    message = EmailMessage()
    message["From"] = settings.smtp_username
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"LeetCode weekly plan — {filename.removesuffix('.md')}"
    message.set_content(
        "Your email client does not support HTML. Your LeetCode weekly plan is "
        "attached as an Obsidian-compatible Markdown file."
    )
    message.add_alternative(render_weekly_plan_email(weekly_plan), subtype="html")
    message.add_attachment(
        plan.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=filename,
    )

    # Gmail displays App Passwords in groups separated by spaces.
    password = "".join(settings.smtp_password.get_secret_value().split())
    context = ssl.create_default_context()
    try:
        if settings.smtp_security == "ssl":
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                context=context,
            ) as smtp:
                smtp.login(settings.smtp_username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
                smtp.starttls(context=context)
                smtp.login(settings.smtp_username, password)
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as error:
        logger.error(
            "SMTP authentication failed for %s; verify SMTP_USERNAME and the Gmail "
            "App Password.",
            settings.smtp_username,
        )
        raise RuntimeError("Gmail SMTP authentication failed.") from error
    logger.info("Plan email sent to %s (%s)", settings.email_to, filename)
