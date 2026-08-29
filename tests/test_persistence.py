from app.config import Settings
from app.db import Database


def test_processing_claim_accepts_one_completion_only(tmp_path):
    database = Database(Settings(database_url=f"sqlite:///{(tmp_path / 'archive.sqlite3').as_posix()}"))
    database.initialize()
    database.create_media({
        "id": "00000000-0000-0000-0000-000000000123", "owner_sub": "owner", "original_name": "test.jpg",
        "media_type": "image", "content_type": "image/jpeg", "checksum_sha256": "f" * 64,
        "status": "UPLOADING", "source_path": "raw/test.jpg", "source_url": "/api/media/test/content",
    })
    assert database.mark_processing("00000000-0000-0000-0000-000000000123", "owner") is True
    assert database.mark_processing("00000000-0000-0000-0000-000000000123", "owner") is False
    assert database.update_processing_result(
        "00000000-0000-0000-0000-000000000123", "owner", status="READY", thumbnail_path=None,
        thumbnail_url=None, tags={}, model_version="test", expected_status="UPLOADING",
    ) is False
    assert database.update_processing_result(
        "00000000-0000-0000-0000-000000000123", "owner", status="READY", thumbnail_path=None,
        thumbnail_url=None, tags={}, model_version="test", expected_status="PROCESSING",
    ) is True


def test_short_environment_variable_alias_is_supported(monkeypatch):
    monkeypatch.setenv("PACIFICBIO_ENV", "production")
    assert Settings().environment == "production"
