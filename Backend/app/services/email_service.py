"""Environment-backed SMTP delivery for security messages."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import settings


class EmailNotConfiguredError(Exception):
    """Raised when SMTP settings are incomplete."""


class EmailDeliveryError(Exception):
    """Raised when SMTP rejects a message."""


class EmailService:
    """Send security-related messages through the configured SMTP server."""

    def send_password_reset_otp(self, recipient: str, otp: str) -> None:
        self._send(
            recipient=recipient,
            subject="AETHERA password reset code",
            body=(
                f"Your AETHERA password reset code is {otp}. It expires in "
                f"{settings.password_reset_otp_expire_minutes} minutes."
            ),
        )

    def send_email_verification_otp(self, recipient: str, otp: str) -> None:
        self._send(
            recipient=recipient,
            subject="AETHERA email verification code",
            body=(
                f"Your AETHERA email verification code is {otp}. It expires in "
                f"{settings.password_reset_otp_expire_minutes} minutes."
            ),
        )

    @staticmethod
    def _send(*, recipient: str, subject: str, body: str) -> None:
        required = (settings.smtp_host, settings.smtp_username, settings.smtp_password, settings.smtp_from)
        if not all(required):
            raise EmailNotConfiguredError("SMTP email delivery is not configured")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise EmailDeliveryError("Email could not be delivered") from error

