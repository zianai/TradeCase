"""Storage checks are offline; an injected S3 client is explicitly synthetic."""

import io
from concurrent.futures import ThreadPoolExecutor

import pytest

from tradecase.platform.storage import LocalStorage, S3Storage


def test_content_address_deduplication_and_integrity(tmp_path):
    store = LocalStorage(tmp_path / "objects")
    with ThreadPoolExecutor(4) as pool:
        refs = list(pool.map(store.put, [b"Synthetic original evidence"] * 8))
    assert len({ref.key for ref in refs}) == 1
    assert store.get(refs[0].key) == b"Synthetic original evidence"
    assert store.verify(refs[0].key, refs[0].sha256)
    (store.root / refs[0].key).write_bytes(b"tampered")
    assert not store.verify(refs[0].key)
    with pytest.raises(ValueError, match="integrity"):
        store.get(refs[0].key)
    with pytest.raises(ValueError, match="integrity"):
        store.put(b"Synthetic original evidence")


@pytest.mark.parametrize("key", ["../../secret", "/etc/passwd", "sha256/aa/" + "b" * 64, "https://example.com"])
def test_invalid_object_reference_never_reads_arbitrary_path(tmp_path, key):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).get(key)


def test_symlink_object_is_rejected(tmp_path):
    store = LocalStorage(tmp_path / "objects")
    ref = store.put(b"original")
    path = store.root / ref.key
    path.unlink()
    target = tmp_path / "private"
    target.write_bytes(b"original")
    path.symlink_to(target)
    with pytest.raises(ValueError):
        store.get(ref.key)


def test_storage_size_bound(tmp_path):
    with pytest.raises(ValueError, match="20 MiB"):
        LocalStorage(tmp_path).put(b"x" * (20 * 1024 * 1024 + 1))


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.put_calls = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs):
        data = self.objects[kwargs["Key"]]
        return {"Body": io.BytesIO(data), "ContentLength": len(data)}

    def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)


def test_s3_adapter_contract_with_fake_client():
    client = FakeS3()
    store = S3Storage("synthetic-bucket", client=client)
    ref = store.put(b"offline synthetic only")
    assert store.get(ref.key) == b"offline synthetic only"
    assert store.verify(ref.key, ref.sha256)
    assert client.put_calls[0]["ServerSideEncryption"] == "AES256"
    assert "ACL" not in client.put_calls[0]
    store.delete(ref.key)
    assert client.objects == {}
