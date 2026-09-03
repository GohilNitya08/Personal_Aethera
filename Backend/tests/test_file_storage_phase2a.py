from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app.repositories.file_repository import FileRecord
from app.repositories.folder_repository import Folder
from app.services.file_service import FileConflictError, FilePermissionError, FileService
from app.services.folder_service import FolderPermissionError
from app.services.workspace_service import WorkspaceConflictError, WorkspacePermissionError
from app.services.storage_service import StorageUploadError


class FakeWorkspaceService:
    def __init__(self, roles: dict[int, str], *, limit: int = 1000) -> None:
        self.roles = roles
        self.storage_used = 0
        self.storage_limit = limit
        self._reserved = 0

    def get_workspace(self, workspace_id: int, actor_id: int):
        role = self.roles.get(actor_id)
        if role is None:
            raise WorkspacePermissionError
        return SimpleNamespace(workspace_id=workspace_id, member_role=role)

    def reserve_storage(self, workspace_id: int, actor_id: int, byte_count: int) -> None:
        self.get_workspace(workspace_id, actor_id)
        if self.storage_used + byte_count > self.storage_limit:
            raise WorkspaceConflictError
        self.storage_used += byte_count
        self._reserved += byte_count

    def rollback(self) -> None:
        self.storage_used -= self._reserved
        self._reserved = 0

    def commit(self) -> None:
        self._reserved = 0


class FakeFolderService:
    def __init__(self, workspace: FakeWorkspaceService) -> None:
        self.workspace = workspace
        self.folder = Folder(20, 10, None, "Private names", None, "blue", False, False, 1, None, None)

    def get_folder(self, folder_id: int, actor_id: int) -> Folder:
        try:
            self.workspace.get_workspace(self.folder.workspace_id, actor_id)
        except WorkspacePermissionError as error:
            raise FolderPermissionError from error
        return self.folder


class FakeFileRepository:
    def __init__(self, workspace: FakeWorkspaceService, *, fail_create: bool = False) -> None:
        self.workspace = workspace
        self.fail_create = fail_create
        self.values: dict | None = None
        self.files: dict[int, FileRecord] = {}

    def create_file(self, values):
        if self.fail_create:
            raise RuntimeError("metadata failed")
        self.values = dict(values)
        file = FileRecord(1, values["folder_id"], values["uploaded_by"], values["file_name"], values["original_file_name"], values["file_extension"], values["mime_type"], values["file_size"], values["storage_path"], values["file_hash"], values["ai_enabled"], False, False, False, None, None)
        self.files[1] = file
        return 1

    def get_by_id(self, file_id, *, user_id, include_deleted):
        file = self.files.get(file_id)
        if file is None or (file.is_deleted and not include_deleted):
            return None
        return file

    def record_activity(self, **kwargs):
        return None

    def commit(self):
        self.workspace.commit()

    def rollback(self):
        self.workspace.rollback()

    def set_deleted(self, file_id, *, is_deleted):
        self.files[file_id] = replace(self.files[file_id], is_deleted=is_deleted)
        return True


class FakeStorage:
    def __init__(self, *, upload_error: bool = False) -> None:
        self.upload_error = upload_error
        self.uploaded: list[tuple[str, bytes]] = []
        self.deleted: list[str] = []
        self.downloaded: list[str] = []

    def upload(self, stream, object_key, content_type):
        if self.upload_error:
            raise StorageUploadError("failed")
        self.uploaded.append((object_key, stream.read()))
        return object_key

    def delete(self, object_key):
        self.deleted.append(object_key)

    def temporary_download_url(self, object_key):
        self.downloaded.append(object_key)
        return f"https://private.example/{object_key}"


def make_service(*, roles: dict[int, str] | None = None, limit: int = 1000, fail_create: bool = False):
    workspace = FakeWorkspaceService(roles or {1: "OWNER"}, limit=limit)
    repository = FakeFileRepository(workspace, fail_create=fail_create)
    return FileService(repository, FakeFolderService(workspace), workspace), repository, workspace


def upload(name: str = "secret report.txt", data: bytes = b"aethera") -> UploadFile:
    return UploadFile(BytesIO(data), filename=name)


def test_multipart_upload_generates_private_server_owned_key_and_actual_metadata():
    service, repository, workspace = make_service()
    storage = FakeStorage()
    data = b"actual uploaded bytes"

    result = service.upload_file(1, 20, upload("personal plan.pdf", data), storage)

    assert result.file_size == len(data)
    assert result.file_hash == hashlib.sha256(data).hexdigest()
    assert result.storage_path.startswith("workspaces/10/folders/20/")
    assert result.storage_path.count("/") == 4
    assert uuid.UUID(result.storage_path.rsplit("/", 1)[1]).version == 4
    assert "personal plan.pdf" not in result.storage_path
    assert result.original_file_name == "personal plan.pdf"
    assert storage.uploaded == [(result.storage_path, data)]
    assert workspace.storage_used == len(data)
    assert repository.values is not None


def test_quota_is_enforced_without_uploading_or_consuming_storage():
    service, _, workspace = make_service(limit=3)
    storage = FakeStorage()

    with pytest.raises(FileConflictError, match="quota"):
        service.upload_file(1, 20, upload(data=b"four"), storage)

    assert workspace.storage_used == 0
    assert storage.uploaded == []


def test_storage_failure_rolls_back_quota_without_metadata_or_cleanup_attempt():
    service, repository, workspace = make_service()
    storage = FakeStorage(upload_error=True)

    with pytest.raises(StorageUploadError):
        service.upload_file(1, 20, upload(data=b"data"), storage)

    assert workspace.storage_used == 0
    assert repository.values is None
    assert storage.deleted == []


def test_metadata_failure_rolls_back_quota_and_deletes_uploaded_object():
    service, _, workspace = make_service(fail_create=True)
    storage = FakeStorage()

    with pytest.raises(RuntimeError, match="metadata"):
        service.upload_file(1, 20, upload(data=b"data"), storage)

    assert workspace.storage_used == 0
    assert storage.deleted == [storage.uploaded[0][0]]


@pytest.mark.parametrize("role", ["OWNER", "ADMIN", "EDITOR"])
def test_writer_roles_can_upload(role: str):
    service, _, _ = make_service(roles={1: role})
    assert service.upload_file(1, 20, upload(), FakeStorage()).uploaded_by == 1


def test_viewer_cannot_upload():
    service, _, _ = make_service(roles={1: "VIEWER"})
    with pytest.raises(FilePermissionError):
        service.upload_file(1, 20, upload(), FakeStorage())


def test_soft_delete_and_restore_do_not_change_stored_quota():
    service, repository, workspace = make_service()
    uploaded = service.upload_file(1, 20, upload(data=b"data"), FakeStorage())
    usage = workspace.storage_used

    service.delete_file(uploaded.file_id, 1)
    service.restore_file(uploaded.file_id, 1)

    assert workspace.storage_used == usage
    assert repository.files[uploaded.file_id].is_deleted is False


def test_download_requires_workspace_access_and_returns_temporary_url():
    service, repository, _ = make_service(roles={1: "EDITOR"})
    uploaded = service.upload_file(1, 20, upload(), FakeStorage())
    storage = FakeStorage()

    assert service.get_download_url(uploaded.file_id, 1, storage).startswith("https://private.example/")
    assert storage.downloaded == [repository.files[uploaded.file_id].storage_path]

    with pytest.raises(FilePermissionError):
        service.get_download_url(uploaded.file_id, 2, storage)
