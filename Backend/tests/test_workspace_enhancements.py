from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from app.repositories.join_request_repository import JoinRequest
from app.repositories.file_repository import FileVersion
from app.repositories.workspace_repository import WorkspaceRepository
from app.api.routes.files import _file_response, _version_response
from app.schemas.file import FileUpdateRequest
from app.schemas.folder import FolderCreateRequest, FolderUpdateRequest
from app.schemas.workspace import (
    WorkspaceInvitationRequest,
    WorkspaceMemberUpdateRequest,
    WorkspaceUpdateRequest,
)
from app.services.file_service import FilePermissionError, FileService
from app.services.folder_service import FolderPermissionError, FolderService
from app.services.join_request_service import JoinRequestService
from app.services.workspace_service import WorkspacePermissionError, WorkspaceService


@dataclass
class Workspace:
    workspace_id: int
    user_id: int
    visibility: str = "PRIVATE"
    workspace_name: str = "Workspace"
    description: str | None = None
    workspace_type: str = "PERSONAL"
    storage_used: int = 0
    storage_limit: int = 0
    color: str = "blue"
    is_archived: bool = False
    created_at: object | None = None
    updated_at: object | None = None
    member_role: str | None = None


@dataclass
class Member:
    member_id: int
    workspace_id: int
    user_id: int
    role: str
    invited_by: int | None = None
    joined_at: object | None = None


@dataclass
class Folder:
    folder_id: int
    workspace_id: int
    parent_folder_id: int | None = None
    folder_name: str = "Folder"
    description: str | None = None
    color: str = "blue"
    is_favorite: bool = False
    is_archived: bool = False
    created_by: int = 1
    created_at: object | None = None
    updated_at: object | None = None


@dataclass
class File:
    file_id: int
    folder_id: int
    uploaded_by: int
    file_name: str = "report.txt"
    original_file_name: str = "report.txt"
    file_extension: str | None = "txt"
    mime_type: str | None = "text/plain"
    file_size: int = 1
    storage_path: str = "object-key"
    file_hash: str = "hash"
    ai_enabled: bool = False
    is_archived: bool = False
    is_deleted: bool = False
    is_favorite: bool = False
    created_at: object | None = None
    updated_at: object | None = None


class WorkspaceRepo:
    def __init__(self, workspaces: dict[int, Workspace], members: dict[int, dict[int, Member]]):
        self.workspaces, self.members = workspaces, members
        self.added: list[tuple[int, int, str]] = []

    def get_by_id(self, workspace_id: int):
        return self.workspaces.get(workspace_id)

    def get_membership(self, workspace_id: int, user_id: int):
        return self.members.get(workspace_id, {}).get(user_id)

    def add_member(self, *, workspace_id: int, user_id: int, role: str, invited_by: int | None):
        self.members.setdefault(workspace_id, {})[user_id] = Member(
            len(self.members[workspace_id]) + 1, workspace_id, user_id, role, invited_by
        )
        self.added.append((workspace_id, user_id, role))
        return len(self.members[workspace_id])

    def record_activity(self, **_kwargs):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None


class UserRepo:
    def get_active_by_id(self, _user_id: int):
        return object()


class FolderRepo:
    def __init__(self, folders: dict[int, Folder]):
        self.folders = folders

    def get_by_id(self, folder_id: int, *, include_archived: bool):
        folder = self.folders.get(folder_id)
        return folder if folder and (include_archived or not folder.is_archived) else None

    def list_by_workspace(self, workspace_id: int, *, include_archived: bool):
        return [folder for folder in self.folders.values() if folder.workspace_id == workspace_id and (include_archived or not folder.is_archived)]

    def list_child_ids(self, parent_ids: list[int]):
        return [folder.folder_id for folder in self.folders.values() if folder.parent_folder_id in parent_ids]

    def set_archived(self, folder_ids: list[int], *, is_archived: bool):
        for folder_id in folder_ids:
            self.folders[folder_id] = replace(self.folders[folder_id], is_archived=is_archived)
        return len(folder_ids)

    def update(self, folder_id: int, changes: dict):
        self.folders[folder_id] = replace(self.folders[folder_id], **changes)
        return True

    def commit(self):
        return None

    def rollback(self):
        return None


