"""Pydantic response models for the unified search endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SearchFolderResult(BaseModel):
    """A folder result returned by the unified search."""

    folder_id: int
    folder_name: str
    description: str | None = None
    color: str
    workspace_id: int
    workspace_name: str
    updated_at: datetime | None = None


class SearchWorkspaceResult(BaseModel):
    """A workspace result returned by the unified search."""

    workspace_id: int
    workspace_name: str
    description: str | None = None
    workspace_type: str
    visibility: str
    member_role: str | None = None
    color: str | None = None
    updated_at: datetime | None = None


class SearchSharedFileResult(BaseModel):
    """A shared file result returned by the unified search."""

    share_id: int
    file_id: int
    file_name: str
    permission: str
    share_type: str
    shared_by: int
    workspace_name: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class UnifiedSearchResponse(BaseModel):
    """Top-level response for the unified search endpoint."""

    query: str
    workspaces: list[SearchWorkspaceResult] = []
    folders: list[SearchFolderResult] = []
    shared_files: list[SearchSharedFileResult] = []
