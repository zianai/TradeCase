"""Content-addressed objects. Callers authorize tenant references before reads.

Objects never contain access permissions. Identical content may share an object,
so retention deletion must first prove there are no remaining database refs.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tradecase.util import no_symlinks

MAX_OBJECT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ObjectRef:
    key: str
    sha256: str
    size_bytes: int


class ObjectStorage(Protocol):
    def put(self, data: bytes) -> ObjectRef: ...
    def get(self, key: str) -> bytes: ...
    def verify(self, key: str, sha256: str | None = None) -> bool: ...
    def delete(self, key: str) -> None: ...


def _digest_from_key(key: str) -> str:
    if not re.fullmatch(r"sha256/[a-f0-9]{2}/[a-f0-9]{64}", key):
        raise ValueError("invalid object key")
    digest = key.rsplit("/", 1)[1]
    if key.split("/")[1] != digest[:2]:
        raise ValueError("object key prefix mismatch")
    return digest


def _reference(data: bytes) -> ObjectRef:
    if not isinstance(data, bytes) or len(data) > MAX_OBJECT_BYTES:
        raise ValueError("object must be bytes and no larger than 20 MiB")
    digest = hashlib.sha256(data).hexdigest()
    return ObjectRef(f"sha256/{digest[:2]}/{digest}", digest, len(data))


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).absolute()
        no_symlinks(self.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        _digest_from_key(key)
        path = self.root / key
        no_symlinks(path)
        return path

    def put(self, data: bytes) -> ObjectRef:
        ref = _reference(data)
        path = self._path(ref.key)
        if path.exists():
            if not self.verify(ref.key, ref.sha256):
                raise ValueError("existing object failed integrity check")
            return ref
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        no_symlinks(path)
        fd, temporary = tempfile.mkstemp(prefix=".object-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Hard link is atomic and refuses to replace an object another writer
            # installed. Only verified identical bytes can share a content key.
            try:
                os.link(temporary, path)
            except FileExistsError:
                if not self.verify(ref.key, ref.sha256):
                    raise ValueError("concurrent object failed integrity check") from None
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return ref

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if path.stat().st_size > MAX_OBJECT_BYTES:
            raise ValueError("stored object exceeds limit")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != _digest_from_key(key):
            raise ValueError("object integrity mismatch")
        return data

    def verify(self, key: str, sha256: str | None = None) -> bool:
        try:
            data = self.get(key)
        except (OSError, ValueError):
            return False
        return sha256 is None or hashlib.sha256(data).hexdigest() == sha256

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Storage:
    """Replaceable S3-compatible backend with injected boto3 client for offline tests.

    A live deployment configures bucket policy, encryption and retention. This
    adapter neither creates buckets nor makes objects publicly accessible.
    """

    def __init__(self, bucket: str, *, client=None, prefix: str = "tradecase", encryption: str = "AES256"):
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError("invalid bucket name")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", prefix):
            raise ValueError("invalid storage prefix")
        if encryption not in {"AES256", "aws:kms"}:
            raise ValueError("server side encryption must be configured")
        if client is None:
            import boto3

            client = boto3.client("s3")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.encryption = encryption

    def _key(self, key):
        _digest_from_key(key)
        return f"{self.prefix}/{key}"

    def put(self, data: bytes) -> ObjectRef:
        ref = _reference(data)
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(ref.key),
            Body=data,
            ContentType="application/octet-stream",
            ServerSideEncryption=self.encryption,
            Metadata={"sha256": ref.sha256},
        )
        return ref

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        stream = response["Body"]
        try:
            if response.get("ContentLength", 0) > MAX_OBJECT_BYTES:
                raise ValueError("stored object exceeds limit")
            data = stream.read(MAX_OBJECT_BYTES + 1)
            if len(data) > MAX_OBJECT_BYTES or hashlib.sha256(data).hexdigest() != _digest_from_key(key):
                raise ValueError("object integrity mismatch")
            return data
        finally:
            stream.close()

    def verify(self, key: str, sha256: str | None = None) -> bool:
        try:
            data = self.get(key)
        except (OSError, ValueError):
            return False
        return sha256 is None or hashlib.sha256(data).hexdigest() == sha256

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))


def configured_storage(settings):
    """No connection is made for the default local backend; S3 uses deployment identity."""
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_root)
    if settings.storage_backend != "s3" or not settings.s3_bucket:
        raise ValueError("storage backend must be local or an explicitly configured S3 bucket")
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}),
    )
    return S3Storage(settings.s3_bucket, client=client, encryption=settings.s3_encryption)
