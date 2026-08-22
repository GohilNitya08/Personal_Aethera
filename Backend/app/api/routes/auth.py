"""Authentication HTTP endpoints."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.repositories.auth_repository import AuthRepository, AuthUser
from app.schemas.auth import (
    ForgotPasswordRequest,
    GoogleOAuthExchangeRequest,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    PasswordResetTokenResponse,
    TokenResponse,
    VerifyPasswordResetOtpRequest,
    UserResponse,
)
from app.services.auth_service import (
    AccessToken,
    AuthService,
    AuthTokens,
    DuplicateEmailError,
    DuplicateUsernameError,
    GoogleOAuthError,
    GoogleOAuthNotConfiguredError,
    InactiveAccountError,
    InvalidCredentialsError,
    InvalidTokenError,
    UserNotFoundError,
)
from app.services.email_service import EmailDeliveryError, EmailNotConfiguredError

router = APIRouter(prefix="/auth", tags=["authentication"])

_GOOGLE_STATE_COOKIE = "aethera_google_oauth_state"


class _GoogleOAuthHandoffStore:
    """Keep short-lived OAuth handoffs server-side so JWTs never enter a URL."""

    def __init__(self) -> None:
        self._pending: dict[str, tuple[float, AuthTokens]] = {}
        self._lock = threading.Lock()

    def issue(self, tokens: AuthTokens) -> str:
        code = secrets.token_urlsafe(32)
        expires_at = time.monotonic() + settings.google_oauth_handoff_expire_seconds
        with self._lock:
            self._remove_expired_locked()
            self._pending[code] = (expires_at, tokens)
        return code

    def consume(self, code: str) -> AuthTokens | None:
        with self._lock:
            self._remove_expired_locked()
            item = self._pending.pop(code, None)
        return item[1] if item else None

    def _remove_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [code for code, (expires_at, _) in self._pending.items() if expires_at <= now]
        for code in expired:
            self._pending.pop(code, None)


_google_oauth_handoffs = _GoogleOAuthHandoffStore()


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    """Build the request-scoped authentication service."""
    return AuthService(AuthRepository(db))


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
def register(
    payload: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Create an account after validating uniqueness and hashing its password."""
    try:
        user = service.register(
            username=payload.username,
            full_name=payload.full_name,
            email=str(payload.email),
            password=payload.password,
        )
    except DuplicateEmailError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from error
    except DuplicateUsernameError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This username is already in use",
        ) from error
    return _user_response(user)


