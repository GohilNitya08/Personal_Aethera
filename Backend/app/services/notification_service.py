"""Notification lifecycle using the existing notifications and file_shares tables."""

from __future__ import annotations

from app.repositories.notification_repository import Notification, NotificationRepository
from app.repositories.share_repository import ShareRepository


class NotificationNotFoundError(Exception):
    pass


class NotificationService:
    EXPIRING_SOON_TITLE = "Shared file expires soon"

    def __init__(self, repository: NotificationRepository, share_repository: ShareRepository) -> None:
        self._repository = repository
        self._share_repository = share_repository

    def notify_private_share(self, *, recipient_id: int, sender_name: str, file_name: str, permission: str, workspace_name: str) -> None:
        self._repository.create(user_id=recipient_id, title=f"{sender_name} shared a file with you", message=f"{file_name}\nPermission: {permission}\nWorkspace: {workspace_name}")

    def list_notifications(self, user_id: int, *, limit: int = 25) -> tuple[list[Notification], int]:
        self._create_expiring_soon_notifications(user_id)
        notifications = self._repository.list_for_user(user_id, limit=limit)
        return notifications, sum(not notification.is_read for notification in notifications)

    def mark_read(self, notification_id: int, user_id: int) -> None:
        if not self._repository.mark_read(notification_id=notification_id, user_id=user_id):
            raise NotificationNotFoundError
        self._repository.commit()

    def mark_all_read(self, user_id: int) -> int:
        marked = self._repository.mark_all_read(user_id)
        self._repository.commit()
        return marked

    def _create_expiring_soon_notifications(self, user_id: int) -> None:
        created = False
        for share in self._share_repository.list_expiring_private_for_recipient(user_id):
            message = f"Share #{share.share_id}: {share.file_name or 'File'} expires within 1 hour."
            if self._repository.exists_for_user_message(user_id=user_id, message=message):
                continue
            self._repository.create(user_id=user_id, title=self.EXPIRING_SOON_TITLE, message=message)
            created = True
        if created:
            self._repository.commit()
