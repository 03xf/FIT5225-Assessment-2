import base64

from boto3.dynamodb.types import TypeDeserializer

from app.config import Settings
from app.services.dynamo_repository import DynamoRepository
from app.services.s3_storage import S3Storage


class FakeTable:
    def __init__(self):
        self.items = []
        self.name = "pacificbio-media"
        self.meta = type("Meta", (), {"client": FakeDynamoClient(self)})()

class FakeDynamoClient:
    def __init__(self, table): self.table = table
    def transact_write_items(self, TransactItems):
        for action in TransactItems:
            self.table.items.append({key: TypeDeserializer().deserialize(value) for key, value in action["Put"]["Item"].items()})


class FakeS3:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn, HttpMethod=None):
        self.calls.append((operation, Params, ExpiresIn, HttpMethod))
        return "https://signed.example/object"

    def delete_objects(self, **kwargs):
        self.calls.append(("delete_objects", kwargs, None, None))
        return {"Deleted": kwargs["Delete"]["Objects"]}


def cloud_settings() -> Settings:
    return Settings(
        environment="production",
        dynamodb_table="pacificbio-media",
        aws_media_bucket="pacificbio-media-bucket",
        aws_region="ap-southeast-2",
    )


def test_dynamo_media_item_has_deduplication_access_path():
    table = FakeTable()
    repository = DynamoRepository(cloud_settings(), table=table)
    repository.create_media({
        "id": "00000000-0000-0000-0000-000000000001", "owner_sub": "user-a", "original_name": "animal.jpg",
        "media_type": "image", "content_type": "image/jpeg", "checksum_sha256": "a" * 64,
        "status": "UPLOADING", "source_path": "raw/user-a/id/source.jpg", "source_url": "/api/media/id/content",
    })
    item = table.items[0]
    assert item["PK"] == "USER#user-a"
    assert item["SK"] == "MEDIA#00000000-0000-0000-0000-000000000001"
    assert item["GSI1PK"] == f"CHECKSUM#user-a#{'a' * 64}"
    assert item["tags"] == {}


def test_s3_presigning_scopes_key_content_type_and_checksum_metadata():
    client = FakeS3()
    storage = S3Storage(cloud_settings(), client=client)
    key = storage.object_key("user-a", "media-1", "Observation.JPG")
    url = storage.upload_url(key, "image/jpeg", "b" * 64)
    assert url == "https://signed.example/object"
    operation, params, expires, method = client.calls[0]
    assert operation == "put_object"
    assert params["Bucket"] == "pacificbio-media-bucket"
    assert params["Key"] == "raw/user-a/media-1/source.jpg"
    assert params["ContentType"] == "image/jpeg"
    assert params["ChecksumSHA256"] == base64.b64encode(bytes.fromhex("b" * 64)).decode("ascii")
    assert params["Metadata"] == {"sha256": "b" * 64}
    assert expires == 900 and method == "PUT"


def test_internal_thumbnail_upload_does_not_bind_the_original_file_checksum():
    client = FakeS3()
    storage = S3Storage(cloud_settings(), client=client)
    storage.upload_url("thumbnails/user-a/media/thumb.jpg", "image/jpeg")
    params = client.calls[0][1]
    assert "ChecksumSHA256" not in params
    assert "Metadata" not in params


def test_s3_delete_submits_only_nonempty_keys():
    client = FakeS3()
    storage = S3Storage(cloud_settings(), client=client)
    storage.delete(["raw/user-a/media/source.jpg", "", None])
    assert client.calls[0][1]["Delete"]["Objects"] == [{"Key": "raw/user-a/media/source.jpg"}]
