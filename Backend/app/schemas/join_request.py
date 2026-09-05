from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


JoinRequestStatus = Literal["PENDING", "APPROVED", "REJECTED"]


class JoinRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: int = Field(gt=0)


class JoinRequestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: JoinRequestStatus


class JoinRequestResponse(BaseModel):
    request_id: str
    workspace_id: int
    user_id: int
    status: JoinRequestStatus
    created_at: datetime | None
    updated_at: datetime | None

class BulkApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_ids: list[str] = Field(min_length=1)
