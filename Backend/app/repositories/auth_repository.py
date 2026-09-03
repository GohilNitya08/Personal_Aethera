"""Database access for authentication against the existing ``users`` table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class AuthUser:
    """The user fields required by the authentication service."""

    user_id: int
    username: str
    full_name: str
    email: str
    password_hash: str | None
    account_type: str
    email_verified: bool
    account_status: str
    created_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "AuthUser":
        """Create a typed user value from a SQLAlchemy mapping result."""
        return cls(
            user_id=int(row["user_id"]),
            username=str(row["username"]),
            full_name=str(row["full_name"]),
            email=str(row["email"]),
            password_hash=row["password_hash"],
            account_type=str(row["account_type"]),
            email_verified=bool(row["email_verified"]),
            account_status=str(row["account_status"]),
            created_at=row["created_at"],
        )


class AuthRepository:
    """Encapsulate all authentication-related reads and writes."""

    _USER_COLUMNS = """
        user_id, username, full_name, email, password_hash,
        account_type, email_verified, account_status, created_at
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_email(self, email: str) -> AuthUser | None:
        """Return a user matching an email address, if one exists."""
        return self._get_one_by("email", email)

    def get_by_username(self, username: str) -> AuthUser | None:
        """Return a user matching a username, if one exists."""
        return self._get_one_by("username", username)

    def get_by_google_id(self, google_id: str) -> AuthUser | None:
        """Return a user linked to a verified Google subject, if one exists."""
        return self._get_one_by("google_id", google_id)

    def get_by_id(self, user_id: int) -> AuthUser | None:
        """Return a user by primary key, if one exists."""
        query = text(
            f"SELECT {self._USER_COLUMNS} FROM users "
            "WHERE user_id = :user_id LIMIT 1"
        )
        row = self._db.execute(query, {"user_id": user_id}).mappings().first()
        return AuthUser.from_row(row) if row else None

    def create_user(
        self,
        *,
        username: str,
        full_name: str,
        email: str,
        password_hash: str,
    ) -> int:
        """Insert a password-based user and return its generated primary key."""
        result = self._db.execute(
            text(
                """
                INSERT INTO users (username, full_name, email, password_hash)
                VALUES (:username, :full_name, :email, :password_hash)
                """
            ),
            {
                "username": username,
                "full_name": full_name,
                "email": email,
                "password_hash": password_hash,
            },
        )
        return int(result.lastrowid)

    def create_google_user(
        self,
        *,
        username: str,
        full_name: str,
        email: str,
        google_id: str,
    ) -> int:
        """Create a passwordless account from a verified Google identity."""
        result = self._db.execute(
            text(
                """
                INSERT INTO users
                    (username, full_name, email, password_hash, google_id, email_verified)
                VALUES
                    (:username, :full_name, :email, NULL, :google_id, TRUE)
                """
            ),
            {
                "username": username,
                "full_name": full_name,
                "email": email,
                "google_id": google_id,
            },
        )
        return int(result.lastrowid)

    def link_google_identity(self, *, user_id: int, google_id: str) -> bool:
        """Link an unlinked account to Google and mark its email verified."""
        result = self._db.execute(
            text(
                """
                UPDATE users
                SET google_id = :google_id, email_verified = TRUE
                WHERE user_id = :user_id AND google_id IS NULL
                """
            ),
            {"user_id": user_id, "google_id": google_id},
        )
        return result.rowcount == 1

    def mark_google_email_verified(self, *, user_id: int, google_id: str) -> bool:
        """Record that the linked Google identity supplied a verified email."""
        result = self._db.execute(
            text(
                """
                UPDATE users
                SET email_verified = TRUE
                WHERE user_id = :user_id AND google_id = :google_id
                """
            ),
            {"user_id": user_id, "google_id": google_id},
        )
        return result.rowcount == 1

    def mark_email_verified(self, user_id: int) -> bool:
        """Set email_verified after a successful OTP verification."""
        result = self._db.execute(
            text(
                """
                UPDATE users
                SET email_verified = TRUE
                WHERE user_id = :user_id AND email_verified = FALSE
                """
            ),
            {"user_id": user_id},
        )
        return result.rowcount == 1

    def update_last_login(self, user_id: int) -> None:
        """Record a successful login using the database server timestamp."""
        self._db.execute(
            text("UPDATE users SET last_login = UTC_TIMESTAMP() WHERE user_id = :user_id"),
            {"user_id": user_id},
        )

    def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        """Replace a user's password hash and report whether a row was updated."""
        result = self._db.execute(
            text(
                "UPDATE users SET password_hash = :password_hash "
                "WHERE user_id = :user_id"
            ),
            {"user_id": user_id, "password_hash": password_hash},
        )
        return result.rowcount == 1

    def commit(self) -> None:
        """Commit the current request transaction."""
        self._db.commit()

    def rollback(self) -> None:
        """Roll back the current request transaction."""
        self._db.rollback()

    def _get_one_by(self, column: str, value: str) -> AuthUser | None:
        """Look up one user through a fixed, internal column name."""
        if column not in {"email", "username", "google_id"}:
            raise ValueError("Unsupported user lookup column")

        query = text(
            f"SELECT {self._USER_COLUMNS} FROM users "
            f"WHERE {column} = :value LIMIT 1"
        )
        row = self._db.execute(query, {"value": value}).mappings().first()
        return AuthUser.from_row(row) if row else None
