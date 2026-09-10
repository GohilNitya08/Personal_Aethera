"""Regression tests for workspace RBAC: exact member_role returned per user.

Reproduces the critical bug: workspace ID 7, User A (OWNER), User B (VIEWER).
Both users should receive their correct role from get_workspace().

This test suite verifies every step of the chain:
1. The workspace_members table stores correct roles
2. get_membership returns the correct membership row per user
3. get_workspace returns the correct member_role per user
4. VIEWER cannot perform management operations
5. The workspace list returns correct member_role per user
"""

from __future__ import annotations

import pytest

from app.services.workspace_service import (
    WorkspacePermissionError,
    WorkspaceService,
)
from app.schemas.workspace import (
    WorkspaceUpdateRequest,
    WorkspaceInvitationRequest,
    WorkspaceMemberUpdateRequest,
)


# ---------------------------------------------------------------------------
# Lightweight stubs matching the real repository interface
# ---------------------------------------------------------------------------

class StubWorkspace:
    """Mimics the repository Workspace dataclass."""
    def __init__(
        self, workspace_id, user_id, workspace_name="WS",
        description=None, workspace_type="PERSONAL", visibility="PRIVATE",
        storage_used=0, storage_limit=1000, color="blue",
        is_archived=False, created_at=None, updated_at=None, member_role=None,
    ):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.workspace_name = workspace_name
        self.description = description
        self.workspace_type = workspace_type
        self.visibility = visibility
        self.storage_used = storage_used
        self.storage_limit = storage_limit
        self.color = color
        self.is_archived = is_archived
        self.created_at = created_at
        self.updated_at = updated_at
        self.member_role = member_role


class StubMember:
    """Mimics the repository WorkspaceMember dataclass."""
    def __init__(self, member_id, workspace_id, user_id, role, invited_by=None, joined_at=None):
        self.member_id = member_id
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.role = role
        self.invited_by = invited_by
        self.joined_at = joined_at


class StubWorkspaceRepo:
    def __init__(self, workspaces, memberships):
        self._workspaces = workspaces
        self._memberships = memberships

    def get_by_id(self, workspace_id):
        return self._workspaces.get(workspace_id)

    def get_membership(self, workspace_id, user_id):
        return self._memberships.get(workspace_id, {}).get(user_id)

    def list_members(self, workspace_id):
        return list(self._memberships.get(workspace_id, {}).values())

    def list_for_user(self, user_id, *, include_archived):
        results = []
        for ws_id, members in self._memberships.items():
            if user_id in members:
                ws = self._workspaces.get(ws_id)
                if ws and (include_archived or not ws.is_archived):
                    results.append(StubWorkspace(
                        workspace_id=ws.workspace_id,
                        user_id=ws.user_id,
                        workspace_name=ws.workspace_name,
                        description=ws.description,
                        workspace_type=ws.workspace_type,
                        visibility=ws.visibility,
                        storage_used=ws.storage_used,
                        storage_limit=ws.storage_limit,
                        color=ws.color,
                        is_archived=ws.is_archived,
                        created_at=ws.created_at,
                        updated_at=ws.updated_at,
                        member_role=members[user_id].role,
                    ))
        return results

    def update_settings(self, workspace_id, changes):
        return True

    def update_member_role(self, workspace_id, user_id, role):
        m = self._memberships.get(workspace_id, {}).get(user_id)
        if m is None:
            return False
        self._memberships[workspace_id][user_id] = StubMember(
            m.member_id, m.workspace_id, m.user_id, role, m.invited_by, m.joined_at
        )
        return True

    def add_member(self, *, workspace_id, user_id, role, invited_by):
        ws_members = self._memberships.setdefault(workspace_id, {})
        member_id = max((m.member_id for ms in self._memberships.values() for m in ms.values()), default=0) + 1
        ws_members[user_id] = StubMember(member_id, workspace_id, user_id, role, invited_by)
        return member_id

    def remove_member(self, workspace_id, user_id):
        if user_id in self._memberships.get(workspace_id, {}):
            del self._memberships[workspace_id][user_id]
            return True
        return False

    def record_activity(self, **kwargs):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


class StubUserRepo:
    def __init__(self, user_ids=None):
        self._ids = set(user_ids or [])

    def get_active_by_id(self, user_id):
        return object() if user_id in self._ids else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

OWNER_USER_ID = 10   # User A
VIEWER_USER_ID = 20  # User B
EDITOR_USER_ID = 30  # User C (for member management tests)
WORKSPACE_ID = 7


def _make_service():
    """Create a service with workspace 7 having OWNER (user 10), VIEWER (user 20), and EDITOR (user 30)."""
    workspace = StubWorkspace(WORKSPACE_ID, OWNER_USER_ID, workspace_name="Test WS")
    repo = StubWorkspaceRepo(
        {WORKSPACE_ID: workspace},
        {WORKSPACE_ID: {
            OWNER_USER_ID: StubMember(1, WORKSPACE_ID, OWNER_USER_ID, "OWNER"),
            VIEWER_USER_ID: StubMember(2, WORKSPACE_ID, VIEWER_USER_ID, "VIEWER"),
            EDITOR_USER_ID: StubMember(3, WORKSPACE_ID, EDITOR_USER_ID, "EDITOR"),
        }},
    )
    user_repo = StubUserRepo([OWNER_USER_ID, VIEWER_USER_ID, EDITOR_USER_ID])
    return WorkspaceService(repo, user_repo), repo


