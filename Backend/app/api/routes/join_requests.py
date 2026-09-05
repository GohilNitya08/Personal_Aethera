from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.routes.users import get_current_auth_user
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.repositories.join_request_repository import JoinRequestRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.join_request import (
    JoinRequestCreate,
    JoinRequestResponse,
    BulkApproveRequest,
)
from app.services.join_request_service import (
    JoinRequestError,
    JoinRequestNotFoundError,
    JoinRequestService,
)
from app.services.workspace_service import (
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspacePermissionError,
    WorkspaceService,
)

router = APIRouter(prefix="/join-requests", tags=["join-requests"])


def get_join_request_service(db: Annotated[Session, Depends(get_db)]) -> JoinRequestService:
    workspace_service = WorkspaceService(WorkspaceRepository(db), UserRepository(db))
    return JoinRequestService(JoinRequestRepository(db), workspace_service)


@router.post("", response_model=JoinRequestResponse, status_code=status.HTTP_201_CREATED)
def submit_join_request(
    payload: JoinRequestCreate,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
):
    try:
        return service.submit_request(current_user.user_id, payload.workspace_id)
    except WorkspaceNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except WorkspaceConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.get("/workspaces/{workspace_id}", response_model=list[JoinRequestResponse])
def list_join_requests(
    workspace_id: int,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
    status: str | None = None,
):
    try:
        return service.list_requests(workspace_id, current_user.user_id, status=status)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    except WorkspacePermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")


@router.post("/{request_id}/approve", response_model=JoinRequestResponse)
def approve_join_request(
    request_id: str,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
):
    try:
        return service.approve_request(request_id, current_user.user_id)
    except JoinRequestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    except WorkspacePermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    except WorkspaceConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.post("/{request_id}/reject", response_model=JoinRequestResponse)
def reject_join_request(
    request_id: str,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
):
    try:
        return service.reject_request(request_id, current_user.user_id)
    except JoinRequestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    except WorkspacePermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    except WorkspaceConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.post("/workspaces/{workspace_id}/bulk-approve")
def bulk_approve_requests(
    workspace_id: int,
    payload: BulkApproveRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[JoinRequestService, Depends(get_join_request_service)],
):
    try:
        return service.bulk_approve_requests(workspace_id, payload.request_ids, current_user.user_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    except WorkspacePermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