class FileRepo:
    def __init__(self, file: File):
        self.file = file

    def get_by_id(self, file_id: int, *, user_id: int, include_deleted: bool):
        if file_id != self.file.file_id or (self.file.is_deleted and not include_deleted):
            return None
        return self.file

    def update_metadata(self, file_id: int, changes: dict):
        self.file = replace(self.file, **changes)
        return True


class JoinRepo:
    def __init__(self):
        self.requests: dict[str, JoinRequest] = {}

    def create(self, request_id: str, workspace_id: int, user_id: int):
        self.requests[request_id] = JoinRequest(request_id, workspace_id, user_id, "PENDING", None, None)
        return True

    def get_by_id(self, request_id: str):
        return self.requests.get(request_id)

    def get_by_user_and_workspace(self, user_id: int, workspace_id: int):
        return next((request for request in self.requests.values() if request.user_id == user_id and request.workspace_id == workspace_id), None)

    def reopen_rejected(self, request_id: str):
        request = self.requests[request_id]
        if request.status != "REJECTED":
            return False
        self.requests[request_id] = replace(request, status="PENDING")
        return True

    def update_status(self, request_id: str, status: str):
        self.requests[request_id] = replace(self.requests[request_id], status=status)
        return True

    def list_by_workspace(self, workspace_id: int, status: str | None = None):
        return [request for request in self.requests.values() if request.workspace_id == workspace_id and (status is None or request.status == status)]

    def commit(self):
        return None

    def rollback(self):
        return None


def workspace_service(visibility: str = "PRIVATE") -> tuple[WorkspaceService, WorkspaceRepo]:
    repo = WorkspaceRepo({1: Workspace(1, 1, visibility)}, {1: {1: Member(1, 1, 1, "OWNER"), 2: Member(2, 1, 2, "ADMIN")}})
    return WorkspaceService(repo, UserRepo()), repo


def test_folder_delete_and_restore_use_writer_authorization():
    service, _ = workspace_service()
    folders = FolderRepo({10: Folder(10, 1), 11: Folder(11, 1, parent_folder_id=10)})
    folder_service = FolderService(folders, service)

    folder_service.delete_folder(10, 1)
    assert folders.folders[10].is_archived and folders.folders[11].is_archived
    folder_service.restore_folder(10, 1)
    assert not folders.folders[10].is_archived and not folders.folders[11].is_archived

    with pytest.raises(FolderPermissionError):
        folder_service.delete_folder(10, 99)


def test_public_workspace_is_readable_but_not_writable_for_non_members():
    service, _ = workspace_service("PUBLIC")
    folder_service = FolderService(FolderRepo({10: Folder(10, 1)}), service)
    file_service = FileService(FileRepo(File(20, 10, 1)), folder_service, service)

    assert folder_service.list_folders(1, 99, include_archived=False)[0].folder_id == 10
    assert file_service.get_file(20, 99).file_id == 20
    with pytest.raises(FolderPermissionError):
        folder_service.list_folders(1, 99, include_archived=True)
    with pytest.raises(FilePermissionError):
        file_service.list_files(10, 99, include_deleted=True)
    with pytest.raises(FolderPermissionError):
        folder_service.create_folder(99, FolderCreateRequest(workspace_id=1, folder_name="Nope"))
    with pytest.raises(FolderPermissionError):
        folder_service.update_folder(10, 99, FolderUpdateRequest(folder_name="Nope"))
    with pytest.raises(FilePermissionError):
        file_service.update_file(20, 99, FileUpdateRequest(file_name="Nope.txt"))


def test_public_file_and_version_responses_redact_storage_paths():
    file = File(20, 10, 1, storage_path="private-object-key")
    version = FileVersion(30, 20, 1, "private-version-key", 1, "hash", 1, None, None)

    assert _file_response(file, expose_storage_path=False).storage_path is None
    assert _version_response(version, expose_storage_path=False).storage_path is None
    assert _file_response(file).storage_path == "private-object-key"


def test_private_join_request_is_pending_and_rejected_request_can_be_resubmitted():
    service, _ = workspace_service("PRIVATE")
    requests = JoinRepo()
    join_service = JoinRequestService(requests, service)

    original = join_service.submit_request(99, 1)
    assert original.status == "PENDING"
    with pytest.raises(Exception, match="already pending"):
        join_service.submit_request(99, 1)
    join_service.reject_request(original.request_id, 1)

    reopened = join_service.submit_request(99, 1)
    assert reopened.request_id == original.request_id
    assert reopened.status == "PENDING"
    assert len(requests.requests) == 1


