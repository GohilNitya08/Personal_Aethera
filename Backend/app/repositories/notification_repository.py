"""SQLAlchemy access for the existing ``notifications`` table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class Notification:
    notification_id: int
    user_id: int
    title: str
    message: str
    is_read: bool
    created_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Notification":
        return cls(int(row["notification_id"]), int(row["user_id"]), str(row["title"]), str(row["message"]), bool(row["is_read"]), row["created_at"])


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, *, user_id: int, title: str, message: str) -> int:
        result = self._db.execute(text("INSERT INTO notifications (user_id, title, message) VALUES (:user_id, :title, :message)"), {"user_id": user_id, "title": title, "message": message})
        return int(result.lastrowid)

    def list_for_user(self, user_id: int, *, limit: int) -> list[Notification]:
        rows = self._db.execute(text("SELECT notification_id, user_id, title, message, is_read, created_at FROM notifications WHERE user_id = :user_id ORDER BY created_at DESC, notification_id DESC LIMIT :limit"), {"user_id": user_id, "limit": limit}).mappings().all()
        return [Notification.from_row(row) for row in rows]

    def exists_for_user_message(self, *, user_id: int, message: str) -> bool:
        return self._db.execute(text("SELECT 1 FROM notifications WHERE user_id = :user_id AND message = :message LIMIT 1"), {"user_id": user_id, "message": message}).first() is not None

    def mark_read(self, *, notification_id: int, user_id: int) -> bool:
        result = self._db.execute(text("UPDATE notifications SET is_read = TRUE WHERE notification_id = :notification_id AND user_id = :user_id"), {"notification_id": notification_id, "user_id": user_id})
        return result.rowcount == 1

    def mark_all_read(self, user_id: int) -> int:
        return int(self._db.execute(text("UPDATE notifications SET is_read = TRUE WHERE user_id = :user_id AND is_read = FALSE"), {"user_id": user_id}).rowcount)

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()
