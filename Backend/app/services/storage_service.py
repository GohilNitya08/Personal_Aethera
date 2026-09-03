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


class CloudStorageService:
    """Upload and remove private objects using Google Cloud Storage."""

    def __init__(self, bucket_name: str | None = None) -> None:
        self._bucket_name = bucket_name or settings.gcs_bucket_name
        self._client = None

    def upload(self, stream: BufferedIOBase, object_key: str, content_type: str | None) -> str:
        if not self._bucket_name:
            raise StorageNotConfiguredError("Private cloud storage is not configured")
        try:
            from google.cloud import storage

            if self._client is None:
                self._client = storage.Client()
            blob = self._client.bucket(self._bucket_name).blob(object_key)
            blob.upload_from_file(stream, rewind=False, content_type=content_type)
            return object_key
        except StorageNotConfiguredError:
            raise
        except Exception as error:
            raise StorageUploadError("Cloud upload failed") from error

    def delete(self, object_key: str) -> None:
        if not self._bucket_name or self._client is None:
            return
        try:
            self._client.bucket(self._bucket_name).blob(object_key).delete()
        except Exception as error:
            raise StorageUploadError("Cloud cleanup failed") from error

    def temporary_download_url(self, object_key: str) -> str:
        """Create short-lived private GCS access without making the object public."""
        if not self._bucket_name:
            raise StorageNotConfiguredError("Private cloud storage is not configured")
        try:
            from google.cloud import storage

            if self._client is None:
                self._client = storage.Client()
            blob = self._client.bucket(self._bucket_name).blob(object_key)
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=settings.gcs_signed_url_expire_minutes),
                method="GET",
            )
        except StorageNotConfiguredError:
            raise
        except Exception as error:
            raise StorageDownloadError("Temporary download access could not be created") from error
