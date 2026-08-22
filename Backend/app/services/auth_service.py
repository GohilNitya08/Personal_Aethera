"""Authentication business logic and JWT handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any

import httpx
from email_validator import EmailNotValidError, validate_email
from google.oauth2 import id_token as google_id_token
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.repositories.auth_repository import AuthRepository, AuthUser

PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthError(Exception):
    """Base class for expected authentication failures."""


class DuplicateEmailError(AuthError):
    """Raised when an email address is already in use."""


class DuplicateUsernameError(AuthError):
    """Raised when a username is already in use."""


class InvalidCredentialsError(AuthError):
    """Raised when login credentials do not authenticate a user."""


class InvalidTokenError(AuthError):
    """Raised when a JWT is malformed, expired, or has the wrong purpose."""


class InactiveAccountError(AuthError):
    """Raised when an operation targets a non-active account."""


class UserNotFoundError(AuthError):
    """Raised when a token references a user that no longer exists."""


class GoogleOAuthError(AuthError):
    """Raised when Google OAuth cannot establish a verified identity."""


class GoogleOAuthNotConfiguredError(GoogleOAuthError):
    """Raised when the Google OAuth client credentials are absent."""


@dataclass(frozen=True, slots=True)
class AuthTokens:
    """A JWT access and refresh token pair."""

    access_token: str
    refresh_token: str
    access_token_expires_in: int


@dataclass(frozen=True, slots=True)
class AccessToken:
    """A newly issued access token."""

    access_token: str
    access_token_expires_in: int


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    """The minimal verified identity claims used to link an AETHERA account."""

    subject: str
    email: str
    full_name: str


@dataclass(frozen=True, slots=True)
class _GoogleCertResponse:
    """Small adapter matching the response contract used by google-auth."""

    status: int
    data: bytes


class _GoogleCertRequest:
    """Fetch Google signing certificates through the project's HTTP client."""

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        **_: object,
    ) -> _GoogleCertResponse:
        response = httpx.request(
            method,
            url,
            content=body,
            headers=headers,
            timeout=10.0,
        )
        return _GoogleCertResponse(status=response.status_code, data=response.content)


