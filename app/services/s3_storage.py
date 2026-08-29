"""Private S3 object access for the production API.

All browser data-plane URLs are short lived. Stable database values remain
opaque S3 keys and same-origin API URLs, so ownership is checked before each
read or delete operation.
"""
from __future__ import annotations

import base64
from pathlib import PurePosixPath
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.config import Settings


class S3Storage:
    def __init__(self, settings: Settings, client: Any | None = None):
        if not settings.aws_media_bucket:
            raise ValueError("PACIFICBIO_AWS_MEDIA_BUCKET is required for S3 storage")
        self.bucket = settings.aws_media_bucket
        self.client = client or boto3.client("s3", region_name=settings.aws_region)

    @staticmethod
    def object_key(owner_sub: str, media_id: str, filename: str) -> str:
        suffix = PurePosixPath(filename).suffix.lower()[:12]
        return f"raw/{owner_sub}/{media_id}/source{suffix}"

    def upload_url(self, key: str, content_type: str, checksum_hex: str | None = None) -> str:
        # Browser-originated source files must be checksum-bound. A thumbnail
        # does not exist until the trusted Function Compute worker creates it, so its
        # internal one-time PUT deliberately has no source-file checksum.
        params = {"Bucket": self.bucket, "Key": key, "ContentType": content_type}
        if checksum_hex:
            checksum_b64 = base64.b64encode(bytes.fromhex(checksum_hex)).decode("ascii")
            params.update({"ChecksumSHA256": checksum_b64, "Metadata": {"sha256": checksum_hex}})
        return self.client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=900,
            HttpMethod="PUT",
        )

    def download_url(self, key: str, expires_seconds: int = 300) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_seconds)

    def upload_file(self, key: str, path: str, content_type: str) -> None:
        self.client.upload_file(path, self.bucket, key, ExtraArgs={"ContentType": content_type})

    def object_exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def checksum_matches(self, key: str, checksum_hex: str) -> bool:
        """Return true only for an S3-validated SHA-256 checksum."""
        expected = base64.b64encode(bytes.fromhex(checksum_hex)).decode("ascii")
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return response.get("ChecksumSHA256") == expected

    def delete(self, keys: list[str]) -> None:
        objects = [{"Key": key} for key in keys if key]
        if objects:
            response = self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True})
            if response.get("Errors"):
                failures = ", ".join(error.get("Key", "unknown") for error in response["Errors"])
                raise RuntimeError(f"S3 deletion failed for: {failures}")
