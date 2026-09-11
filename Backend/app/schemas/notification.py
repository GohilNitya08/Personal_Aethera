"""Request and response schemas for the compact in-app notification inbox."""

from datetime import datetime

from pydantic import BaseModel, Field


class NotificationResponse(BaseModel):
    notification_id: int
    title: str
    message: str
    is_read: bool
    created_at: datetime | None


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    unread_count: int


class NotificationMarkAllReadResponse(BaseModel):
    marked_count: int = Field(ge=0)
