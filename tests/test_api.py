from pathlib import Path
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


FIXTURES = Path(__file__).parent / "fixtures" / "test_images"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PACIFICBIO_ENV", "development")
    monkeypatch.setenv("PACIFICBIO_DATABASE_URL", f"sqlite:///{(tmp_path / 'archive.sqlite3').as_posix()}")
    monkeypatch.setenv("PACIFICBIO_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("PACIFICBIO_WORKER_CALLBACK_HMAC_SECRET", "test-callback-secret")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def upload(client: TestClient, name: str) -> dict:
    path = FIXTURES / name
    with path.open("rb") as stream:
        response = client.post("/api/media/upload", files={"file": (name, stream, "image/jpeg")})
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_deduplicates_and_generates_thumbnail(client: TestClient):
    first = upload(client, "Bos_taurus_1.JPG")
    duplicate = upload(client, "Bos_taurus_1.JPG")
    assert first["id"] == duplicate["id"]
    assert first["checksum_sha256"] == duplicate["checksum_sha256"]
    assert first["status"] == "READY"
    assert first["thumbnail_url"]
    assert first["tags"]["bos_taurus"]["count"] == 1
    thumbnail = client.get(first["thumbnail_url"])
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/jpeg")


def test_tag_and_species_search_use_logical_and(client: TestClient):
    cattle = upload(client, "Bos_taurus_1.JPG")
    cat = upload(client, "Felis_catus_3.JPG")
    change = client.post(
        "/api/media/tags",
        json={"urls": [cattle["source_url"], cat["source_url"]], "tags": ["research_priority"], "operation": 1},
    )
    assert change.status_code == 200
    result = client.post("/api/search/tags", json={"tags": {"research_priority": 1, "bos_taurus": 1}})
    assert result.status_code == 200
    assert [media["id"] for media in result.json()] == [cattle["id"]]
    species = client.post("/api/search/species", json={"species": "felis_catus"})
    assert [media["id"] for media in species.json()] == [cat["id"]]


def test_thumbnail_lookup_temporary_query_and_deletion(client: TestClient):
    item = upload(client, "Casuarius_casuarius_1.JPG")
    resolved = client.post("/api/resolve-thumbnail", json={"thumbnail_url": item["thumbnail_url"]})
    assert resolved.status_code == 200
    assert resolved.json()["source_url"] == item["source_url"]
    absolute = client.post("/api/resolve-thumbnail", json={"thumbnail_url": f"https://archive.example{item['thumbnail_url']}"})
    assert absolute.status_code == 200
    assert absolute.json()["source_url"] == item["source_url"]
    query_path = FIXTURES / "Casuarius_casuarius_2.JPG"
    with query_path.open("rb") as stream:
        matched = client.post("/api/search/by-file", files={"file": (query_path.name, stream, "image/jpeg")})
    assert matched.status_code == 200
    assert [media["id"] for media in matched.json()] == [item["id"]]
    deleted = client.request("DELETE", "/api/media", json={"urls": [item["source_url"]]})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_media_ids"] == [item["id"]]
    assert client.get(item["source_url"]).status_code == 404


def test_users_cannot_access_each_others_media(client: TestClient):
    owner = upload(client, "Sus_scrofa_1.JPG")
    denied = client.get(owner["source_url"], headers={"X-Demo-User": "another.researcher"})
    assert denied.status_code == 404


def test_species_subscription_is_idempotent(client: TestClient):
    first = client.post("/api/subscriptions", json={"species": "sus_scrofa"})
    second = client.post("/api/subscriptions", json={"species": "sus_scrofa"})
    assert first.status_code == 201
    assert first.json()["status"] == "subscribed"
    assert second.json()["status"] == "already-subscribed"


def test_worker_callback_requires_hmac_and_writes_result(client: TestClient):
    item = upload(client, "Bos_taurus_1.JPG")
    payload = {
        "media_id": item["id"], "owner_sub": "demo.researcher", "tags": {"sus_scrofa": {"count": 2, "source": "auto", "confidence": 0.88}},
        "model_version": "cloud-model-v2", "thumbnail_key": "thumbnails/test.jpg", "callback_nonce": "x" * 16,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    denied = client.post("/internal/worker-callback", content=body, headers={"content-type": "application/json"})
    assert denied.status_code == 401
    signature = hmac.new(b"test-callback-secret", body, hashlib.sha256).hexdigest()
    saved = client.post("/internal/worker-callback", content=body, headers={"content-type": "application/json", "x-pacificbio-signature": signature})
    assert saved.status_code == 200
    assert saved.json()["tags"]["sus_scrofa"]["count"] == 2
    assert saved.json()["model_version"] == "cloud-model-v2"
