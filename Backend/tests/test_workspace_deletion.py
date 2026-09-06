from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.repositories.folder_repository import Folder
from app.repositories.workspace_repository import (
    Workspace,
    WorkspaceMember,
    WorkspaceRepository,
)
from app.services.folder_service import FolderPermissionError, FolderService
from app.services.storage_service import ObjectStorage
from app.services.workspace_service import (
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    WorkspacePermissionError,
    WorkspaceService,
)


def create_test_workspace(
    workspace_id: int = 1,
    user_id: int = 1,
    workspace_name: str = "Engineering Team",
    description: str | None = "Docs",
    workspace_type: str = "PERSONAL",
    visibility: str = "PRIVATE",
    storage_used: int = 0,
    storage_limit: int = 10000,
    color: str = "blue",
    is_archived: bool = False,
    member_role: str | None = None,
) -> Workspace:
    return Workspace(
        workspace_id=workspace_id,
        user_id=user_id,
        workspace_name=workspace_name,
        description=description,
        workspace_type=workspace_type,
        visibility=visibility,
        storage_used=storage_used,
        storage_limit=storage_limit,
        color=color,
        is_archived=is_archived,
        created_at=None,
        updated_at=None,
        member_role=member_role,
    )


class FakeStorageSpy(ObjectStorage):
    def __init__(self, failing_keys: set[str] | None = None) -> None:
        self.failing_keys = failing_keys or set()
        self.deleted_keys: list[str] = []

    def upload(self, key: str, data: Any, content_type: str | None = None) -> None:
        pass

    def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        return f"https://example.com/{key}"

    def delete(self, key: str) -> None:
        if key in self.failing_keys:
            raise RuntimeError(f"S3 deletion failed for key: {key}")
        self.deleted_keys.append(key)


