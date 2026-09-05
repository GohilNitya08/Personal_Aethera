"""SQLAlchemy data access for workspace join requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class JoinRequest:
    request_id: str
    workspace_id: int
    user_id: int
    status: str
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "JoinRequest":
        return cls(
            request_id=str(row["request_id"]),
            workspace_id=int(row["workspace_id"]),
            user_id=int(row["user_id"]),
            status=str(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class JoinRequestRepository:
    _COLUMNS = "request_id, workspace_id, user_id, status, created_at, updated_at"

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, request_id: str, workspace_id: int, user_id: int) -> bool:
        self._db.execute(
            text(
                """
                INSERT INTO workspace_join_requests (request_id, workspace_id, user_id)
                VALUES (:request_id, :workspace_id, :user_id)
                """
            ),
            {
                "request_id": request_id,
                "workspace_id": workspace_id,
                "user_id": user_id,
            },
        )
        return True

    def get_by_id(self, request_id: str) -> JoinRequest | None:
        row = (
            self._db.execute(
                text(
                    f"SELECT {self._COLUMNS} FROM workspace_join_requests "
                    "WHERE request_id = :request_id LIMIT 1"
                ),
                {"request_id": request_id},
            )
            .mappings()
            .first()
        )
        return JoinRequest.from_row(row) if row else None
        
    def get_by_user_and_workspace(self, user_id: int, workspace_id: int) -> JoinRequest | None:
        row = (
            self._db.execute(
                text(
                    f"SELECT {self._COLUMNS} FROM workspace_join_requests "
                    "WHERE user_id = :user_id AND workspace_id = :workspace_id LIMIT 1"
                ),
                {"user_id": user_id, "workspace_id": workspace_id},
            )
            .mappings()
            .first()
        )
        return JoinRequest.from_row(row) if row else None

    def list_by_workspace(self, workspace_id: int, status: str | None = None) -> list[JoinRequest]:
        query = f"SELECT {self._COLUMNS} FROM workspace_join_requests WHERE workspace_id = :workspace_id"
        params = {"workspace_id": workspace_id}
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC"
        
        rows = self._db.execute(text(query), params).mappings().all()
        return [JoinRequest.from_row(row) for row in rows]

    def update_status(self, request_id: str, status: str) -> bool:
        result = self._db.execute(
            text(
                """
                UPDATE workspace_join_requests 
                SET status = :status, updated_at = CURRENT_TIMESTAMP
                WHERE request_id = :request_id
                """
            ),
            {"request_id": request_id, "status": status},
        )
        return result.rowcount == 1

    def reopen_rejected(self, request_id: str) -> bool:
        """Reuse the unique request record when a rejected user applies again."""
        result = self._db.execute(
            text(
                """
                UPDATE workspace_join_requests
                SET status = 'PENDING', updated_at = CURRENT_TIMESTAMP
                WHERE request_id = :request_id AND status = 'REJECTED'
                """
            ),
            {"request_id": request_id},
        )
        return result.rowcount == 1
        
    def bulk_update_status(self, request_ids: list[str], status: str) -> int:
        if not request_ids:
            return 0
            
        placeholders = ", ".join(f":id_{i}" for i in range(len(request_ids)))
        params = {f"id_{i}": req_id for i, req_id in enumerate(request_ids)}
        params["status"] = status
        
        result = self._db.execute(
            text(
                f"""
                UPDATE workspace_join_requests 
                SET status = :status, updated_at = CURRENT_TIMESTAMP
                WHERE request_id IN ({placeholders})
                """
            ),
            params,
        )
        return result.rowcount

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()
