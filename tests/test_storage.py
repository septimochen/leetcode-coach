from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from leetcode_coach.storage import (
    LocalObjectStorage,
    ObjectNotFound,
    S3ObjectStorage,
)


def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    storage.write_text("data/plans/2026-09-14.md", "# Plan\n")

    assert storage.read_text("data/plans/2026-09-14.md") == "# Plan\n"
    assert storage.location("data/plans/2026-09-14.md") == str(
        tmp_path / "data/plans/2026-09-14.md"
    )


def test_local_missing_object_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(ObjectNotFound):
        LocalObjectStorage(tmp_path).read_text("missing.json")


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        try:
            body = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        except KeyError as error:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            ) from error
        return {"Body": SimpleNamespace(read=lambda: body)}


def test_s3_storage_uses_prefixed_keys_and_round_trips() -> None:
    client = FakeS3()
    storage = S3ObjectStorage(
        endpoint_url="https://example.r2.cloudflarestorage.com",
        bucket="coach",
        access_key_id="access",
        secret_access_key="secret",
        prefix="private/",
        client=client,
    )

    storage.write_text(Path("data/progress.json"), '{"solved": []}')

    assert client.objects[("coach", "private/data/progress.json")] == b'{"solved": []}'
    assert storage.read_text("data/progress.json") == '{"solved": []}'
    assert storage.location("data/progress.json") == "s3://coach/private/data/progress.json"


def test_s3_missing_object_is_explicit() -> None:
    storage = S3ObjectStorage(
        endpoint_url="https://example.r2.cloudflarestorage.com",
        bucket="coach",
        access_key_id="access",
        secret_access_key="secret",
        client=FakeS3(),
    )

    with pytest.raises(ObjectNotFound):
        storage.read_text("progress.json")
