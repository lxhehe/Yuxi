import json
from io import BytesIO

import pytest
from minio.error import S3Error
from urllib3 import HTTPResponse

from yuxi.storage.s3.client import ObjectStoreClient, normalize_public_object_url


class FakeMinio:
    def __init__(self):
        self.policy = None

    def bucket_exists(self, bucket_name: str) -> bool:
        return False

    def make_bucket(self, bucket_name: str) -> None:
        return None

    def set_bucket_policy(self, bucket_name: str, policy: str) -> None:
        self.policy = json.loads(policy)

    def put_object(self, **kwargs):
        return object()


def test_public_image_uses_same_origin_url_without_bucket_listing(monkeypatch):
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "/minio")
    client = ObjectStoreClient()
    fake_object_store = FakeMinio()
    client._client = fake_object_store

    result = client.upload_file("public", "images/user 1/avatar.png", b"image", "image/png")

    assert result.url == "/minio/public/images/user%201/avatar.png"
    assert fake_object_store.policy is not None
    actions = [action for statement in fake_object_store.policy["Statement"] for action in statement["Action"]]
    assert actions == ["s3:GetObject"]


def test_legacy_public_minio_url_is_normalized_to_same_origin(monkeypatch):
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "/minio")

    assert (
        normalize_public_object_url("http://example.test:9000/public/avatar/user.png") == "/minio/public/avatar/user.png"
    )
    assert normalize_public_object_url("https://cdn.example.test/public/user.png") == (
        "https://cdn.example.test/public/user.png"
    )


def test_legacy_public_minio_url_preserves_query_and_fragment(monkeypatch):
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "/minio")

    assert (
        normalize_public_object_url("http://example.test:9000/public/avatar/user.png?v=123#preview")
        == "/minio/public/avatar/user.png?v=123#preview"
    )


@pytest.mark.parametrize("read_error", [False, True])
def test_download_file_always_releases_response(read_error):
    class Response:
        closed = False
        released = False

        def read(self):
            if read_error:
                raise RuntimeError("read failed")
            return b"content"

        def close(self):
            self.closed = True

        def release_conn(self):
            self.released = True

    response = Response()
    client = ObjectStoreClient()
    client._client = type("FakeClient", (), {"get_object": lambda _self, **_kwargs: response})()

    if read_error:
        with pytest.raises(RuntimeError, match="read failed"):
            client.download_file("bucket", "object")
    else:
        assert client.download_file("bucket", "object") == b"content"

    assert response.closed is True
    assert response.released is True


@pytest.mark.asyncio
@pytest.mark.parametrize("read_error", [False, True])
async def test_async_download_file_always_releases_response(read_error):
    class Response:
        closed = False
        released = False

        def read(self):
            if read_error:
                raise RuntimeError("read failed")
            return b"content"

        def close(self):
            self.closed = True

        def release_conn(self):
            self.released = True

    response = Response()
    client = ObjectStoreClient()
    client._client = type("FakeClient", (), {"get_object": lambda _self, **_kwargs: response})()

    if read_error:
        with pytest.raises(RuntimeError, match="read failed"):
            await client.adownload_file("bucket", "object")
    else:
        assert await client.adownload_file("bucket", "object") == b"content"

    assert response.closed is True
    assert response.released is True


@pytest.mark.asyncio
async def test_delete_prefix_is_idempotent_when_bucket_does_not_exist():
    client = ObjectStoreClient()

    class MissingBucketClient:
        def list_objects(self, *_args, **_kwargs):
            response = HTTPResponse(BytesIO(b""), status=404)
            raise S3Error(response, "NoSuchBucket", "Not found", "kb-images", "request_id", "host_id")

    client._client = MissingBucketClient()

    assert await client.adelete_objects_by_prefix("kb-images", "kb-1/") == 0


def test_private_upload_uses_s3_internal_url(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", "http://rustfs:9000")
    monkeypatch.setenv("S3_ACCESS_KEY", "rustfsadmin")
    monkeypatch.setenv("S3_SECRET_KEY", "rustfsadmin")
    client = ObjectStoreClient()
    fake_object_store = FakeMinio()
    client._client = fake_object_store

    result = client.upload_file("knowledgebases", "db/upload/note.md", b"# note")

    assert result.url == "s3://knowledgebases/db/upload/note.md"
    assert client.endpoint == "http://rustfs:9000"


def test_object_store_client_reads_s3_env(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", "http://rustfs:9000")
    monkeypatch.setenv("S3_ACCESS_KEY", "key")
    monkeypatch.setenv("S3_SECRET_KEY", "secret")
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "/minio")
    client = ObjectStoreClient()

    assert client.endpoint == "http://rustfs:9000"
    assert client.access_key == "key"
    assert client.secret_key == "secret"
    assert client.public_base_url == "/minio"
