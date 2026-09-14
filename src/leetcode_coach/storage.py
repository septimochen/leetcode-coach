"""Durable object storage with a local filesystem and S3-compatible backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import boto3
from botocore.exceptions import ClientError

from .log import get_logger
from .settings import Settings

logger = get_logger(__name__)


class ObjectNotFound(FileNotFoundError):
    """Raised when an object does not exist in the selected storage backend."""


class ObjectStorage(Protocol):
    def read_text(self, key: str | Path) -> str: ...

    def write_text(self, key: str | Path, content: str) -> None: ...

    def location(self, key: str | Path) -> str: ...


class LocalObjectStorage:
    """Store objects beneath a local directory, preserving existing CLI behavior."""

    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root)

    def _path(self, key: str | Path) -> Path:
        path = Path(key)
        return path if path.is_absolute() else self.root / path

    def read_text(self, key: str | Path) -> str:
        path = self._path(key)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ObjectNotFound(str(path)) from error

    def write_text(self, key: str | Path, content: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def location(self, key: str | Path) -> str:
        return str(self._path(key))


class S3ObjectStorage:
    """Store objects through an S3-compatible API such as Cloudflare R2."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str = "",
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name="auto",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _key(self, key: str | Path) -> str:
        object_key = str(key).replace("\\", "/").strip("/")
        return f"{self.prefix}/{object_key}" if self.prefix else object_key

    def read_text(self, key: str | Path) -> str:
        object_key = self._key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectNotFound(self.location(key)) from error
            raise
        return response["Body"].read().decode("utf-8")

    def write_text(self, key: str | Path, content: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )

    def location(self, key: str | Path) -> str:
        return f"s3://{self.bucket}/{self._key(key)}"


def create_storage(settings: Settings) -> ObjectStorage:
    """Build the configured backend without exposing credentials in logs."""
    if settings.storage_backend == "local":
        return LocalObjectStorage()
    assert settings.s3_endpoint_url is not None
    assert settings.s3_bucket is not None
    assert settings.s3_access_key_id is not None
    assert settings.s3_secret_access_key is not None
    logger.info(
        "Using S3-compatible storage (bucket=%s, prefix=%s)",
        settings.s3_bucket,
        settings.s3_prefix or "(none)",
    )
    return S3ObjectStorage(
        endpoint_url=settings.s3_endpoint_url,
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id.get_secret_value(),
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        prefix=settings.s3_prefix,
    )
