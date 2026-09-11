from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.schemas.file import FileUpdateRequest
from app.schemas.folder import FolderUpdateRequest
from app.schemas.share import ShareCreateRequest
from app.services.file_service import FileService, FilePermissionError
from app.services.folder_service import FolderService
from app.services.share_service import ShareService, ShareValidationError
from app.services.workspace_service import WorkspaceService


@dataclass
class DummyWorkspace:
    workspace_id: int
    user_id: int
    workspace_name: str = "Workspace"
    description: str | None = None
    workspace_type: str = "PERSONAL"
    visibility: str = "PRIVATE"
    storage_used: int = 0
    storage_limit: int = 1000
    color: str = "blue"
    is_archived: bool = False
    created_at: object | None = None
    updated_at: object | None = None
    member_role: str | None = None


@dataclass
class DummyWorkspaceMember:
    member_id: int
    workspace_id: int
    user_id: int
    role: str
    invited_by: int | None = None
    joined_at: object | None = None


@dataclass
class DummyFolder:
    folder_id: int
    workspace_id: int
    parent_folder_id: int | None
    folder_name: str
    description: str | None
    color: str
    is_favorite: bool
    is_archived: bool
    created_by: int
    created_at: object | None
    updated_at: object | None


@dataclass
class DummyFile:
    file_id: int
    folder_id: int
    uploaded_by: int
    file_name: str
    original_file_name: str
    file_extension: str | None
    mime_type: str | None
    file_size: int
    storage_path: str
    file_hash: str
    ai_enabled: bool
    is_archived: bool
    is_deleted: bool
    is_favorite: bool
    created_at: object | None
    updated_at: object | None


@dataclass
class DummyShare:
    share_id: int
    file_id: int
    shared_by: int
    shared_with: int | None
    share_type: str
    permission: str
    share_link: str | None = None
    password_hash: str | None = None
    expires_at: object | None = None
    created_at: object | None = None


class DummyUserRepo:
    def __init__(self, users: dict[int, object]) -> None:
        self._users = users

    def get_active_by_id(self, user_id: int):
        return self._users.get(user_id)

    def get_user(self, user_id: int):
        if user_id not in self._users:
            raise LookupError(user_id)
        return self._users[user_id]


class DummyWorkspaceRepo:
    def __init__(self, workspaces: dict[int, DummyWorkspace], memberships: dict[int, dict[int, DummyWorkspaceMember]]) -> None:
        self._workspaces = workspaces
        self._memberships = memberships

    def get_by_id(self, workspace_id: int):
        return self._workspaces.get(workspace_id)

    def get_membership(self, workspace_id: int, user_id: int):
        return self._memberships.get(workspace_id, {}).get(user_id)

    def list_members(self, workspace_id: int):
        return list(self._memberships.get(workspace_id, {}).values())

    def update_member_role(self, workspace_id: int, user_id: int, role: str) -> bool:
        membership = self._memberships.get(workspace_id, {}).get(user_id)
        if membership is None:
            return False
        self._memberships[workspace_id][user_id] = DummyWorkspaceMember(
            member_id=membership.member_id,
            workspace_id=membership.workspace_id,
            user_id=membership.user_id,
            role=role,
            invited_by=membership.invited_by,
            joined_at=membership.joined_at,
        )
        return True

    def transfer_ownership(self, *, workspace_id: int, previous_owner_id: int, new_owner_id: int) -> bool:
        current = self._workspaces[workspace_id]
        self._workspaces[workspace_id] = DummyWorkspace(
            workspace_id=current.workspace_id,
            user_id=new_owner_id,
            workspace_name=current.workspace_name,
            description=current.description,
            workspace_type=current.workspace_type,
            visibility=current.visibility,
            storage_used=current.storage_used,
            storage_limit=current.storage_limit,
            color=current.color,
            is_archived=current.is_archived,
            created_at=current.created_at,
            updated_at=current.updated_at,
            member_role="OWNER",
        )
        previous = self._memberships[workspace_id][previous_owner_id]
        self._memberships[workspace_id][previous_owner_id] = DummyWorkspaceMember(
            member_id=previous.member_id,
            workspace_id=previous.workspace_id,
            user_id=previous.user_id,
            role="ADMIN",
            invited_by=previous.invited_by,
            joined_at=previous.joined_at,
        )
        new = self._memberships[workspace_id][new_owner_id]
        self._memberships[workspace_id][new_owner_id] = DummyWorkspaceMember(
            member_id=new.member_id,
            workspace_id=new.workspace_id,
            user_id=new.user_id,
            role="OWNER",
            invited_by=new.invited_by,
            joined_at=new.joined_at,
        )
        return True

    def record_activity(self, **kwargs):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None


