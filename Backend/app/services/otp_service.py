"""Short-lived, single-use OTP state for password reset and email verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from app.core.config import settings


class OtpCooldownError(Exception):
    """Raised when an OTP is requested before the resend cooldown has elapsed."""


@dataclass
class _OtpRecord:
    user_id: int
    purpose: str
    digest: str
    expires_at: float
    attempts: int = 0


class OtpService:
    """Keep OTPs hashed and bounded in memory for the local demo process."""

    def __init__(self) -> None:
        self._records: dict[str, _OtpRecord] = {}
        self._cooldowns: dict[tuple[int, str], float] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: int, *, purpose: str = "password_reset") -> tuple[str, str]:
        """Issue a new OTP after enforcing the per-user resend cooldown."""
        now = time.monotonic()
        cooldown_key = (user_id, purpose)
        with self._lock:
            self._purge_locked()
            cooldown_until = self._cooldowns.get(cooldown_key, 0.0)
            if now < cooldown_until:
                remaining = int(cooldown_until - now) + 1
                raise OtpCooldownError(
                    f"Please wait {remaining} seconds before requesting a new code"
                )
            # Invalidate any previous OTP for the same user and purpose.
            for challenge, record in list(self._records.items()):
                if record.user_id == user_id and record.purpose == purpose:
                    self._records.pop(challenge, None)
            challenge = secrets.token_urlsafe(32)
            otp = f"{secrets.randbelow(1_000_000):06d}"
            self._records[challenge] = _OtpRecord(
                user_id=user_id,
                purpose=purpose,
                digest=self._digest(otp),
                expires_at=now + settings.password_reset_otp_expire_minutes * 60,
            )
            self._cooldowns[cooldown_key] = now + settings.otp_resend_cooldown_seconds
        return challenge, otp

    def verify(self, challenge: str, otp: str, *, purpose: str = "password_reset") -> int:
        with self._lock:
            self._purge_locked()
            record = self._records.get(challenge)
            if record is None or record.purpose != purpose:
                raise ValueError("Invalid or expired code")
            record.attempts += 1
            if record.attempts > settings.password_reset_otp_max_attempts:
                self._records.pop(challenge, None)
                raise ValueError("Invalid or expired code")
            if not hmac.compare_digest(record.digest, self._digest(otp)):
                raise ValueError("Invalid or expired code")
            self._records.pop(challenge, None)
            return record.user_id

    def consume(self, challenge: str) -> None:
        with self._lock:
            self._records.pop(challenge, None)

    @staticmethod
    def _digest(otp: str) -> str:
        return hashlib.sha256(f"{settings.jwt_secret_key}:{otp}".encode()).hexdigest()

    def _purge_locked(self) -> None:
        now = time.monotonic()
        for challenge, record in list(self._records.items()):
            if record.expires_at <= now:
                self._records.pop(challenge, None)
        for key, until in list(self._cooldowns.items()):
            if until <= now:
                self._cooldowns.pop(key, None)
