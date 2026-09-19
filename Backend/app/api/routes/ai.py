"""Talk with Document — JWT-protected AI chat endpoint."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.api.routes.files import get_file_service
from app.api.routes.users import get_current_auth_user
from app.database.session import get_db
from app.repositories.auth_repository import AuthUser
from app.repositories.file_repository import FileRepository
from app.services.file_service import (
    FileNotFoundError,
    FilePermissionError,
    FileService,
)
from app.services.storage_service import (
    S3StorageService,
    StorageDownloadError,
    StorageNotConfiguredError,
)
from app.services.ai_service import (
    AIServiceError,
    BedrockError,
    ContextTooLargeError,
    DocumentExtractionError,
    SUPPORTED_MIME_TYPES,
    UnsupportedDocumentError,
    chat_with_document,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])

FileId = Annotated[int, Path(gt=0)]


class ChatRequest(BaseModel):
    """User message for document-scoped AI chat."""
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]


class ChatResponse(BaseModel):
    """AI answer scoped to the requested document."""
    answer: str
    file_id: int
    file_name: str


@router.post(
    "/files/{file_id}/chat",
    response_model=ChatResponse,
    summary="Talk with Document — ask the AI about a specific file",
)
def chat_with_file(
    file_id: FileId,
    payload: ChatRequest,
    current_user: Annotated[AuthUser, Depends(get_current_auth_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> ChatResponse:
    """Authenticate, authorize, extract, and invoke Bedrock for a document question.

    Authorization is fully delegated to the existing FileService.get_file() which
    verifies workspace membership, folder access, and non-deleted status.
    """
    # 1. Authorize — reuse existing RBAC (raises 404/403 on failure)
    try:
        file = service.get_file(file_id, current_user.user_id)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        ) from error
    except FilePermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this file",
        ) from error

    # 2. Check supported type early
    mime = (file.mime_type or "").lower().strip()
    is_pdf_by_ext = (file.file_extension or "").lower() in ("pdf",)
    if mime not in SUPPORTED_MIME_TYPES and not is_pdf_by_ext:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"This file type ({mime or file.file_extension or 'unknown'}) "
                "is not yet supported for AI analysis. "
                "Supported types include PDF and text-based documents."
            ),
        )

    # 3. Download document bytes from S3
    storage = S3StorageService()
    try:
        raw_bytes = storage.download_bytes(file.storage_path)
    except StorageNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloud storage is not configured",
        ) from error
    except StorageDownloadError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not retrieve the document from storage",
        ) from error

    # 4. Extract text, invoke Bedrock, return answer
    effective_mime = mime if mime in SUPPORTED_MIME_TYPES else (
        "application/pdf" if is_pdf_by_ext else mime
    )
    try:
        answer = chat_with_document(
            raw_bytes=raw_bytes,
            mime_type=effective_mime,
            file_name=file.file_name,
            user_message=payload.message,
        )
    except UnsupportedDocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except DocumentExtractionError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except ContextTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(error),
        ) from error
    except BedrockError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
    except AIServiceError as error:
        logger.error("AI service error for file %s: %s", file_id, error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your request",
        ) from error

    # 5. Log activity (non-blocking — uses existing activity_logs table)
    try:
        from app.database.session import SessionLocal
        db = SessionLocal()
        try:
            repo = FileRepository(db)
            repo.record_activity(
                user_id=current_user.user_id,
                file_id=file_id,
                activity_type="AI_CHAT",
                detail=f"AI query on '{file.file_name}'",
            )
            repo.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("Activity logging for AI chat failed (non-critical)", exc_info=True)

    return ChatResponse(
        answer=answer,
        file_id=file.file_id,
        file_name=file.file_name,
    )
