"""Private object-storage integration for uploaded file contents."""

from __future__ import annotations

from io import BufferedIOBase

from app.core.config import settings


class StorageNotConfiguredError(Exception):
    """Raised when private cloud storage is not configured."""


class StorageUploadError(Exception):
    """Raised when an object cannot be uploaded or removed."""


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