class DummyFolderRepo:
    def __init__(self, folders: dict[int, DummyFolder]) -> None:
        self._folders = folders

    def get_by_id(self, folder_id: int, *, include_archived: bool):
        folder = self._folders.get(folder_id)
        if folder is None:
            return None
        if include_archived or not folder.is_archived:
            return folder
        return None

    def update(self, folder_id: int, changes):
        current = self._folders[folder_id]
        self._folders[folder_id] = DummyFolder(
            folder_id=current.folder_id,
            workspace_id=current.workspace_id,
            parent_folder_id=current.parent_folder_id,
            folder_name=changes.get("folder_name", current.folder_name),
            description=changes.get("description", current.description),
            color=changes.get("color", current.color),
            is_favorite=changes.get("is_favorite", current.is_favorite),
            is_archived=current.is_archived,
            created_by=current.created_by,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        return True

    def commit(self):
        return None

    def rollback(self):
        return None


class DummyFileRepo:
    def __init__(self, files: dict[int, DummyFile]) -> None:
        self._files = files

    def get_by_id(self, file_id: int, *, user_id: int, include_deleted: bool):
        file = self._files.get(file_id)
        if file is None:
            return None
        if include_deleted or not file.is_deleted:
            return file
        return None

    def update_metadata(self, file_id: int, changes):
        current = self._files[file_id]
        self._files[file_id] = DummyFile(
            file_id=current.file_id,
            folder_id=current.folder_id,
            uploaded_by=current.uploaded_by,
            file_name=changes.get("file_name", current.file_name),
            original_file_name=current.original_file_name,
            file_extension=current.file_extension,
            mime_type=changes.get("mime_type", current.mime_type),
            file_size=current.file_size,
            storage_path=current.storage_path,
            file_hash=current.file_hash,
            ai_enabled=changes.get("ai_enabled", current.ai_enabled),
            is_archived=current.is_archived,
            is_deleted=current.is_deleted,
            is_favorite=current.is_favorite,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        return True

    def record_activity(self, **kwargs):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def add_favorite(self, file_id: int, user_id: int):
        return None

    def remove_favorite(self, file_id: int, user_id: int):
        return True

    def create_file(self, values):
        return 1

    def list_versions(self, file_id: int):
        return []

    def next_version_number(self, file_id: int):
        return 1

    def create_version(self, values):
        return 1

    def get_version(self, version_id: int):
        return None

    def set_deleted(self, file_id: int, *, is_deleted: bool):
        current = self._files[file_id]
        self._files[file_id] = DummyFile(
            file_id=current.file_id,
            folder_id=current.folder_id,
            uploaded_by=current.uploaded_by,
            file_name=current.file_name,
            original_file_name=current.original_file_name,
            file_extension=current.file_extension,
            mime_type=current.mime_type,
            file_size=current.file_size,
            storage_path=current.storage_path,
            file_hash=current.file_hash,
            ai_enabled=current.ai_enabled,
            is_archived=current.is_archived,
            is_deleted=is_deleted,
            is_favorite=current.is_favorite,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        return True


class DummyShareRepo:
    def __init__(self, shares: dict[int, DummyShare] | None = None) -> None:
        self._shares = shares or {}

    def get_active_duplicate(self, *, file_id: int, share_type: str, shared_with: int | None):
        for share in self._shares.values():
            if share.file_id == file_id and share.share_type == share_type and share.shared_with == shared_with:
                return share
        return None

    def create(self, values):
        share_id = max(self._shares, default=0) + 1
        self._shares[share_id] = DummyShare(
            share_id=share_id,
            file_id=values["file_id"],
            shared_by=values["shared_by"],
            shared_with=values["shared_with"],
            share_type=values["share_type"],
            permission=values["permission"],
            share_link=values["share_link"],
            password_hash=values["password_hash"],
            expires_at=values["expires_at"],
            created_at=None,
        )
        return share_id

    def get_by_id(self, share_id: int):
        return self._shares.get(share_id)

    def update(self, share_id: int, changes):
        return True

    def delete(self, share_id: int):
        self._shares.pop(share_id, None)
        return True

    def list_by_sharer(self, shared_by: int):
        return [share for share in self._shares.values() if share.shared_by == shared_by]

    def get_by_link(self, share_link: str):
        for share in self._shares.values():
            if share.share_link == share_link:
                return share
        return None

    def commit(self):
        return None

    def rollback(self):
        return None


def _workspace(workspace_id: int, user_id: int) -> DummyWorkspace:
    return DummyWorkspace(
        workspace_id=workspace_id,
        user_id=user_id,
        workspace_name=f"Workspace {workspace_id}",
        description=None,
        workspace_type="PERSONAL",
        visibility="PRIVATE",
        storage_used=0,
        storage_limit=1000,
        color="blue",
        is_archived=False,
        created_at=None,
        updated_at=None,
        member_role=None,
    )


def _folder(folder_id: int, workspace_id: int, *, created_by: int, archived: bool = False) -> DummyFolder:
    return DummyFolder(
        folder_id=folder_id,
        workspace_id=workspace_id,
        parent_folder_id=None,
        folder_name=f"Folder {folder_id}",
        description=None,
        color="blue",
        is_favorite=False,
        is_archived=archived,
        created_by=created_by,
        created_at=None,
        updated_at=None,
    )


def _file(file_id: int, folder_id: int, *, uploaded_by: int, is_deleted: bool = False) -> DummyFile:
    return DummyFile(
        file_id=file_id,
        folder_id=folder_id,
        uploaded_by=uploaded_by,
        file_name="report.txt",
        original_file_name="report.txt",
        file_extension="txt",
        mime_type="text/plain",
        file_size=12,
        storage_path="/tmp/report.txt",
        file_hash="abc",
        ai_enabled=False,
        is_archived=False,
        is_deleted=is_deleted,
        is_favorite=False,
        created_at=None,
        updated_at=None,
    )


def test_owner_admin_editor_write_permissions() -> None:
    # Real service contract: OWNER/ADMIN/EDITOR may update workspace-controlled files,
    # while VIEWER is blocked from destructive operations.
    workspace = _workspace(1, 10)
    folder = _folder(20, 1, created_by=10)
    file = _file(30, 20, uploaded_by=10)

    repo = DummyWorkspaceRepo(
        {1: workspace},
        {1: {
            10: DummyWorkspaceMember(1, 1, 10, "OWNER"),
            11: DummyWorkspaceMember(2, 1, 11, "ADMIN"),
            12: DummyWorkspaceMember(3, 1, 12, "EDITOR"),
            13: DummyWorkspaceMember(4, 1, 13, "VIEWER"),
        }},
    )
    workspace_service = WorkspaceService(repo, DummyUserRepo({10: object(), 11: object(), 12: object(), 13: object()}))
    folder_service = FolderService(DummyFolderRepo({20: folder}), workspace_service)
    file_service = FileService(DummyFileRepo({30: file}), folder_service, workspace_service)

    assert file_service.update_file(30, 11, FileUpdateRequest(file_name="admin.txt")).file_name == "admin.txt"
    with pytest.raises(FilePermissionError):
        file_service.update_file(30, 12, FileUpdateRequest(file_name="editor.txt"))
    assert file_service.get_file(30, 13).file_id == 30

    with pytest.raises(FilePermissionError):
        file_service.delete_file(30, 13)


def test_share_requires_same_workspace_member_recipient() -> None:
    workspace = _workspace(1, 10)
    folder = _folder(20, 1, created_by=10)
    file = _file(30, 20, uploaded_by=10)

    workspace_repo = DummyWorkspaceRepo(
        {1: workspace},
        {1: {
            10: DummyWorkspaceMember(1, 1, 10, "OWNER"),
            11: DummyWorkspaceMember(2, 1, 11, "ADMIN"),
        }},
    )
    workspace_service = WorkspaceService(workspace_repo, DummyUserRepo({10: object(), 11: object(), 99: object()}))
    folder_service = FolderService(DummyFolderRepo({20: folder}), workspace_service)
    file_service = FileService(DummyFileRepo({30: file}), folder_service, workspace_service)
    share_service = ShareService(
        DummyShareRepo(),
        file_service,
        folder_service,
        workspace_service,
        DummyUserRepo({10: object(), 11: object(), 99: object()}),
    )

    with pytest.raises(ShareValidationError):
        share_service.create_share(
            11,
            ShareCreateRequest(file_id=30, share_type="PRIVATE", shared_with=99, permission="VIEW"),
        )


def test_ownership_transfer_updates_roles_and_denies_invalid_targets() -> None:
    workspace = _workspace(1, 10)
    repo = DummyWorkspaceRepo(
        {1: workspace},
        {1: {
            10: DummyWorkspaceMember(1, 1, 10, "OWNER"),
            11: DummyWorkspaceMember(2, 1, 11, "EDITOR"),
        }},
    )
    workspace_service = WorkspaceService(repo, DummyUserRepo({10: object(), 11: object(), 12: object()}))

    result = workspace_service.transfer_ownership(1, 10, 11)
    assert result.user_id == 11
    assert repo.get_membership(1, 10).role == "ADMIN"
    assert repo.get_membership(1, 11).role == "OWNER"

    with pytest.raises(Exception):
        workspace_service.transfer_ownership(1, 11, 11)

    with pytest.raises(Exception):
        workspace_service.transfer_ownership(1, 11, 12)


def test_cross_workspace_resource_access_is_denied() -> None:
    workspace_a = _workspace(1, 10)
    workspace_b = _workspace(2, 20)
    folder_b = _folder(50, 2, created_by=20)
    file_b = _file(60, 50, uploaded_by=20)

    workspace_repo = DummyWorkspaceRepo(
        {1: workspace_a, 2: workspace_b},
        {1: {10: DummyWorkspaceMember(1, 1, 10, "OWNER")}, 2: {20: DummyWorkspaceMember(3, 2, 20, "OWNER")}},
    )
    workspace_service = WorkspaceService(workspace_repo, DummyUserRepo({10: object(), 20: object()}))
    folder_service = FolderService(DummyFolderRepo({50: folder_b}), workspace_service)
    file_service = FileService(DummyFileRepo({60: file_b}), folder_service, workspace_service)

    with pytest.raises(FilePermissionError):
        file_service.get_file(60, 10)


def test_editor_can_update_folder_not_created_by_them() -> None:
    workspace = _workspace(1, 10)
    folder = _folder(20, 1, created_by=10)

    repo = DummyWorkspaceRepo(
        {1: workspace},
        {1: {
            10: DummyWorkspaceMember(1, 1, 10, "OWNER"),
            11: DummyWorkspaceMember(2, 1, 11, "EDITOR"),
        }},
    )
    workspace_service = WorkspaceService(repo, DummyUserRepo({10: object(), 11: object()}))
    folder_service = FolderService(DummyFolderRepo({20: folder}), workspace_service)

    updated = folder_service.update_folder(20, 11, FolderUpdateRequest(folder_name="Updated folder"))
    assert updated.folder_name == "Updated folder"

def test_viewer_is_strictly_denied_management() -> None:
    workspace = _workspace(1, 10)
    repo = DummyWorkspaceRepo(
        {1: workspace},
        {1: {
            10: DummyWorkspaceMember(1, 1, 10, 'OWNER'),
            11: DummyWorkspaceMember(2, 1, 11, 'VIEWER'),
            12: DummyWorkspaceMember(3, 1, 12, 'EDITOR'),
        }},
    )
    from app.schemas.workspace import WorkspaceUpdateRequest
    from app.services.workspace_service import WorkspacePermissionError
    workspace_service = WorkspaceService(repo, DummyUserRepo({10: object(), 11: object()}))

    with pytest.raises(WorkspacePermissionError):
        workspace_service.update_workspace(1, 11, WorkspaceUpdateRequest(workspace_name='Hack'))

    with pytest.raises(WorkspacePermissionError):
        workspace_service.delete_workspace(1, 11)

    with pytest.raises(WorkspacePermissionError):
        workspace_service.transfer_ownership(1, 11, 11)

    with pytest.raises(WorkspacePermissionError):
        workspace_service.remove_member(1, 11, 12)