@router.post("/login", response_model=TokenResponse, summary="Log in with email and password")
def login(
    payload: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Authenticate the user and return a JWT access and refresh token pair."""
    try:
        tokens = service.login(email=str(payload.email), password=payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error
    return _token_response(tokens)


@router.post("/logout", response_model=MessageResponse, summary="Log out the current client")
def logout() -> MessageResponse:
    """Acknowledge logout until a token blacklist or session store is introduced."""
    AuthService.logout()
    return MessageResponse(message="Logged out successfully")


@router.post("/refresh", response_model=TokenResponse, summary="Refresh an access token")
def refresh_access_token(
    payload: RefreshTokenRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Exchange a valid refresh JWT for a new access JWT."""
    try:
        access_token = service.refresh_access_token(payload.refresh_token)
    except (InvalidTokenError, UserNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error
    return _access_token_response(access_token)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset",
)
def forgot_password(
    payload: ForgotPasswordRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Accept a password-reset request without disclosing account existence."""
    try:
        service.request_password_reset(str(payload.email))
    except EmailNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except EmailDeliveryError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return MessageResponse(
        message="If an account exists, password reset instructions will be sent."
    )


@router.post(
    "/verify-reset-otp",
    response_model=PasswordResetTokenResponse,
    summary="Verify a password reset OTP",
)
def verify_reset_otp(
    payload: VerifyPasswordResetOtpRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> PasswordResetTokenResponse:
    try:
        reset_token = service.verify_password_reset_otp(payload.challenge, payload.otp)
    except (InvalidTokenError, UserNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired password reset code") from error
    return PasswordResetTokenResponse(reset_token=reset_token)


@router.post("/reset-password", response_model=MessageResponse, summary="Reset a password")
def reset_password(
    payload: ResetPasswordRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    """Set a new hashed password from a valid password-reset token."""
    try:
        service.reset_password(
            reset_token=payload.reset_token,
            new_password=payload.new_password,
        )
    except (InvalidTokenError, UserNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired password reset token",
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error
    return MessageResponse(message="Password reset successfully")


@router.get("/verify-email", response_model=MessageResponse, summary="Verify an email address")
def verify_email(token: Annotated[str | None, Query()] = None) -> MessageResponse:
    """Reserve the email-verification URL until email delivery is integrated."""
    del token
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Email verification is not configured yet",
    )


@router.get("/google/login", summary="Start Google sign-in")
def google_login() -> RedirectResponse:
    """Redirect the browser to Google's authorization endpoint with CSRF state."""
    _require_google_oauth_configuration()
    nonce = secrets.token_urlsafe(32)
    state = _create_google_oauth_state(nonce)
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=_GOOGLE_STATE_COOKIE,
        value=nonce,
        max_age=settings.google_oauth_state_expire_minutes * 60,
        httponly=True,
        secure=settings.google_oauth_cookie_secure,
        samesite="lax",
        path=f"{settings.api_v1_prefix}/auth/google",
    )
    return response


@router.get("/google/callback", summary="Complete Google sign-in")
def google_callback(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Validate Google sign-in and redirect with a one-time React handoff code."""
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authentication was cancelled or denied",
        )
    _require_google_oauth_configuration()
    if not _is_valid_google_oauth_state(
        state, request.cookies.get(_GOOGLE_STATE_COOKIE)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired Google OAuth state",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authorization code is missing",
        )
    try:
        identity = service.verify_google_authorization_code(code)
        tokens = service.login_with_google(identity)
    except GoogleOAuthNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        ) from error
    except GoogleOAuthError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        ) from error
    except InactiveAccountError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active",
        ) from error

    handoff_code = _google_oauth_handoffs.issue(tokens)
    response = RedirectResponse(
        url=f"{settings.google_oauth_frontend_redirect_uri}?{urlencode({'oauth_code': handoff_code})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(key=_GOOGLE_STATE_COOKIE, path=f"{settings.api_v1_prefix}/auth/google")
    return response


@router.post(
    "/google/exchange",
    response_model=TokenResponse,
    summary="Exchange a completed Google sign-in handoff",
)
def exchange_google_oauth_handoff(payload: GoogleOAuthExchangeRequest) -> TokenResponse:
    """Return the existing JWT pair for a valid, single-use OAuth handoff code."""
    tokens = _google_oauth_handoffs.consume(payload.code)
    if tokens is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Google OAuth handoff",
        )
    return _token_response(tokens)


def _require_google_oauth_configuration() -> None:
    if not settings.google_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )


def _create_google_oauth_state(nonce: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "nonce": nonce,
            "token_type": "google_oauth_state",
            "iat": now,
            "exp": now + timedelta(minutes=settings.google_oauth_state_expire_minutes),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _is_valid_google_oauth_state(state: str | None, cookie_nonce: str | None) -> bool:
    """Check the short-lived signed state and the HttpOnly browser cookie."""
    if not state or not cookie_nonce:
        return False
    try:
        claims = jwt.decode(
            state,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return False
    nonce = claims.get("nonce")
    return (
        claims.get("token_type") == "google_oauth_state"
        and isinstance(nonce, str)
        and hmac.compare_digest(nonce, cookie_nonce)
    )


def _user_response(user: AuthUser) -> UserResponse:
    """Convert the repository user value into the public API response model."""
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        account_type=user.account_type,
        email_verified=user.email_verified,
        created_at=user.created_at,
    )


def _token_response(tokens: AuthTokens) -> TokenResponse:
    """Convert a login token pair into the API response model."""
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_token_expires_in=tokens.access_token_expires_in,
    )


def _access_token_response(token: AccessToken) -> TokenResponse:
    """Convert a refreshed access token into the API response model."""
    return TokenResponse(
        access_token=token.access_token,
        access_token_expires_in=token.access_token_expires_in,
    )
