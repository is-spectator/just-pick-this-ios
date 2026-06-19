from __future__ import annotations

import logging
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.config import get_settings
from app.services.email_templates import login_code_subject, login_code_text


logger = logging.getLogger(__name__)


@dataclass
class SendEmailResult:
    ok: bool
    provider: str
    message_id: str | None = None
    error: str | None = None
    latency_ms: float | None = None


class EmailService:
    def send_login_code(self, email: str, code: str) -> SendEmailResult:
        settings = get_settings()
        started = time.perf_counter()
        if settings.email_provider == "console":
            if settings.app_env in {"production", "staging"}:
                return SendEmailResult(
                    ok=False,
                    provider="console",
                    error="console_email_provider_forbidden",
                    latency_ms=_elapsed_ms(started),
                )
            logger.info("login code for %s: %s", email, code)
            return SendEmailResult(
                ok=True,
                provider="console",
                message_id="console",
                latency_ms=_elapsed_ms(started),
            )

        try:
            message = _build_login_code_message(email, code)
            if settings.smtp_use_ssl:
                with smtplib.SMTP_SSL(
                    settings.smtp_host,
                    int(settings.smtp_port or 465),
                    timeout=settings.smtp_timeout_seconds,
                ) as smtp:
                    _login_and_send(smtp, message)
            else:
                with smtplib.SMTP(
                    settings.smtp_host,
                    int(settings.smtp_port or 587),
                    timeout=settings.smtp_timeout_seconds,
                ) as smtp:
                    if settings.smtp_use_starttls:
                        smtp.starttls()
                    _login_and_send(smtp, message)
            return SendEmailResult(
                ok=True,
                provider="smtp",
                message_id=message["Message-ID"],
                latency_ms=_elapsed_ms(started),
            )
        except Exception as exc:  # pragma: no cover - exact SMTP errors vary.
            return SendEmailResult(
                ok=False,
                provider="smtp",
                error=_safe_error(exc),
                latency_ms=_elapsed_ms(started),
            )


def _build_login_code_message(email: str, code: str) -> EmailMessage:
    settings = get_settings()
    message = EmailMessage()
    from_address = settings.email_from_address or settings.smtp_username or "no-reply@example.com"
    message["From"] = formataddr((settings.email_from_name, from_address))
    message["To"] = email
    message["Subject"] = login_code_subject()
    message.set_content(login_code_text(code))
    return message


def _login_and_send(smtp: smtplib.SMTP, message: EmailMessage) -> None:
    settings = get_settings()
    if settings.smtp_username and settings.smtp_password:
        smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
    smtp.send_message(message)


def _safe_error(exc: Exception) -> str:
    settings = get_settings()
    text = f"{exc.__class__.__name__}: {exc}"
    if settings.smtp_password:
        text = text.replace(settings.smtp_password.get_secret_value(), "***")
    return text


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


email_service = EmailService()