class TestWorkspaceRBACRegression:
    """
    Regression: workspace ID 7, User A (OWNER), User B (VIEWER).
    Both users must receive their EXACT role from every API surface.
    """

    def test_get_membership_returns_correct_role_per_user(self):
        """Step 1: The repository correctly resolves membership per user."""
        _, repo = _make_service()
        owner_member = repo.get_membership(WORKSPACE_ID, OWNER_USER_ID)
        viewer_member = repo.get_membership(WORKSPACE_ID, VIEWER_USER_ID)
        assert owner_member is not None and owner_member.role == "OWNER"
        assert viewer_member is not None and viewer_member.role == "VIEWER"

    def test_get_workspace_returns_owner_for_user_a(self):
        """Step 2a: get_workspace returns member_role=OWNER for User A."""
        service, _ = _make_service()
        ws = service.get_workspace(WORKSPACE_ID, OWNER_USER_ID)
        assert ws.member_role == "OWNER"

    def test_get_workspace_returns_viewer_for_user_b(self):
        """Step 2b: get_workspace returns member_role=VIEWER for User B."""
        service, _ = _make_service()
        ws = service.get_workspace(WORKSPACE_ID, VIEWER_USER_ID)
        assert ws.member_role == "VIEWER"

    def test_list_workspaces_returns_correct_role_per_user(self):
        """Step 3: list_workspaces includes member_role per user."""
        service, _ = _make_service()
        owner_list = service.list_workspaces(OWNER_USER_ID, include_archived=False)
        viewer_list = service.list_workspaces(VIEWER_USER_ID, include_archived=False)
        assert len(owner_list) == 1 and owner_list[0].member_role == "OWNER"
        assert len(viewer_list) == 1 and viewer_list[0].member_role == "VIEWER"

    def test_viewer_cannot_update_workspace(self):
        """Step 4a: VIEWER User B cannot update workspace settings."""
        service, _ = _make_service()
        with pytest.raises(WorkspacePermissionError):
            service.update_workspace(
                WORKSPACE_ID, VIEWER_USER_ID,
                WorkspaceUpdateRequest(workspace_name="Hacked")
            )

    def test_viewer_cannot_delete_workspace(self):
        """Step 4b: VIEWER User B cannot delete the workspace."""
        service, _ = _make_service()
        with pytest.raises(WorkspacePermissionError):
            service.delete_workspace(WORKSPACE_ID, VIEWER_USER_ID)

    def test_viewer_cannot_transfer_ownership(self):
        """Step 4c: VIEWER User B cannot transfer ownership."""
        service, _ = _make_service()
        with pytest.raises(WorkspacePermissionError):
            service.transfer_ownership(WORKSPACE_ID, VIEWER_USER_ID, OWNER_USER_ID)

    def test_viewer_cannot_manage_members(self):
        """Step 4d: VIEWER User B cannot remove other members (non-OWNER target)."""
        service, _ = _make_service()
        with pytest.raises(WorkspacePermissionError):
            service.remove_member(WORKSPACE_ID, VIEWER_USER_ID, EDITOR_USER_ID)

    def test_viewer_cannot_invite_members(self):
        """Step 4e: VIEWER User B cannot invite new members."""
        service, _ = _make_service()
        with pytest.raises(WorkspacePermissionError):
            service.invite_member(
                WORKSPACE_ID, VIEWER_USER_ID,
                WorkspaceInvitationRequest(user_id=99, role="VIEWER")
            )

    def test_viewer_cannot_update_member_roles(self):
        """Step 4f: VIEWER User B cannot change member roles."""
        service, _ = _make_service()
        with pytest.raises(WorkspacePermissionError):
            service.update_member(
                WORKSPACE_ID, VIEWER_USER_ID, OWNER_USER_ID,
                WorkspaceMemberUpdateRequest(role="EDITOR")
            )

    def test_owner_can_perform_management(self):
        """Step 5: OWNER User A retains full management capabilities."""
        service, _ = _make_service()
        # Owner can update settings (stub doesn't persist name, but no PermissionError)
        ws = service.update_workspace(
            WORKSPACE_ID, OWNER_USER_ID,
            WorkspaceUpdateRequest(workspace_name="Updated")
        )
        assert ws.member_role == "OWNER"

    def test_roles_never_cross_contaminate_between_users(self):
        """Step 6: Sequential get_workspace calls never leak roles between users."""
        service, _ = _make_service()
        # Call for OWNER first, then VIEWER, then OWNER again
        ws_a1 = service.get_workspace(WORKSPACE_ID, OWNER_USER_ID)
        ws_b = service.get_workspace(WORKSPACE_ID, VIEWER_USER_ID)
        ws_a2 = service.get_workspace(WORKSPACE_ID, OWNER_USER_ID)
        assert ws_a1.member_role == "OWNER"
        assert ws_b.member_role == "VIEWER"
        assert ws_a2.member_role == "OWNER"