def test_only_owner_can_decide_or_bulk_approve_join_requests():
    service, repo = workspace_service("PRIVATE")
    requests = JoinRepo()
    join_service = JoinRequestService(requests, service)
    first = join_service.submit_request(99, 1)
    second = join_service.submit_request(98, 1)

    with pytest.raises(WorkspacePermissionError):
        join_service.approve_request(first.request_id, 2)
    result = join_service.bulk_approve_requests(1, [first.request_id, second.request_id], 1)
    assert result == {"approved": 2, "failed": 0}
    assert {member.user_id for member in repo.members[1].values()} >= {98, 99}


class SearchResult:
    def mappings(self):
        return self

    def all(self):
        return []


class SearchDb:
    def __init__(self):
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement, self.params = statement, params
        return SearchResult()


def test_workspace_search_queries_id_and_name_without_access_filter():
    db = SearchDb()
    WorkspaceRepository(db).search_workspaces("42", 7)
    sql = str(db.statement)
    assert "CAST(w.workspace_id AS CHAR) LIKE :query" in sql
    assert "w.workspace_name LIKE :query" in sql
    assert "w.visibility = 'PUBLIC'" not in sql
    assert "COALESCE" not in sql
    assert "wm.role AS member_role" in sql
    assert db.params == {"user_id": 7, "query": "%42%"}


def test_workspace_identity_and_role_are_scoped_to_exact_membership():
    """Identically named workspaces must never share identity or owner privilege."""
    first = Workspace(101, 1, workspace_name="SEM 5")
    second = Workspace(202, 2, workspace_name="SEM 5")
    repo = WorkspaceRepo(
        {101: first, 202: second},
        {
            101: {1: Member(1, 101, 1, "OWNER"), 3: Member(3, 101, 3, "EDITOR")},
            202: {2: Member(2, 202, 2, "OWNER"), 4: Member(4, 202, 4, "VIEWER")},
        },
    )
    service = WorkspaceService(repo, UserRepo())

    assert service.get_workspace(101, 1).member_role == "OWNER"
    assert service.get_workspace(202, 2).member_role == "OWNER"
    assert service.get_workspace(101, 3).member_role == "EDITOR"
    assert service.get_workspace(202, 4).member_role == "VIEWER"
    with pytest.raises(WorkspacePermissionError):
        service.get_workspace(202, 1)
    with pytest.raises(WorkspacePermissionError):
        service.get_workspace(101, 2)


def test_creator_without_membership_is_not_promoted_to_owner():
    """The creator column is metadata; membership is the only role authority."""
    repo = WorkspaceRepo({1: Workspace(1, 1)}, {1: {2: Member(2, 1, 2, "VIEWER")}})
    service = WorkspaceService(repo, UserRepo())

    with pytest.raises(WorkspacePermissionError):
        service.get_workspace(1, 1)
    with pytest.raises(WorkspacePermissionError):
        service.update_workspace(1, 1, WorkspaceUpdateRequest(workspace_name="Nope"))
    assert service.get_workspace(1, 2).member_role == "VIEWER"


def test_editor_can_add_members_but_cannot_manage_members_or_settings():
    repo = WorkspaceRepo(
        {1: Workspace(1, 1)},
        {1: {1: Member(1, 1, 1, "OWNER"), 3: Member(3, 1, 3, "EDITOR"), 4: Member(4, 1, 4, "VIEWER")}},
    )
    service = WorkspaceService(repo, UserRepo())

    added = service.invite_member(1, 3, WorkspaceInvitationRequest(user_id=5, role="VIEWER"))
    assert added.workspace_id == 1 and added.user_id == 5 and added.role == "VIEWER"
    with pytest.raises(WorkspacePermissionError):
        service.update_member(1, 3, 4, WorkspaceMemberUpdateRequest(role="EDITOR"))
    with pytest.raises(WorkspacePermissionError):
        service.remove_member(1, 3, 4)
    with pytest.raises(WorkspacePermissionError):
        service.update_workspace(1, 3, WorkspaceUpdateRequest(workspace_name="Nope"))
    with pytest.raises(WorkspacePermissionError):
        service.invite_member(1, 4, WorkspaceInvitationRequest(user_id=6, role="VIEWER"))
