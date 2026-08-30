"""SQS-triggered AWS dispatcher for the private GCP Cloud Run ML worker.

AWS workload identity federation supplies Application Default Credentials in
the Lambda runtime. The dispatcher exchanges them for an audience-bound Google
ID token; no long-lived GCP service-account JSON key is stored in the browser
or repository.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.config import Settings
from app.db import create_database
from app.services.gcp_wif import cloud_run_id_token
from app.services.s3_storage import S3Storage


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def dispatch(message: dict[str, Any]) -> None:
    settings = Settings()
    repository = create_database(settings)
    media_id = str(message["media_id"])
    owner_sub = str(message["owner_sub"])
    item = repository.get_media(media_id, owner_sub)
    if not item or item["status"] != "PROCESSING":
        return
    if not repository.claim_dispatch(media_id, owner_sub):
        return
    storage = S3Storage(settings)
    worker_url = required("PACIFICBIO_GCP_PROCESSOR_URL").rstrip("/")
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
        token = cloud_run_id_token(worker_url, required("PACIFICBIO_GCP_WIF_AUDIENCE"), required("PACIFICBIO_GCP_WIF_SERVICE_ACCOUNT"))
        headers = {"Authorization": f"Bearer {token}", "X-Worker-Key": required("PACIFICBIO_WORKER_SHARED_KEY")}
        response = httpx.post(f"{worker_url}/process", json=payload, headers=headers, timeout=900)
        response.raise_for_status()
    except Exception:
        repository.release_dispatch(media_id, owner_sub)
        raise


def handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    for record in event.get("Records", []):
        dispatch(json.loads(record["body"]))
    return {"processed": len(event.get("Records", []))}