class AuthService:
    """Coordinate password authentication, repository access, and token creation."""

    def __init__(self, repository: AuthRepository) -> None:
        self._repository = repository

    def register(
        self,
        *,
        username: str,
        full_name: str,
        email: str,
        password: str,
    ) -> AuthUser:
        """Create a new account with a bcrypt password hash."""
        normalized_email = email.lower()
        if self._repository.get_by_email(normalized_email):
            raise DuplicateEmailError
        if self._repository.get_by_username(username):
            raise DuplicateUsernameError

        try:
            user_id = self._repository.create_user(
                username=username,
                full_name=full_name,
                email=normalized_email,
                password_hash=self._hash_password(password),
            )
            self._repository.commit()
        except IntegrityError:
            self._repository.rollback()
            self._raise_duplicate_after_conflict(email=normalized_email, username=username)
            raise

        user = self._repository.get_by_id(user_id)
        if user is None:
            raise RuntimeError("Created user could not be loaded")
        return user

    def login(self, *, email: str, password: str) -> AuthTokens:
        """Verify credentials, update login metadata, and issue both JWTs."""
        user = self._repository.get_by_email(email.lower())
        if user is None or not user.password_hash:
            raise InvalidCredentialsError
        if not self._verify_password(password, user.password_hash):
            raise InvalidCredentialsError
        self._ensure_active(user)

        self._repository.update_last_login(user.user_id)
        self._repository.commit()
        return self._issue_token_pair(user)

    def login_with_google(self, identity: GoogleIdentity) -> AuthTokens:
        """Find, link, or create an account for a verified Google identity."""
        user = self._repository.get_by_google_id(identity.subject)
        if user is None:
            user = self._repository.get_by_email(identity.email)
            try:
                if user is None:
                    user_id = self._repository.create_google_user(
                        username=self._google_username(identity),
                        full_name=identity.full_name,
                        email=identity.email,
                        google_id=identity.subject,
                    )
                    user = self._repository.get_by_id(user_id)
                    if user is None:
                        raise RuntimeError("Created Google user could not be loaded")
                elif not self._repository.link_google_identity(
                    user_id=user.user_id, google_id=identity.subject
                ):
                    # A concurrent request may have completed the same link.
                    user = self._repository.get_by_google_id(identity.subject)
                    if user is None:
                        raise GoogleOAuthError("Unable to link Google account")
            except IntegrityError as error:
                self._repository.rollback()
                # Resolve the only safe concurrent case: another request linked the
                # same Google subject while this request was in progress.
                user = self._repository.get_by_google_id(identity.subject)
                if user is None:
                    raise GoogleOAuthError("Unable to create Google account") from error

        self._ensure_active(user)
        if not self._repository.mark_google_email_verified(
            user_id=user.user_id, google_id=identity.subject
        ):
            self._repository.rollback()
            raise GoogleOAuthError("Unable to confirm Google account")
        self._repository.update_last_login(user.user_id)
        self._repository.commit()
        return self._issue_token_pair(user)

    @staticmethod
    def verify_google_authorization_code(code: str) -> GoogleIdentity:
        """Exchange an authorization code and verify Google's signed ID token."""
        if not settings.google_oauth_configured:
            raise GoogleOAuthNotConfiguredError
        if not code or len(code) > 4096:
            raise GoogleOAuthError("Invalid authorization code")

        try:
            response = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            token_data: dict[str, Any] = response.json()
            raw_id_token = token_data.get("id_token")
            if not isinstance(raw_id_token, str) or not raw_id_token:
                raise GoogleOAuthError("Google did not return an ID token")
            claims = google_id_token.verify_oauth2_token(
                raw_id_token,
                _GoogleCertRequest(),
                settings.google_client_id,
            )
        except GoogleOAuthError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise GoogleOAuthError("Google authentication failed") from error
        except Exception as error:
            # google-auth raises several implementation-specific token errors.
            raise GoogleOAuthError("Google identity token verification failed") from error

        subject = claims.get("sub")
        email = claims.get("email")
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 255
            or not isinstance(email, str)
            or claims.get("email_verified") is not True
        ):
            raise GoogleOAuthError("Google account does not have a verified email")
        try:
            normalized_email = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError as error:
            raise GoogleOAuthError("Google returned an invalid email address") from error

        name = claims.get("name")
        full_name = name.strip() if isinstance(name, str) else ""
        if not full_name:
            full_name = normalized_email.split("@", 1)[0]
        return GoogleIdentity(
            subject=subject,
            email=normalized_email.lower(),
            full_name=full_name[:100],
        )

    def refresh_access_token(self, refresh_token: str) -> AccessToken:
        """Validate a refresh token and issue a new access token."""
        user = self._get_active_token_user(refresh_token, expected_type="refresh")
        access_token = self._create_token(
            user,
            token_type="access",
            expires_in_minutes=settings.jwt_access_token_expire_minutes,
        )
        return AccessToken(
            access_token=access_token,
            access_token_expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    def request_password_reset(self, email: str) -> None:
        """Accept a reset request without revealing whether the account exists.

        Email delivery is intentionally deferred. A future mail workflow will create a
        password-reset JWT and deliver it only for active accounts.
        """
        user = self._repository.get_by_email(email.lower())
        if user is not None and user.account_status == "ACTIVE":
            # Reserved for future email delivery; keep the response identical either way.
            return

    def reset_password(self, *, reset_token: str, new_password: str) -> None:
        """Validate a future-issued reset token and store a new bcrypt hash."""
        user = self._get_active_token_user(reset_token, expected_type="password_reset")
        if not self._repository.update_password_hash(
            user.user_id, self._hash_password(new_password)
        ):
            self._repository.rollback()
            raise UserNotFoundError
        self._repository.commit()

    @staticmethod
    def logout() -> None:
        """Provide a no-op logout hook until token blacklisting is implemented."""
        return None

    def _issue_token_pair(self, user: AuthUser) -> AuthTokens:
        return AuthTokens(
            access_token=self._create_token(
                user,
                token_type="access",
                expires_in_minutes=settings.jwt_access_token_expire_minutes,
            ),
            refresh_token=self._create_token(
                user,
                token_type="refresh",
                expires_in_minutes=settings.jwt_refresh_token_expire_minutes,
            ),
            access_token_expires_in=settings.jwt_access_token_expire_minutes * 60,
        )

    def _get_active_token_user(self, token: str, *, expected_type: str) -> AuthUser:
        claims = self._decode_token(token, expected_type=expected_type)
        subject = claims.get("sub")
        try:
            user_id = int(subject)
        except (TypeError, ValueError) as error:
            raise InvalidTokenError from error
        if user_id < 1:
            raise InvalidTokenError

        user = self._repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError
        self._ensure_active(user)
        return user

    @staticmethod
    def _hash_password(password: str) -> str:
        return PASSWORD_CONTEXT.hash(password)

    @staticmethod
    def _verify_password(password: str, password_hash: str) -> bool:
        try:
            return PASSWORD_CONTEXT.verify(password, password_hash)
        except ValueError:
            return False

    @staticmethod
    def _ensure_active(user: AuthUser) -> None:
        if user.account_status != "ACTIVE":
            raise InactiveAccountError

    @staticmethod
    def _create_token(
        user: AuthUser,
        *,
        token_type: str,
        expires_in_minutes: int,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.user_id),
            "email": user.email,
            "token_type": token_type,
            "iat": now,
            "exp": now + timedelta(minutes=expires_in_minutes),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    @staticmethod
    def _decode_token(token: str, *, expected_type: str) -> dict[str, object]:
        try:
            claims = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except JWTError as error:
            raise InvalidTokenError from error
        if claims.get("token_type") != expected_type:
            raise InvalidTokenError
        return claims

    def _raise_duplicate_after_conflict(self, *, email: str, username: str) -> None:
        """Translate a race-condition unique-constraint conflict to an API error."""
        if self._repository.get_by_email(email):
            raise DuplicateEmailError
        if self._repository.get_by_username(username):
            raise DuplicateUsernameError

    @staticmethod
    def _google_username(identity: GoogleIdentity) -> str:
        """Create a stable, valid username without exposing a Google subject."""
        local_part = identity.email.split("@", 1)[0]
        base = re.sub(r"[^A-Za-z0-9_]", "_", local_part).strip("_") or "googleuser"
        base = base[:21]
        if len(base) < 3:
            base = (base + "user")[:21]
        suffix = hashlib.sha256(identity.subject.encode("utf-8")).hexdigest()[:8]
        return f"{base}_{suffix}"
