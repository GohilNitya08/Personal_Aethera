"""JWT-protected notification inbox endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.api.routes.users import get_current_auth_user
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.repositories.notification_repository import NotificationRepository
from app.repositories.share_repository import ShareRepository
from app.schemas.notification import NotificationListResponse, NotificationMarkAllReadResponse, NotificationResponse
from app.services.notification_service import NotificationNotFoundError, NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_notification_service(db: Annotated[Session, Depends(get_db)]) -> NotificationService:
    return NotificationService(NotificationRepository(db), ShareRepository(db))


@router.get("", response_model=NotificationListResponse)
def list_notifications(current_user: Annotated[AuthUser, Depends(get_current_auth_user)], service: Annotated[NotificationService, Depends(get_notification_service)], limit: Annotated[int, Query(ge=1, le=100)] = 25) -> NotificationListResponse:
    notifications, unread_count = service.list_notifications(current_user.user_id, limit=limit)
    return NotificationListResponse(notifications=[NotificationResponse(notification_id=item.notification_id, title=item.title, message=item.message, is_read=item.is_read, created_at=item.created_at) for item in notifications], unread_count=unread_count)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(notification_id: Annotated[int, Path(gt=0)], current_user: Annotated[AuthUser, Depends(get_current_auth_user)], service: Annotated[NotificationService, Depends(get_notification_service)]) -> None:
    try:
        service.mark_read(notification_id, current_user.user_id)
    except NotificationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found") from error


@router.post("/read-all", response_model=NotificationMarkAllReadResponse)
def mark_all_read(current_user: Annotated[AuthUser, Depends(get_current_auth_user)], service: Annotated[NotificationService, Depends(get_notification_service)]) -> NotificationMarkAllReadResponse:
    return NotificationMarkAllReadResponse(marked_count=service.mark_all_read(current_user.user_id))