class FakeWorkspaceRepo:
    def __init__(
        self,
        workspaces: dict[int, Workspace],
        members: dict[int, dict[int, WorkspaceMember]],
        storage_keys: dict[int, list[str]] | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.members = members
        self.storage_keys = storage_keys or {}
        self.committed = False
        self.rolled_back = False
        self.activity_records: list[dict[str, Any]] = []

    def get_by_id(self, workspace_id: int) -> Workspace | None:
        return self.workspaces.get(workspace_id)

    def get_membership(self, workspace_id: int, user_id: int) -> WorkspaceMember | None:
        return self.members.get(workspace_id, {}).get(user_id)

    def list_for_user(self, user_id: int, *, include_archived: bool = False) -> list[Workspace]:
        results: list[Workspace] = []
        for ws_id, ws in self.workspaces.items():
            if ws.is_archived and not include_archived:
                continue
            member = self.members.get(ws_id, {}).get(user_id)
            if member:
                results.append(replace(ws, member_role=member.role))
            elif ws.user_id == user_id:
                results.append(replace(ws, member_role="OWNER"))
            elif ws.visibility == "PUBLIC":
                results.append(replace(ws, member_role=None))
        return results

    def get_storage_keys(self, workspace_id: int) -> list[str]:
        return list(self.storage_keys.get(workspace_id, []))

    def delete_workspace(self, workspace_id: int) -> bool:
        if workspace_id not in self.workspaces:
            return False
        del self.workspaces[workspace_id]
        self.members.pop(workspace_id, None)
        self.storage_keys.pop(workspace_id, None)
        return True

    def record_activity(self, **kwargs: Any) -> None:
        self.activity_records.append(kwargs)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeUserRepo:
    def get_active_by_id(self, _user_id: int) -> object:
        return object()


class FakeFolderRepo:
    def __init__(self, folders: dict[int, Folder]) -> None:
        self.folders = folders
        self.committed = False
        self.rolled_back = False

    def get_by_id(self, folder_id: int, *, include_archived: bool = False) -> Folder | None:
        folder = self.folders.get(folder_id)
        if folder and (include_archived or not folder.is_archived):
            return folder
        return None

    def list_by_workspace(self, workspace_id: int, *, include_archived: bool = False) -> list[Folder]:
        return [
            f
            for f in self.folders.values()
            if f.workspace_id == workspace_id and (include_archived or not f.is_archived)
        ]

    def list_child_ids(self, parent_ids: list[int]) -> list[int]:
        return [f.folder_id for f in self.folders.values() if f.parent_folder_id in parent_ids]

    def set_archived(self, folder_ids: list[int], *, is_archived: bool) -> int:
        for fid in folder_ids:
            if fid in self.folders:
                self.folders[fid] = replace(self.folders[fid], is_archived=is_archived)
        return len(folder_ids)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def test_owner_deletes_workspace_globally_and_cleans_up_s3():
    ws = create_test_workspace(
        workspace_id=1,
        user_id=1,
        workspace_name="Engineering Team",
        description="Docs",
        workspace_type="PERSONAL",
        visibility="PRIVATE",
        storage_used=2048,
        storage_limit=10000,
    )
    members = {
        1: {
            1: WorkspaceMember(1, 1, 1, "OWNER", None, None),
            2: WorkspaceMember(2, 1, 2, "ADMIN", 1, None),
            3: WorkspaceMember(3, 1, 3, "VIEWER", 1, None),
        }
    }
    keys = ["workspaces/1/files/doc1.pdf", "workspaces/1/files/img1.png"]
    repo = FakeWorkspaceRepo({1: ws}, members, {1: keys})
    service = WorkspaceService(repo, FakeUserRepo())
    storage = FakeStorageSpy()

    service.delete_workspace(workspace_id=1, actor_id=1, storage=storage)

    assert repo.committed is True
    assert repo.rolled_back is False
    assert storage.deleted_keys == keys
    assert repo.get_by_id(1) is None
    assert repo.get_membership(1, 1) is None
    assert repo.get_membership(1, 2) is None
    assert repo.get_membership(1, 3) is None

    with pytest.raises(WorkspaceNotFoundError):
        service.get_workspace(1, user_id=1)
    with pytest.raises(WorkspaceNotFoundError):
        service.get_workspace(1, user_id=2)
    with pytest.raises(WorkspaceNotFoundError):
        service.get_workspace(1, user_id=3)
    with pytest.raises(WorkspaceNotFoundError):
        service.get_workspace(1, user_id=99)

    assert service.list_workspaces(user_id=2, include_archived=False) == []
    assert service.list_workspaces(user_id=3, include_archived=False) == []


def test_non_owners_cannot_delete_workspace():
    ws = create_test_workspace(
        workspace_id=1,
        user_id=1,
        workspace_name="Engineering Team",
        description="Docs",
        workspace_type="PERSONAL",
        visibility="PRIVATE",
        storage_used=1024,
        storage_limit=10000,
    )
    members = {
        1: {
            1: WorkspaceMember(1, 1, 1, "OWNER", None, None),
            2: WorkspaceMember(2, 1, 2, "ADMIN", 1, None),
            3: WorkspaceMember(3, 1, 3, "EDITOR", 1, None),
            4: WorkspaceMember(4, 1, 4, "VIEWER", 1, None),
        }
    }
    keys = ["workspaces/1/files/doc1.pdf"]
    repo = FakeWorkspaceRepo({1: ws}, members, {1: keys})
    service = WorkspaceService(repo, FakeUserRepo())
    storage = FakeStorageSpy()

    with pytest.raises(WorkspacePermissionError):
        service.delete_workspace(workspace_id=1, actor_id=2, storage=storage)

    with pytest.raises(WorkspacePermissionError):
        service.delete_workspace(workspace_id=1, actor_id=3, storage=storage)

    with pytest.raises(WorkspacePermissionError):
        service.delete_workspace(workspace_id=1, actor_id=4, storage=storage)

    with pytest.raises(WorkspacePermissionError):
        service.delete_workspace(workspace_id=1, actor_id=99, storage=storage)

    assert repo.get_by_id(1) is not None
    assert storage.deleted_keys == []


def test_delete_nonexistent_workspace_raises_not_found():
    repo = FakeWorkspaceRepo({}, {})
    service = WorkspaceService(repo, FakeUserRepo())
    storage = FakeStorageSpy()

    with pytest.raises(WorkspaceNotFoundError):
        service.delete_workspace(workspace_id=999, actor_id=1, storage=storage)
    assert storage.deleted_keys == []


def test_s3_cleanup_failure_does_not_corrupt_db_and_logs_orphaned_object(caplog):
    ws = create_test_workspace(
        workspace_id=1,
        user_id=1,
        workspace_name="Engineering Team",
        description="Docs",
        workspace_type="PERSONAL",
        visibility="PRIVATE",
        storage_used=2048,
        storage_limit=10000,
    )
    members = {1: {1: WorkspaceMember(1, 1, 1, "OWNER", None, None)}}
    keys = ["workspaces/1/files/fail-obj.pdf", "workspaces/1/files/ok-obj.png"]
    repo = FakeWorkspaceRepo({1: ws}, members, {1: keys})
    service = WorkspaceService(repo, FakeUserRepo())
    storage = FakeStorageSpy(failing_keys={"workspaces/1/files/fail-obj.pdf"})

    with caplog.at_level(logging.ERROR):
        service.delete_workspace(workspace_id=1, actor_id=1, storage=storage)

    assert repo.committed is True
    assert repo.rolled_back is False
    assert repo.get_by_id(1) is None
    assert "workspaces/1/files/ok-obj.png" in storage.deleted_keys

    assert any(
        "orphaned S3 object" in record.message and "workspaces/1/files/fail-obj.pdf" in record.message
        for record in caplog.records
    )


def test_folder_deletion_role_permissions():
    ws = create_test_workspace(
        workspace_id=1,
        user_id=1,
        workspace_name="Engineering Team",
        description="Docs",
        workspace_type="PERSONAL",
        visibility="PRIVATE",
        storage_used=0,
        storage_limit=10000,
    )
    members = {
        1: {
            1: WorkspaceMember(1, 1, 1, "OWNER", None, None),
            2: WorkspaceMember(2, 1, 2, "ADMIN", 1, None),
            3: WorkspaceMember(3, 1, 3, "EDITOR", 1, None),
            4: WorkspaceMember(4, 1, 4, "VIEWER", 1, None),
        }
    }
    ws_repo = FakeWorkspaceRepo({1: ws}, members)
    ws_service = WorkspaceService(ws_repo, FakeUserRepo())

    folder10 = Folder(10, 1, None, "Owner Folder", None, "blue", False, False, 1, None, None)
    folder20 = Folder(20, 1, None, "Editor Folder", None, "blue", False, False, 3, None, None)
    folder_repo = FakeFolderRepo({10: folder10, 20: folder20})
    folder_service = FolderService(folder_repo, ws_service)

    with pytest.raises(FolderPermissionError):
        folder_service.delete_folder(folder_id=10, actor_id=4)
    with pytest.raises(FolderPermissionError):
        folder_service.delete_folder(folder_id=20, actor_id=4)

    with pytest.raises(FolderPermissionError, match="Editors can only delete folders they created"):
        folder_service.delete_folder(folder_id=10, actor_id=3)

    folder_service.delete_folder(folder_id=20, actor_id=3)
    assert folder_repo.folders[20].is_archived is True

    folder_repo.folders[20] = replace(folder_repo.folders[20], is_archived=False)

    folder_service.delete_folder(folder_id=20, actor_id=2)
    assert folder_repo.folders[20].is_archived is True

    folder_service.delete_folder(folder_id=10, actor_id=1)
    assert folder_repo.folders[10].is_archived is True


def test_sqlite_database_cascading_deletion_integration():
    ddl = '''
    CREATE TABLE workspaces (
        workspace_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        workspace_name TEXT NOT NULL,
        description TEXT,
        workspace_type TEXT NOT NULL,
        visibility TEXT DEFAULT 'PRIVATE',
        storage_used INTEGER DEFAULT 0,
        storage_limit INTEGER DEFAULT 0,
        color TEXT DEFAULT 'blue',
        is_archived BOOLEAN DEFAULT 0,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE workspace_members (
        member_id INTEGER PRIMARY KEY,
        workspace_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        invited_by INTEGER,
        joined_at TIMESTAMP
    );
    CREATE TABLE folders (
        folder_id INTEGER PRIMARY KEY,
        workspace_id INTEGER NOT NULL,
        parent_folder_id INTEGER,
        folder_name TEXT NOT NULL,
        description TEXT,
        color TEXT DEFAULT 'blue',
        is_favorite BOOLEAN DEFAULT 0,
        is_archived BOOLEAN DEFAULT 0,
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE files (
        file_id INTEGER PRIMARY KEY,
        folder_id INTEGER NOT NULL,
        uploaded_by INTEGER NOT NULL,
        file_name TEXT NOT NULL,
        original_file_name TEXT NOT NULL,
        file_extension TEXT,
        mime_type TEXT,
        file_size INTEGER NOT NULL,
        storage_path TEXT NOT NULL,
        file_hash TEXT NOT NULL,
        ai_enabled BOOLEAN DEFAULT 0,
        is_favorite BOOLEAN DEFAULT 0,
        is_archived BOOLEAN DEFAULT 0,
        is_deleted BOOLEAN DEFAULT 0,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE file_versions (
        version_id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        version_number INTEGER NOT NULL,
        storage_path TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        file_hash TEXT NOT NULL,
        uploaded_by INTEGER NOT NULL,
        version_note TEXT,
        created_at TIMESTAMP
    );
    CREATE TABLE file_shares (
        share_id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        shared_by INTEGER NOT NULL,
        shared_with INTEGER,
        share_type TEXT DEFAULT 'PRIVATE',
        permission TEXT DEFAULT 'VIEW',
        share_link TEXT,
        password_hash TEXT,
        expires_at TIMESTAMP,
        created_at TIMESTAMP
    );
    CREATE TABLE comments (
        comment_id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        comment TEXT NOT NULL,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    CREATE TABLE activity_logs (
        activity_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        file_id INTEGER,
        activity_type TEXT NOT NULL,
        activity_description TEXT,
        created_at TIMESTAMP
    );
    CREATE TABLE favorites (
        favorite_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        file_id INTEGER NOT NULL,
        created_at TIMESTAMP
    );
    CREATE TABLE tags (
        tag_id INTEGER PRIMARY KEY,
        tag_name TEXT NOT NULL
    );
    CREATE TABLE file_tags (
        file_tag_id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL
    );
    CREATE TABLE workspace_join_requests (
        request_id TEXT PRIMARY KEY,
        workspace_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT DEFAULT 'PENDING',
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    '''
    engine = create_engine('sqlite:///:memory:')
    with engine.connect() as conn:
        for stmt in ddl.strip().split(';'):
            if stmt.strip():
                conn.execute(text(stmt.strip()))
        conn.commit()

    Session = sessionmaker(bind=engine)
    session = Session()
    repo = WorkspaceRepository(session)

    session.execute(text("INSERT INTO workspaces (workspace_id, user_id, workspace_name, workspace_type) VALUES (1, 10, 'Target WS', 'PERSONAL')"))
    session.execute(text("INSERT INTO workspace_members (member_id, workspace_id, user_id, role) VALUES (1, 1, 10, 'OWNER')"))
    session.execute(text("INSERT INTO workspace_members (member_id, workspace_id, user_id, role) VALUES (2, 1, 11, 'ADMIN')"))
    session.execute(text("INSERT INTO workspace_members (member_id, workspace_id, user_id, role) VALUES (3, 1, 12, 'VIEWER')"))
    session.execute(text("INSERT INTO workspace_join_requests (request_id, workspace_id, user_id, status) VALUES ('req-ws1', 1, 13, 'PENDING')"))

    session.execute(text("INSERT INTO folders (folder_id, workspace_id, parent_folder_id, folder_name, created_by) VALUES (100, 1, NULL, 'Root Folder', 10)"))
    session.execute(text("INSERT INTO folders (folder_id, workspace_id, parent_folder_id, folder_name, created_by) VALUES (101, 1, 100, 'Child Folder', 10)"))

    session.execute(text("INSERT INTO files (file_id, folder_id, uploaded_by, file_name, original_file_name, file_size, storage_path, file_hash) VALUES (200, 100, 10, 'f1.pdf', 'f1.pdf', 100, 's3://bucket/key-1', 'h1')"))
    session.execute(text("INSERT INTO files (file_id, folder_id, uploaded_by, file_name, original_file_name, file_size, storage_path, file_hash) VALUES (201, 101, 10, 'f2.png', 'f2.png', 200, 's3://bucket/key-2', 'h2')"))

    session.execute(text("INSERT INTO file_versions (version_id, file_id, version_number, storage_path, file_size, file_hash, uploaded_by) VALUES (300, 200, 2, 's3://bucket/key-1-v2', 150, 'h1v2', 10)"))

    session.execute(text("INSERT INTO file_shares (share_id, file_id, shared_by) VALUES (400, 200, 10)"))
    session.execute(text("INSERT INTO comments (comment_id, file_id, user_id, comment) VALUES (500, 200, 10, 'Great doc')"))
    session.execute(text("INSERT INTO favorites (favorite_id, user_id, file_id) VALUES (600, 10, 200)"))
    session.execute(text("INSERT INTO tags (tag_id, tag_name) VALUES (1, 'reports')"))
    session.execute(text("INSERT INTO file_tags (file_tag_id, file_id, tag_id) VALUES (700, 200, 1)"))
    session.execute(text("INSERT INTO activity_logs (activity_id, user_id, file_id, activity_type, activity_description) VALUES (800, 10, 200, 'FILE_UPLOAD', 'Uploaded f1.pdf')"))

    session.execute(text("INSERT INTO workspaces (workspace_id, user_id, workspace_name, workspace_type) VALUES (2, 20, 'Other WS', 'PERSONAL')"))
    session.execute(text("INSERT INTO workspace_members (member_id, workspace_id, user_id, role) VALUES (4, 2, 20, 'OWNER')"))
    session.execute(text("INSERT INTO folders (folder_id, workspace_id, parent_folder_id, folder_name, created_by) VALUES (2000, 2, NULL, 'WS2 Folder', 20)"))
    session.execute(text("INSERT INTO files (file_id, folder_id, uploaded_by, file_name, original_file_name, file_size, storage_path, file_hash) VALUES (3000, 2000, 20, 'other.txt', 'other.txt', 50, 's3://bucket/other-key', 'h3')"))
    session.execute(text("INSERT INTO file_versions (version_id, file_id, version_number, storage_path, file_size, file_hash, uploaded_by) VALUES (4000, 3000, 2, 's3://bucket/other-v2', 60, 'h3v2', 20)"))
    session.execute(text("INSERT INTO activity_logs (activity_id, user_id, file_id, activity_type, activity_description) VALUES (900, 20, 3000, 'FILE_UPLOAD', 'WS2 file')"))
    session.execute(text("INSERT INTO workspace_join_requests (request_id, workspace_id, user_id, status) VALUES ('req-ws2', 2, 21, 'PENDING')"))
    session.commit()

    storage_keys = repo.get_storage_keys(1)
    assert set(storage_keys) == {"s3://bucket/key-1", "s3://bucket/key-2", "s3://bucket/key-1-v2"}
    assert "s3://bucket/other-key" not in storage_keys
    assert "s3://bucket/other-v2" not in storage_keys

    assert repo.delete_workspace(1) is True
    session.commit()

    assert session.execute(text("SELECT COUNT(*) FROM workspaces WHERE workspace_id = 1")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM workspace_members WHERE workspace_id = 1")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM workspace_join_requests WHERE workspace_id = 1")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM folders WHERE workspace_id = 1")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM files WHERE folder_id IN (100, 101)")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM file_versions WHERE file_id IN (200, 201)")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM file_shares WHERE file_id = 200")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM comments WHERE file_id = 200")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM favorites WHERE file_id = 200")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM file_tags WHERE file_id = 200")).scalar() == 0

    ws1_log = session.execute(text("SELECT file_id, activity_description FROM activity_logs WHERE activity_id = 800")).first()
    assert ws1_log is not None
    assert ws1_log[0] is None
    assert ws1_log[1] == "Uploaded f1.pdf"

    assert session.execute(text("SELECT COUNT(*) FROM workspaces WHERE workspace_id = 2")).scalar() == 1
    assert session.execute(text("SELECT COUNT(*) FROM workspace_members WHERE workspace_id = 2")).scalar() == 1
    assert session.execute(text("SELECT COUNT(*) FROM workspace_join_requests WHERE workspace_id = 2")).scalar() == 1
    assert session.execute(text("SELECT COUNT(*) FROM folders WHERE workspace_id = 2")).scalar() == 1
    assert session.execute(text("SELECT COUNT(*) FROM files WHERE file_id = 3000")).scalar() == 1
    assert session.execute(text("SELECT COUNT(*) FROM file_versions WHERE file_id = 3000")).scalar() == 1
    ws2_log = session.execute(text("SELECT file_id FROM activity_logs WHERE activity_id = 900")).scalar()
    assert ws2_log == 3000
