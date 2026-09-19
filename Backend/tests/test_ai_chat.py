"""Tests for Talk with Document AI — authorization, extraction, error handling."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.repositories.file_repository import FileRecord
from app.repositories.folder_repository import Folder
from app.services.file_service import FileNotFoundError, FilePermissionError, FileService
from app.services.storage_service import StorageDownloadError, StorageNotConfiguredError
from app.services.ai_service import (
    BedrockError,
    DocumentExtractionError,
    UnsupportedDocumentError,
    _bound_context,
    _extract_text_from_plain,
    chat_with_document,
    extract_document_text,
)


# ---------------------------------------------------------------------------
# Fixtures — reuse the same patterns from test_file_storage_phase2a
# ---------------------------------------------------------------------------

_SAMPLE_FILE = FileRecord(
    file_id=1,
    folder_id=20,
    uploaded_by=100,
    file_name="report.pdf",
    original_file_name="report.pdf",
    file_extension="pdf",
    mime_type="application/pdf",
    file_size=1024,
    storage_path="user_0100/ws/folder/report.pdf",
    file_hash="a" * 64,
    ai_enabled=False,
    is_archived=False,
    is_deleted=False,
    is_favorite=False,
    created_at=None,
    updated_at=None,
)

_SAMPLE_FOLDER = Folder(20, 10, None, "folder", None, "blue", False, False, 1, None, None)


class FakeWorkspaceService:
    def __init__(self, roles: dict[int, str]) -> None:
        self.roles = roles

    def get_workspace(self, workspace_id: int, actor_id: int):
        role = self.roles.get(actor_id)
        if role is None:
            from app.services.workspace_service import WorkspacePermissionError
            raise WorkspacePermissionError
        return SimpleNamespace(workspace_id=workspace_id, workspace_name="ws", member_role=role)


class FakeFolderService:
    def __init__(self, workspace: FakeWorkspaceService) -> None:
        self.workspace = workspace
        self.folder = _SAMPLE_FOLDER

    def get_folder(self, folder_id: int, actor_id: int) -> Folder:
        from app.services.workspace_service import WorkspacePermissionError
        from app.services.folder_service import FolderPermissionError
        try:
            self.workspace.get_workspace(self.folder.workspace_id, actor_id)
        except WorkspacePermissionError as error:
            raise FolderPermissionError from error
        return self.folder


class FakeFileRepository:
    def __init__(self) -> None:
        self.files: dict[int, FileRecord] = {1: _SAMPLE_FILE}
        self._activity: list[dict] = []

    def get_by_id(self, file_id: int, *, user_id: int, include_deleted: bool) -> FileRecord | None:
        f = self.files.get(file_id)
        if f is None:
            return None
        if not include_deleted and f.is_deleted:
            return None
        return f

    def record_activity(self, **kwargs) -> None:
        self._activity.append(kwargs)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------

class TestAIAuthorization:
    """The AI endpoint must reuse existing RBAC — never bypass it."""

    def _build_service(self, roles: dict[int, str]) -> FileService:
        ws = FakeWorkspaceService(roles)
        fs = FakeFolderService(ws)
        repo = FakeFileRepository()
        return FileService(repo, fs, ws)

    def test_authorized_user_can_access_file(self):
        """An OWNER can get the file (which the AI route calls first)."""
        svc = self._build_service({100: "OWNER"})
        file = svc.get_file(1, 100)
        assert file.file_id == 1

    def test_unauthorized_user_cannot_access_file(self):
        """A user without workspace membership is denied."""
        svc = self._build_service({100: "OWNER"})
        with pytest.raises(FilePermissionError):
            svc.get_file(1, 999)

    def test_nonexistent_file_rejected(self):
        """Requesting a file that does not exist raises FileNotFoundError."""
        svc = self._build_service({100: "OWNER"})
        with pytest.raises(FileNotFoundError):
            svc.get_file(9999, 100)

    def test_deleted_file_rejected(self):
        """A soft-deleted file is not accessible for AI."""
        ws = FakeWorkspaceService({100: "OWNER"})
        fs = FakeFolderService(ws)
        repo = FakeFileRepository()
        deleted_file = FileRecord(
            file_id=2, folder_id=20, uploaded_by=100,
            file_name="deleted.pdf", original_file_name="deleted.pdf",
            file_extension="pdf", mime_type="application/pdf",
            file_size=100, storage_path="path", file_hash="b" * 64,
            ai_enabled=False, is_archived=False, is_deleted=True,
            is_favorite=False, created_at=None, updated_at=None,
        )
        repo.files[2] = deleted_file
        svc = FileService(repo, fs, ws)
        with pytest.raises(FileNotFoundError):
            svc.get_file(2, 100)

    def test_viewer_can_read_file_for_ai(self):
        """A VIEWER has read access — AI should work for them too."""
        svc = self._build_service({200: "VIEWER"})
        file = svc.get_file(1, 200)
        assert file.file_id == 1


# ---------------------------------------------------------------------------
# Text extraction tests
# ---------------------------------------------------------------------------

class TestDocumentExtraction:
    """Extraction pipeline must handle supported and unsupported types."""

    def test_plain_text_extraction(self):
        text = _extract_text_from_plain(b"Hello world")
        assert text == "Hello world"

    def test_plain_text_latin1_fallback(self):
        text = _extract_text_from_plain("café résumé".encode("latin-1"))
        assert "caf" in text

    def test_unsupported_mime_raises(self):
        with pytest.raises(UnsupportedDocumentError):
            extract_document_text(b"binary garbage", "application/octet-stream")

    def test_unsupported_binary_raises(self):
        """Binary formats like octet-stream are rejected."""
        with pytest.raises(UnsupportedDocumentError):
            extract_document_text(b"\x00\x01\x02binary", "image/png")

    def test_text_mime_types_supported(self):
        for mime in ("text/plain", "text/csv", "application/json"):
            text = extract_document_text(b"content", mime)
            assert text == "content"


# ---------------------------------------------------------------------------
# Context bounding tests
# ---------------------------------------------------------------------------

class TestContextBounding:
    """Context must be truncated to prevent oversized Bedrock requests."""

    def test_short_text_unchanged(self):
        assert _bound_context("short text", max_chars=1000) == "short text"

    def test_long_text_truncated(self):
        long_text = "word " * 20000
        result = _bound_context(long_text, max_chars=100)
        assert len(result) < 200
        assert "[Document truncated" in result

    def test_truncation_at_word_boundary(self):
        text = "hello world this is a test string for truncation"
        result = _bound_context(text, max_chars=30)
        assert not result.endswith("trun")  # Should truncate at a word boundary


# ---------------------------------------------------------------------------
# Bedrock invocation tests (mocked)
# ---------------------------------------------------------------------------

class TestBedrockInvocation:
    """Bedrock errors should be handled gracefully."""

    @patch("app.services.ai_service.invoke_bedrock")
    def test_bedrock_failure_handled(self, mock_invoke):
        mock_invoke.side_effect = BedrockError("Service unavailable")
        with pytest.raises(BedrockError, match="Service unavailable"):
            chat_with_document(b"Some content", "text/plain", "test.txt", "Summarize")

    @patch("app.services.ai_service.invoke_bedrock")
    def test_successful_chat(self, mock_invoke):
        mock_invoke.return_value = "This document is about testing."
        answer = chat_with_document(b"Test content here", "text/plain", "test.txt", "What is this about?")
        assert answer == "This document is about testing."

    def test_empty_document_raises(self):
        with pytest.raises(DocumentExtractionError, match="empty"):
            chat_with_document(b"", "text/plain", "test.txt", "Summarize")

    def test_whitespace_only_raises(self):
        with pytest.raises(DocumentExtractionError, match="empty"):
            chat_with_document(b"   \n\t  ", "text/plain", "test.txt", "Summarize")
