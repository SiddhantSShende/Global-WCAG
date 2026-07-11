"""Artifact storage abstraction.

Two backends behind one interface so the pipeline code never branches:
  • S3Storage    — MinIO / Garage / AWS S3 (production, and docker-compose dev).
  • LocalStorage — plain filesystem under artifacts_dir (offline dev / CI /
                   `scripts/run_local_scan.py` without Docker).

Backend is chosen by the A11Y_STORAGE env var ('s3' default, or 'local'), so a
developer can run the whole scan with no object store.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import settings


class LocalStorage:
    scheme = "local"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._path(key).write_bytes(data)
        return key

    def put_file(self, key: str, src: str | Path, content_type: str = "application/octet-stream") -> str:
        dst = self._path(key)
        src = Path(src)
        # The pipeline often writes a report straight to its storage location;
        # copying a file onto itself raises SameFileError — treat as a no-op.
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def download(self, key: str, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), dest)
        return dest

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def url(self, key: str) -> str:
        return self._path(key).as_uri()


class S3Storage:
    scheme = "s3"

    def __init__(self):
        import boto3  # imported lazily so LocalStorage needs no boto3

        self.bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self._client.create_bucket(Bucket=self.bucket)
            except Exception:
                pass  # bucket may be created out-of-band (docker createbucket)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def put_file(self, key: str, src: str | Path, content_type: str = "application/octet-stream") -> str:
        self._client.upload_file(str(src), self.bucket, key, ExtraArgs={"ContentType": content_type})
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def download(self, key: str, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self.bucket, key, str(dest))
        return dest

    def local_path(self, key: str) -> Path:
        """Download to a temp path so report builders can embed by filesystem path."""
        dest = settings.artifacts_dir / "_cache" / key
        return self.download(key, dest)

    def url(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600
        )


def _make_storage():
    if os.getenv("A11Y_STORAGE", "s3").lower() == "local":
        return LocalStorage(settings.artifacts_dir)
    try:
        return S3Storage()
    except Exception as exc:  # noqa: BLE001 — degrade to local if S3 unavailable
        print(f"[storage] S3 unavailable ({exc}); falling back to local filesystem.")
        return LocalStorage(settings.artifacts_dir)


storage = _make_storage()
