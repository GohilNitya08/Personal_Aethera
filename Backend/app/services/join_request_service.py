from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.repositories.join_request_repository import JoinRequest, JoinRequestRepository
from app.services.workspace_service import WorkspaceService, WorkspaceNotFoundError, WorkspaceConflictError, WorkspacePermissionError


class JoinRequestError(Exception):
    pass

class JoinRequestNotFoundError(JoinRequestError):
    pass


class JoinRequestService:
    def __init__(
        self,
        repository: JoinRequestRepository,
        workspace_service: WorkspaceService,
    ) -> None:
        self._repository = repository
        self._workspace_service = workspace_service

    def submit_request(self, user_id: int, workspace_id: int) -> JoinRequest:
        workspace = self._workspace_service._repository.get_by_id(workspace_id)
        if not workspace:
            raise WorkspaceNotFoundError("Workspace not found")
            
        if workspace.visibility == "PUBLIC":
            raise WorkspaceConflictError("Public workspaces are available without joining")

        existing_membership = self._workspace_service._repository.get_membership(workspace_id, user_id)
        if existing_membership is not None or workspace.user_id == user_id:
            raise WorkspaceConflictError("User is already a member")

        existing_request = self._repository.get_by_user_and_workspace(user_id, workspace_id)
        if existing_request is not None:
            if existing_request.status == "PENDING":
                raise WorkspaceConflictError("Join request is already pending")
            if existing_request.status == "REJECTED":
                try:
                    if not self._repository.reopen_rejected(existing_request.request_id):
                        raise WorkspaceConflictError("Join request could not be reopened")
                    self._repository.commit()
                except Exception:
                    self._repository.rollback()
                    raise
                reopened = self._repository.get_by_id(existing_request.request_id)
                if reopened is None:
                    raise RuntimeError("Reopened join request could not be loaded")
                return reopened
            raise WorkspaceConflictError("User is already a member")
            
        request_id = str(uuid.uuid4())
        
        try:
            self._repository.create(request_id, workspace_id, user_id)
            self._repository.commit()
        except IntegrityError as error:
            self._repository.rollback()
            raise WorkspaceConflictError("Join request is already pending") from error
        except Exception:
            self._repository.rollback()
            raise
            
        created = self._repository.get_by_id(request_id)
        if not created:
            raise RuntimeError("Could not load created join request")
        return created

    def list_requests(self, workspace_id: int, user_id: int, status: str | None = None) -> list[JoinRequest]:
        self._workspace_service._require_owner(workspace_id, user_id)
        return self._repository.list_by_workspace(workspace_id, status=status)

    def approve_request(self, request_id: str, actor_id: int) -> JoinRequest:
        request = self._repository.get_by_id(request_id)
        if not request:
            raise JoinRequestNotFoundError("Request not found")
            
        self._workspace_service._require_owner(request.workspace_id, actor_id)
        
        if request.status != "PENDING":
            raise WorkspaceConflictError("Request is not pending")
            
        try:
            self._workspace_service._repository.add_member(
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                role="VIEWER",
                invited_by=actor_id
            )
            self._workspace_service._repository.record_activity(
                workspace_id=request.workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_MEMBER_APPROVED",
                detail=f"Join request approved for user {request.user_id}"
            )
            self._repository.update_status(request_id, "APPROVED")
            self._repository.commit()
            self._workspace_service._repository.commit()
        except Exception:
            self._repository.rollback()
            self._workspace_service._repository.rollback()
            raise
            
        updated = self._repository.get_by_id(request_id)
        if not updated:
            raise RuntimeError("Could not load updated join request")
        return updated

    def reject_request(self, request_id: str, actor_id: int) -> JoinRequest:
        request = self._repository.get_by_id(request_id)
        if not request:
            raise JoinRequestNotFoundError("Request not found")
            
        self._workspace_service._require_owner(request.workspace_id, actor_id)
        
        if request.status != "PENDING":
            raise WorkspaceConflictError("Request is not pending")
            
        try:
            self._repository.update_status(request_id, "REJECTED")
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
            
        updated = self._repository.get_by_id(request_id)
        if not updated:
            raise RuntimeError("Could not load updated join request")
        return updated

    def bulk_approve_requests(self, workspace_id: int, request_ids: list[str], actor_id: int) -> dict[str, Any]:
        self._workspace_service._require_owner(workspace_id, actor_id)
        
        approved_count = 0
        failed_count = 0
        
        for req_id in request_ids:
            try:
                req = self._repository.get_by_id(req_id)
                if not req or req.workspace_id != workspace_id or req.status != "PENDING":
                    failed_count += 1
                    continue
                
                self._workspace_service._repository.add_member(
                    workspace_id=workspace_id,
                    user_id=req.user_id,
                    role="VIEWER",
                    invited_by=actor_id
                )
                self._repository.update_status(req_id, "APPROVED")
                approved_count += 1
            except Exception:
                failed_count += 1
                
        if approved_count > 0:
            self._workspace_service._repository.record_activity(
                workspace_id=workspace_id,
                user_id=actor_id,
                activity_type="WORKSPACE_MEMBER_BULK_APPROVED",
                detail=f"Bulk approved {approved_count} join requests"
            )
            self._repository.commit()
            self._workspace_service._repository.commit()
        else:
            self._repository.rollback()
            self._workspace_service._repository.rollback()
            
        return {"approved": approved_count, "failed": failed_count}
