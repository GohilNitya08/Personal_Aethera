from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.notification_repository import Notification
from app.repositories.share_repository import FileShare
from app.services.notification_service import NotificationNotFoundError, NotificationService
from app.services.share_service import ShareNotFoundError, ShareService


class FakeNotifications:
    def __init__(self) -> None:
        self.items: list[Notification] = []

    def create(self, *, user_id: int, title: str, message: str) -> int:
        notification_id = len(self.items) + 1
        self.items.append(Notification(notification_id, user_id, title, message, False, None))
        return notification_id

    def list_for_user(self, user_id: int, *, limit: int):
        return [item for item in self.items if item.user_id == user_id][:limit]

    def exists_for_user_message(self, *, user_id: int, message: str) -> bool:
        return any(item.user_id == user_id and item.message == message for item in self.items)

    def mark_read(self, *, notification_id: int, user_id: int) -> bool:
        for index, item in enumerate(self.items):
            if item.notification_id == notification_id and item.user_id == user_id:
                self.items[index] = Notification(item.notification_id, item.user_id, item.title, item.message, True, item.created_at)
                return True
        return False

    def mark_all_read(self, user_id: int) -> int:
        count = 0
        for item in list(self.items):
            if item.user_id == user_id and not item.is_read:
                self.mark_read(notification_id=item.notification_id, user_id=user_id)
                count += 1
        return count

    def commit(self) -> None:
        return None


class FakeShares:
    def __init__(self, expiring: dict[int, list[FileShare]] | None = None, by_id: dict[int, FileShare] | None = None) -> None:
        self.expiring = expiring or {}
        self.by_id = by_id or {}

    def list_expiring_private_for_recipient(self, user_id: int):
        return self.expiring.get(user_id, [])

    def get_by_id(self, share_id: int):
        return self.by_id.get(share_id)


def share(share_id: int, *, recipient: int = 2, expires_at: datetime | None = None) -> FileShare:
    return FileShare(share_id, 10, 1, recipient, "PRIVATE", "VIEW", None, None, expires_at, None, "Project_Report.pdf", "UDP Project")


def test_private_share_notification_is_scoped_to_recipient_and_read_state():
    notifications = FakeNotifications()
    service = NotificationService(notifications, FakeShares())
    service.notify_private_share(recipient_id=2, sender_name="Nitya", file_name="Project_Report.pdf", permission="VIEW", workspace_name="UDP Project")

    inbox, unread = service.list_notifications(2)
    assert unread == 1 and inbox[0].title == "Nitya shared a file with you"
    assert "Workspace: UDP Project" in inbox[0].message
    assert service.list_notifications(3)[0] == []
    service.mark_read(inbox[0].notification_id, 2)
    assert service.list_notifications(2)[1] == 0
    with pytest.raises(NotificationNotFoundError):
        service.mark_read(inbox[0].notification_id, 3)


def test_expiring_soon_warning_is_generated_once_for_the_recipient():
    notifications = FakeNotifications()
    expiring_share = share(7, expires_at=datetime.now(timezone.utc) + timedelta(minutes=30))
    service = NotificationService(notifications, FakeShares({2: [expiring_share]}))

    first, unread = service.list_notifications(2)
    second, _ = service.list_notifications(2)
    assert unread == 1 and len(first) == len(second) == 1
    assert first[0].title == "Shared file expires soon"
    assert "Share #7" in first[0].message
    assert service.list_notifications(3)[0] == []


def test_direct_share_expiration_boundary_is_enforced():
    now = datetime.now(timezone.utc)
    active = share(1, expires_at=now + timedelta(seconds=1))
    expired = share(2, expires_at=now)
    service = ShareService(FakeShares(by_id={1: active, 2: expired}), None, None, None, None)

    assert service.get_active_share_for_recipient(1, 2).share_id == 1
    with pytest.raises(ShareNotFoundError, match="expired"):
        service.get_active_share_for_recipient(2, 2)
