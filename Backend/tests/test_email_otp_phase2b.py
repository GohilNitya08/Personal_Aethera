"""Unit tests for Phase 2B: email verification, OTP password recovery, and cooldown."""

from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.repositories.auth_repository import AuthUser
from app.services.auth_service import (
    AuthError,
    AuthService,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
    UserNotFoundError,
)
from app.services.email_service import EmailNotConfiguredError
from app.services.otp_service import OtpCooldownError, OtpService


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

_BCRYPT_HASH_OF_PASSWORD = "$2b$12$zvn3DkTfO7JickgSgxxhBOX.5zgn.to.l8DFYmJebSsmfQ56I3ezu"
_TEST_PASSWORD = "TestPassword1!"

_BASE_USER = AuthUser(
    user_id=1,
    username="testuser",
    full_name="Test User",
    email="test@example.com",
    password_hash=_BCRYPT_HASH_OF_PASSWORD,
    account_type="PUBLIC",
    email_verified=False,
    account_status="ACTIVE",
    created_at=None,
)


class FakeAuthRepository:
    """In-memory auth repository for unit tests."""

    def __init__(self, user: AuthUser | None = None) -> None:
        self.user = user or _BASE_USER
        self._verified = False
        self._password_updated = False

    def get_by_email(self, email: str) -> AuthUser | None:
        if self.user and self.user.email == email:
            return self.user
        return None

    def get_by_username(self, username: str) -> AuthUser | None:
        if self.user and self.user.username == username:
            return self.user
        return None

    def get_by_id(self, user_id: int) -> AuthUser | None:
        if self.user and self.user.user_id == user_id:
            return self.user
        return None

    def get_by_google_id(self, google_id: str) -> AuthUser | None:
        return None

    def mark_email_verified(self, user_id: int) -> bool:
        if self.user and self.user.user_id == user_id and not self.user.email_verified:
            self.user = replace(self.user, email_verified=True)
            self._verified = True
            return True
        return False

    def mark_google_email_verified(self, *, user_id: int, google_id: str) -> bool:
        return False

    def update_last_login(self, user_id: int) -> None:
        pass

    def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        if self.user and self.user.user_id == user_id:
            self.user = replace(self.user, password_hash=password_hash)
            self._password_updated = True
            return True
        return False

    def create_user(self, **kwargs: object) -> int:
        return 1

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class FakeEmailService:
    """Capture OTP emails without actually sending them."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    def send_password_reset_otp(self, recipient: str, otp: str) -> None:
        if self.fail:
            raise EmailNotConfiguredError("SMTP not configured")
        self.sent.append(("password_reset", recipient, otp))

    def send_email_verification_otp(self, recipient: str, otp: str) -> None:
        if self.fail:
            raise EmailNotConfiguredError("SMTP not configured")
        self.sent.append(("email_verification", recipient, otp))


def _make_service(
    user: AuthUser | None = None,
    email_fail: bool = False,
    otp_service: OtpService | None = None,
) -> tuple[AuthService, FakeAuthRepository, FakeEmailService, OtpService]:
    repo = FakeAuthRepository(user)
    email = FakeEmailService(fail=email_fail)
    otp = otp_service or OtpService()
    service = AuthService(repo, email_service=email, otp_service=otp)
    return service, repo, email, otp


# ---------------------------------------------------------------------------
# OTP Service Unit Tests
# ---------------------------------------------------------------------------

class TestOtpService:
    """Direct tests on the OTP service."""

    def test_issue_and_verify_success(self) -> None:
        otp_svc = OtpService()
        challenge, otp = otp_svc.issue(1, purpose="password_reset")
        assert len(challenge) >= 32
        assert len(otp) == 6 and otp.isdigit()
        user_id = otp_svc.verify(challenge, otp, purpose="password_reset")
        assert user_id == 1

    def test_otp_is_single_use(self) -> None:
        otp_svc = OtpService()
        challenge, otp = otp_svc.issue(1)
        otp_svc.verify(challenge, otp)
        with pytest.raises(ValueError, match="Invalid or expired"):
            otp_svc.verify(challenge, otp)

    def test_wrong_otp_increments_attempts(self) -> None:
        otp_svc = OtpService()
        challenge, otp = otp_svc.issue(1)
        with pytest.raises(ValueError):
            otp_svc.verify(challenge, "000000")
        # Original OTP still works if attempts not exhausted
        user_id = otp_svc.verify(challenge, otp)
        assert user_id == 1

    def test_max_attempts_exhausted(self) -> None:
        otp_svc = OtpService()
        challenge, otp = otp_svc.issue(1)
        for _ in range(5):
            with pytest.raises(ValueError):
                otp_svc.verify(challenge, "000000")
        # After max attempts, even correct OTP fails
        with pytest.raises(ValueError, match="Invalid or expired"):
            otp_svc.verify(challenge, otp)

    def test_wrong_purpose_rejected(self) -> None:
        otp_svc = OtpService()
        challenge, otp = otp_svc.issue(1, purpose="password_reset")
        with pytest.raises(ValueError, match="Invalid or expired"):
            otp_svc.verify(challenge, otp, purpose="email_verification")

    def test_expired_otp_rejected(self) -> None:
        otp_svc = OtpService()
        challenge, otp = otp_svc.issue(1)
        # Manually expire the record
        with otp_svc._lock:
            for record in otp_svc._records.values():
                record.expires_at = time.monotonic() - 1
        with pytest.raises(ValueError, match="Invalid or expired"):
            otp_svc.verify(challenge, otp)

    def test_resend_cooldown_enforced(self) -> None:
        otp_svc = OtpService()
        otp_svc.issue(1, purpose="password_reset")
        with pytest.raises(OtpCooldownError, match="wait"):
            otp_svc.issue(1, purpose="password_reset")

    def test_cooldown_is_per_purpose(self) -> None:
        otp_svc = OtpService()
        otp_svc.issue(1, purpose="password_reset")
        # Different purpose should not be blocked
        challenge, otp = otp_svc.issue(1, purpose="email_verification")
        assert len(challenge) >= 32

    def test_cooldown_expires(self) -> None:
        otp_svc = OtpService()
        otp_svc.issue(1, purpose="password_reset")
        # Manually expire the cooldown
        with otp_svc._lock:
            for key in list(otp_svc._cooldowns):
                otp_svc._cooldowns[key] = time.monotonic() - 1
        # Should succeed now
        challenge, otp = otp_svc.issue(1, purpose="password_reset")
        assert len(challenge) >= 32

    def test_reissue_invalidates_previous_otp(self) -> None:
        otp_svc = OtpService()
        challenge1, otp1 = otp_svc.issue(1, purpose="password_reset")
        # Expire cooldown to allow reissue
        with otp_svc._lock:
            for key in list(otp_svc._cooldowns):
                otp_svc._cooldowns[key] = time.monotonic() - 1
        challenge2, otp2 = otp_svc.issue(1, purpose="password_reset")
        # Old OTP should be invalidated
        with pytest.raises(ValueError):
            otp_svc.verify(challenge1, otp1)
        # New OTP should work
        assert otp_svc.verify(challenge2, otp2) == 1

    def test_consume_removes_record(self) -> None:
        otp_svc = OtpService()
        challenge, otp = otp_svc.issue(1)
        otp_svc.consume(challenge)
        with pytest.raises(ValueError):
            otp_svc.verify(challenge, otp)


# ---------------------------------------------------------------------------
# Password Reset Flow Tests
# ---------------------------------------------------------------------------

class TestPasswordResetFlow:
    """Tests for the forgot-password → OTP → reset flow."""

    def test_request_password_reset_sends_otp(self) -> None:
        service, repo, email, _ = _make_service(
            user=replace(_BASE_USER, email_verified=True)
        )
        challenge = service.request_password_reset("test@example.com")
        assert isinstance(challenge, str) and len(challenge) > 10
        assert len(email.sent) == 1
        assert email.sent[0][0] == "password_reset"
        assert email.sent[0][1] == "test@example.com"

    def test_request_password_reset_nonexistent_email_silent(self) -> None:
        service, _, email, _ = _make_service()
        challenge = service.request_password_reset("nobody@example.com")
        assert isinstance(challenge, str) and len(challenge) > 10
        assert len(email.sent) == 0

    def test_forgot_password_cooldown(self) -> None:
        service, repo, email, _ = _make_service(
            user=replace(_BASE_USER, email_verified=True)
        )
        service.request_password_reset("test@example.com")
        with pytest.raises(OtpCooldownError):
            service.request_password_reset("test@example.com")

    def test_verify_otp_returns_reset_token(self) -> None:
        service, repo, email, otp_svc = _make_service(
            user=replace(_BASE_USER, email_verified=True)
        )
        challenge = service.request_password_reset("test@example.com")
        otp_code = email.sent[0][2]
        reset_token = service.verify_password_reset_otp(challenge, otp_code)
        assert isinstance(reset_token, str) and len(reset_token) > 0

    def test_verify_otp_invalid_code(self) -> None:
        service, _, email, otp_svc = _make_service(
            user=replace(_BASE_USER, email_verified=True)
        )
        challenge = service.request_password_reset("test@example.com")
        with pytest.raises(InvalidTokenError):
            service.verify_password_reset_otp(challenge, "000000")

    def test_verify_otp_expired(self) -> None:
        service, _, email, otp_svc = _make_service(
            user=replace(_BASE_USER, email_verified=True)
        )
        challenge = service.request_password_reset("test@example.com")
        with otp_svc._lock:
            otp_svc._records[challenge].expires_at = time.monotonic() - 1
        with pytest.raises(InvalidTokenError):
            service.verify_password_reset_otp(challenge, email.sent[0][2])

    def test_reset_password_success(self) -> None:
        service, repo, email, otp_svc = _make_service(
            user=replace(_BASE_USER, email_verified=True)
        )
        challenge = service.request_password_reset("test@example.com")
        otp_code = email.sent[0][2]
        reset_token = service.verify_password_reset_otp(challenge, otp_code)
        service.reset_password(reset_token=reset_token, new_password="NewSecure123!")
        assert repo._password_updated is True

    def test_reset_password_invalid_token(self) -> None:
        service, _, _, _ = _make_service()
        with pytest.raises(InvalidTokenError):
            service.reset_password(reset_token="bogus.token.here", new_password="NewSecure123!")

    def test_smtp_failure_consumes_otp(self) -> None:
        service, repo, email, otp_svc = _make_service(
            user=replace(_BASE_USER, email_verified=True),
            email_fail=True,
        )
        with pytest.raises(EmailNotConfiguredError):
            service.request_password_reset("test@example.com")
        # OTP should have been consumed on SMTP failure
        with otp_svc._lock:
            assert len(otp_svc._records) == 0


# ---------------------------------------------------------------------------
# Email Verification Flow Tests
# ---------------------------------------------------------------------------

class TestEmailVerificationFlow:
    """Tests for the request-email-verification → verify-email flow."""

    def test_request_verification_sends_otp(self) -> None:
        service, _, email, _ = _make_service()
        challenge = service.request_email_verification(1)
        assert len(challenge) >= 32
        assert len(email.sent) == 1
        assert email.sent[0][0] == "email_verification"
        assert email.sent[0][1] == "test@example.com"

    def test_verify_email_success(self) -> None:
        service, repo, email, _ = _make_service()
        challenge = service.request_email_verification(1)
        otp_code = email.sent[0][2]
        service.verify_email(challenge, otp_code)
        assert repo.user.email_verified is True
        assert repo._verified is True

    def test_verify_email_invalid_otp(self) -> None:
        service, repo, _, _ = _make_service()
        challenge = service.request_email_verification(1)
        with pytest.raises(InvalidTokenError):
            service.verify_email(challenge, "000000")
        assert repo.user.email_verified is False

    def test_verify_email_expired(self) -> None:
        service, repo, email, otp_svc = _make_service()
        challenge = service.request_email_verification(1)
        otp_code = email.sent[0][2]
        with otp_svc._lock:
            otp_svc._records[challenge].expires_at = time.monotonic() - 1
        with pytest.raises(InvalidTokenError):
            service.verify_email(challenge, otp_code)

    def test_verify_email_single_use(self) -> None:
        service, repo, email, _ = _make_service()
        challenge = service.request_email_verification(1)
        otp_code = email.sent[0][2]
        service.verify_email(challenge, otp_code)
        # Recreate with unverified user for second attempt since the user is
        # now verified and request_email_verification would raise AuthError
        with pytest.raises(InvalidTokenError):
            service.verify_email(challenge, otp_code)

    def test_already_verified_rejected(self) -> None:
        service, _, _, _ = _make_service(
            user=replace(_BASE_USER, email_verified=True)
        )
        with pytest.raises(AuthError, match="already verified"):
            service.request_email_verification(1)

    def test_verification_cooldown(self) -> None:
        service, _, _, _ = _make_service()
        service.request_email_verification(1)
        with pytest.raises(OtpCooldownError):
            service.request_email_verification(1)

    def test_smtp_failure_consumes_otp(self) -> None:
        service, _, _, otp_svc = _make_service(email_fail=True)
        with pytest.raises(EmailNotConfiguredError):
            service.request_email_verification(1)
        with otp_svc._lock:
            assert len(otp_svc._records) == 0

    def test_nonexistent_user_rejected(self) -> None:
        service, _, _, _ = _make_service()
        with pytest.raises(UserNotFoundError):
            service.request_email_verification(999)

    def test_google_oauth_user_already_verified(self) -> None:
        """Google OAuth users have email_verified=True and should not need OTP."""
        google_user = replace(_BASE_USER, email_verified=True, password_hash=None)
        service, _, _, _ = _make_service(user=google_user)
        with pytest.raises(AuthError, match="already verified"):
            service.request_email_verification(1)


# ---------------------------------------------------------------------------
# SMTP Configuration Tests
# ---------------------------------------------------------------------------

class TestSmtpConfiguration:
    """Verify the SMTP configuration field naming is correct."""

    def test_config_field_name_matches_env_var(self) -> None:
        """The Settings field 'smtp_from' should match env var SMTP_FROM."""
        from app.core.config import Settings
        field_names = set(Settings.model_fields.keys())
        assert "smtp_from" in field_names
        # The old mismatched name should not exist
        assert "smtp_from_email" not in field_names

    def test_otp_resend_cooldown_field_exists(self) -> None:
        from app.core.config import Settings
        assert "otp_resend_cooldown_seconds" in Settings.model_fields


# ---------------------------------------------------------------------------
# Login with unverified email test
# ---------------------------------------------------------------------------

class TestLoginEmailVerification:
    """Verify login rejects unverified email users."""

    def test_login_unverified_email_raises(self) -> None:
        service, _, _, _ = _make_service()
        with pytest.raises(EmailNotVerifiedError):
            service.login(email="test@example.com", password=_TEST_PASSWORD)
