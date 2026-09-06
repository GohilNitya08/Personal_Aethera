"""Private object-storage integration for uploaded file contents."""

from __future__ import annotations

from datetime import timedelta
from io import BufferedIOBase
from typing import Protocol

from app.core.config import settings


class StorageNotConfiguredError(Exception):
    """Raised when private cloud storage is not configured."""


class StorageUploadError(Exception):
    """Raised when an object cannot be uploaded or removed."""


class StorageDownloadError(Exception):
    """Raised when temporary access to a private object cannot be created."""


class ObjectStorage(Protocol):
    """Minimal provider-neutral contract for private file objects.

    Providers remain responsible for keeping objects private; callers only receive
    a time-limited download URL after authorization has completed.
    """

    def upload(self, stream: BufferedIOBase, object_key: str, content_type: str | None) -> str: ...

    def delete(self, object_key: str) -> None: ...

    def temporary_download_url(self, object_key: str) -> str: ...


class S3StorageService:
    """Upload and remove private objects using AWS S3."""

    def __init__(self, bucket_name: str | None = None) -> None:
        self._bucket_name = bucket_name or settings.s3_bucket_name
        self._client = None

    def upload(self, stream: BufferedIOBase, object_key: str, content_type: str | None) -> str:
        if not self._bucket_name:
            raise StorageNotConfiguredError("Private cloud storage is not configured")
        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError

            if self._client is None:
                self._client = boto3.client("s3")
            
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
                
            self._client.upload_fileobj(stream, self._bucket_name, object_key, ExtraArgs=extra_args)
            return object_key
        except StorageNotConfiguredError:
            raise
        except Exception as error:
            raise StorageUploadError("Cloud upload failed") from error

    def delete(self, object_key: str) -> None:
        if not self._bucket_name or self._client is None:
            return
        try:
            self._client.delete_object(Bucket=self._bucket_name, Key=object_key)
        except Exception as error:
            raise StorageUploadError("Cloud cleanup failed") from error

    def temporary_download_url(self, object_key: str) -> str:
        """Create short-lived private S3 access without making the object public."""
        if not self._bucket_name:
            raise StorageNotConfiguredError("Private cloud storage is not configured")
        try:
            import boto3

            if self._client is None:
                self._client = boto3.client("s3")
            
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket_name, "Key": object_key},
                ExpiresIn=settings.s3_signed_url_expire_minutes * 60,
            )
        except StorageNotConfiguredError:
            raise
        except Exception as error:
            raise StorageDownloadError("Temporary download access could not be created") from error


def get_storage_service() -> ObjectStorage:
    """FastAPI dependency providing the configured object-storage service."""
    return S3StorageService()

