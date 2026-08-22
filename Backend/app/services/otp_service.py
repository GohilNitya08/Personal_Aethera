"""Short-lived, single-use password-reset OTP state."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class _OtpRecord:
    user_id: int
    digest: str
    expires_at: float
    attempts: int = 0


class OtpService:
    """Keep reset OTPs hashed and bounded in memory for the local demo process."""

    def __init__(self) -> None:
        self._records: dict[str, _OtpRecord] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: int) -> tuple[str, str]:
        challenge = secrets.token_urlsafe(32)
        otp = f"{secrets.randbelow(1_000_000):06d}"
        record = _OtpRecord(
            user_id=user_id,
            digest=self._digest(otp),
            expires_at=time.monotonic() + settings.password_reset_otp_expire_minutes * 60,
        )
        with self._lock:
            self._purge_locked()
            self._records[challenge] = record
        return challenge, otp

    def verify(self, challenge: str, otp: str) -> int:
        with self._lock:
            self._purge_locked()
            record = self._records.get(challenge)
            if record is None:
                raise ValueError("Invalid or expired password reset code")
            record.attempts += 1
            if record.attempts > settings.password_reset_otp_max_attempts:
                self._records.pop(challenge, None)
                raise ValueError("Invalid or expired password reset code")
            if not hmac.compare_digest(record.digest, self._digest(otp)):
                raise ValueError("Invalid or expired password reset code")
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
