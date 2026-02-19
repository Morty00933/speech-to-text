"""
S3/MinIO storage client for Speech-to-Text Pipeline.
Handles audio file uploads and result storage.
"""
import os
import io
from typing import Optional, BinaryIO
from minio import Minio
from minio.error import S3Error
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings
from .logging_config import get_logger

logger = get_logger("storage")


class StorageClient:
    """MinIO/S3 storage client with retry logic."""

    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Create bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"Failed to create bucket: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    def upload_file(
        self,
        file_path: str,
        object_name: str,
        content_type: str = "audio/mpeg"
    ) -> str:
        """
        Upload a file to storage.

        Args:
            file_path: Local file path
            object_name: Object name in storage
            content_type: MIME type of the file

        Returns:
            Object URL
        """
        try:
            self.client.fput_object(
                self.bucket,
                object_name,
                file_path,
                content_type=content_type,
            )
            logger.info(f"Uploaded file: {object_name}")
            return f"{self.bucket}/{object_name}"
        except S3Error as e:
            logger.error(f"Failed to upload file: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    def upload_bytes(
        self,
        data: bytes,
        object_name: str,
        content_type: str = "audio/mpeg"
    ) -> str:
        """
        Upload bytes data to storage.

        Args:
            data: Bytes data
            object_name: Object name in storage
            content_type: MIME type

        Returns:
            Object URL
        """
        try:
            data_stream = io.BytesIO(data)
            self.client.put_object(
                self.bucket,
                object_name,
                data_stream,
                length=len(data),
                content_type=content_type,
            )
            logger.info(f"Uploaded bytes: {object_name}")
            return f"{self.bucket}/{object_name}"
        except S3Error as e:
            logger.error(f"Failed to upload bytes: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    def download_file(self, object_name: str, file_path: str) -> str:
        """
        Download a file from storage.

        Args:
            object_name: Object name in storage
            file_path: Local file path to save

        Returns:
            Local file path
        """
        try:
            self.client.fget_object(self.bucket, object_name, file_path)
            logger.info(f"Downloaded file: {object_name} -> {file_path}")
            return file_path
        except S3Error as e:
            logger.error(f"Failed to download file: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    def get_file_bytes(self, object_name: str) -> bytes:
        """
        Get file content as bytes.

        Args:
            object_name: Object name in storage

        Returns:
            File content as bytes
        """
        try:
            response = self.client.get_object(self.bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Failed to get file bytes: {e}")
            raise

    def delete_file(self, object_name: str) -> bool:
        """
        Delete a file from storage.

        Args:
            object_name: Object name in storage

        Returns:
            True if deleted successfully
        """
        try:
            self.client.remove_object(self.bucket, object_name)
            logger.info(f"Deleted file: {object_name}")
            return True
        except S3Error as e:
            logger.error(f"Failed to delete file: {e}")
            return False

    def file_exists(self, object_name: str) -> bool:
        """Check if file exists in storage."""
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False

    def get_presigned_url(
        self,
        object_name: str,
        expires_hours: int = 24
    ) -> str:
        """
        Get presigned URL for file download.

        Args:
            object_name: Object name in storage
            expires_hours: URL expiration time in hours

        Returns:
            Presigned URL
        """
        from datetime import timedelta
        try:
            url = self.client.presigned_get_object(
                self.bucket,
                object_name,
                expires=timedelta(hours=expires_hours),
            )
            return url
        except S3Error as e:
            logger.error(f"Failed to get presigned URL: {e}")
            raise


# Singleton instance
_storage_client: Optional[StorageClient] = None


def get_storage() -> StorageClient:
    """Get storage client singleton."""
    global _storage_client
    if _storage_client is None:
        _storage_client = StorageClient()
    return _storage_client
