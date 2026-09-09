"""SQS-triggered AWS dispatcher for the private Alibaba FC ML worker."""
from __future__ import annotations

import json
import os
from typing import Any


from app.config import Settings
from app.db import create_database
from app.services.alibaba_fc import invoke_worker
from app.services.s3_storage import S3Storage


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def dispatch(message: dict[str, Any]) -> None:
    settings = Settings()
    repository = create_database(settings)
    if message.get("kind") == "query":
        dispatch_query(message, settings, repository)
        return
    media_id = str(message["media_id"])
    owner_sub = str(message["owner_sub"])
    item = repository.get_media(media_id, owner_sub)
    if not item or item["status"] != "PROCESSING":
        return
    if not repository.claim_dispatch(media_id, owner_sub):
        return
    storage = S3Storage(settings)
    worker_url = required("PACIFICBIO_ALIBABA_PROCESSOR_URL").rstrip("/")
    thumbnail_key = f"thumbnails/{owner_sub}/{media_id}/thumbnail.jpg"
    payload = {
        "media_id": media_id,
        "owner_sub": owner_sub,
        "media_type": item["media_type"],
        "input_url": storage.download_url(item["source_path"], expires_seconds=900),
        "thumbnail_upload_url": storage.upload_url(thumbnail_key, "image/jpeg"),
        "thumbnail_key": thumbnail_key,
        "callback_url": required("PACIFICBIO_WORKER_CALLBACK_URL"),
        "callback_nonce": required("PACIFICBIO_WORKER_CALLBACK_NONCE_PREFIX") + media_id,
    }
    try:
        import asyncio
        asyncio.run(invoke_worker(worker_url, "/process", payload, required("PACIFICBIO_WORKER_SHARED_KEY")))
    except Exception:
        repository.release_dispatch(media_id, owner_sub)
        raise


def dispatch_query(message: dict[str, Any], settings: Settings, repository: Any) -> None:
    """Run the slow query outside API Gateway and persist a pollable result."""
    query_id = str(message["query_id"])
    owner_sub = str(message["owner_sub"])
    job = repository.claim_query_job(query_id, owner_sub)
    if not job:
        return
    storage = S3Storage(settings)
    try:
        import asyncio
        response = asyncio.run(invoke_worker(
            required("PACIFICBIO_ALIBABA_PROCESSOR_URL").rstrip("/"),
            "/query",
            {"input_url": storage.download_url(job["source_path"], expires_seconds=900)},
            required("PACIFICBIO_WORKER_SHARED_KEY"),
        ))
        tags = response.json().get("tags", {})
        requested = {name: int(detail.get("count", 1)) for name, detail in tags.items()}
        matches = repository.search_tags(owner_sub, requested) if requested else []
        repository.finish_query_job(query_id, owner_sub, tags, [item["id"] for item in matches])
    except Exception as exc:
        repository.fail_query_job(query_id, owner_sub, f"Query processing failed: {type(exc).__name__}")
    finally:
        storage.delete([job["source_path"]])


def handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    for record in event.get("Records", []):
        dispatch(json.loads(record["body"]))
    return {"processed": len(event.get("Records", []))}
