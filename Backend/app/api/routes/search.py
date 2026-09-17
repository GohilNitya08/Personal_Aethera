"""JWT-protected unified search endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.users import get_current_auth_user
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.schemas.search import (
    SearchFolderResult,
    SearchSharedFileResult,
    SearchWorkspaceResult,
    UnifiedSearchResponse,
)

router = APIRouter(prefix="/search", tags=["search"])

_MAX_RESULTS_PER_CATEGORY = 25


@router.get("", response_model=UnifiedSearchResponse, summary="Unified search")
def unified_search(
    q: Annotated[str, Query(min_length=1)],
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UnifiedSearchResponse:
    """Search across workspaces, folders, and shared files.

    Authorization is enforced per category:
    - Workspaces: user's own member workspaces + discoverable non-PERSONAL workspaces
    - Folders: non-archived folders in workspaces where user is a member
    - Shared files: active shares where the user is the recipient

    PERSONAL workspaces are never exposed to non-owners.
    """
    query = q.strip()
    if not query:
        return UnifiedSearchResponse(query=q)

    pattern = f"%{query}%"
    user_id = current_user.user_id
    params = {"user_id": user_id, "pattern": pattern, "limit": _MAX_RESULTS_PER_CATEGORY}

    workspaces = _search_workspaces(db, params)
    folders = _search_folders(db, params)
    shared_files = _search_shared_files(db, params)

    return UnifiedSearchResponse(
        query=q,
        workspaces=workspaces,
        folders=folders,
        shared_files=shared_files,
    )


def _search_workspaces(
    db: Session, params: dict,
) -> list[SearchWorkspaceResult]:
    """Discover workspaces the user can access or that are publicly discoverable.

    Rules:
    - The user's own member workspaces always appear (any type).
    - Non-member workspaces appear ONLY if they are NOT PERSONAL (i.e. INSTITUTION)
      and have PUBLIC visibility, so the user can discover and request to join them.
    - PERSONAL workspaces are NEVER exposed to non-owners/non-members.
    - GROUP BY ensures each workspace appears at most once.
    """
    rows = (
        db.execute(
            text(
                """
                SELECT w.workspace_id, w.workspace_name, w.description,
                       w.workspace_type, w.visibility, w.color, w.updated_at,
                       MAX(wm.role) AS member_role
                FROM workspaces AS w
                LEFT JOIN workspace_members AS wm
                  ON wm.workspace_id = w.workspace_id AND wm.user_id = :user_id
                WHERE w.is_archived = FALSE
                  AND (w.workspace_name LIKE :pattern
                       OR w.description LIKE :pattern
                       OR CAST(w.workspace_id AS CHAR) LIKE :pattern)
                  AND (
                      wm.user_id IS NOT NULL
                      OR (w.workspace_type != 'PERSONAL' AND w.visibility = 'PUBLIC')
                  )
                GROUP BY w.workspace_id
                ORDER BY w.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [
        SearchWorkspaceResult(
            workspace_id=row["workspace_id"],
            workspace_name=row["workspace_name"],
            description=row["description"],
            workspace_type=row["workspace_type"],
            visibility=row["visibility"],
            member_role=row["member_role"],
            color=row["color"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def _search_folders(
    db: Session, params: dict,
) -> list[SearchFolderResult]:
    """Search non-archived folders in workspaces the user can access."""
    rows = (
        db.execute(
            text(
                """
                SELECT fo.folder_id, fo.folder_name, fo.description, fo.color,
                       w.workspace_id, w.workspace_name, fo.updated_at
                FROM folders AS fo
                JOIN workspaces AS w ON w.workspace_id = fo.workspace_id
                WHERE fo.is_archived = FALSE
                  AND w.is_archived = FALSE
                  AND fo.folder_name LIKE :pattern
                  AND (
                      w.visibility = 'PUBLIC'
                      OR EXISTS (
                          SELECT 1 FROM workspace_members AS wm
                          WHERE wm.workspace_id = w.workspace_id
                            AND wm.user_id = :user_id
                      )
                  )
                ORDER BY fo.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [
        SearchFolderResult(
            folder_id=row["folder_id"],
            folder_name=row["folder_name"],
            description=row["description"],
            color=row["color"],
            workspace_id=row["workspace_id"],
            workspace_name=row["workspace_name"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def _search_shared_files(
    db: Session, params: dict,
) -> list[SearchSharedFileResult]:
    """Search active shares where the user is the recipient."""
    rows = (
        db.execute(
            text(
                """
                SELECT s.share_id, s.file_id, f.file_name, s.permission,
                       s.share_type, s.shared_by, w.workspace_name,
                       s.expires_at, s.created_at
                FROM file_shares AS s
                JOIN files AS f ON f.file_id = s.file_id
                JOIN folders AS fo ON fo.folder_id = f.folder_id
                JOIN workspaces AS w ON w.workspace_id = fo.workspace_id
                WHERE s.shared_with = :user_id
                  AND f.is_deleted = FALSE
                  AND f.file_name LIKE :pattern
                  AND (s.expires_at IS NULL OR s.expires_at > UTC_TIMESTAMP())
                ORDER BY s.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [
        SearchSharedFileResult(
            share_id=row["share_id"],
            file_id=row["file_id"],
            file_name=row["file_name"],
            permission=row["permission"],
            share_type=row["share_type"],
            shared_by=row["shared_by"],
            workspace_name=row["workspace_name"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
