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
    """Send reset messages through the configured SMTP server."""

    def send_password_reset_otp(self, recipient: str, otp: str) -> None:
        required = (settings.smtp_host, settings.smtp_username, settings.smtp_password, settings.smtp_from_email)
        if not all(required):
            raise EmailNotConfiguredError("SMTP email delivery is not configured")
        message = EmailMessage()
        message["Subject"] = "AETHERA password reset code"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message.set_content(
            f"Your AETHERA password reset code is {otp}. It expires in "
            f"{settings.password_reset_otp_expire_minutes} minutes."
        )
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise EmailDeliveryError("Password reset email could not be delivered") from error
