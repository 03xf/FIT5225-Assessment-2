"""Authenticated calls to the private Alibaba Cloud Function Compute worker."""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx


def worker_headers(shared_key: str) -> dict[str, str]:
    if not shared_key:
        raise RuntimeError("PACIFICBIO_WORKER_SHARED_KEY is required")
    return {"X-Worker-Key": shared_key}


async def invoke_worker(url: str, path: str, payload: dict[str, Any], shared_key: str) -> httpx.Response:
    endpoint = f"{url.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=900) as client:
        response = await client.post(endpoint, json=payload, headers=worker_headers(shared_key))
        response.raise_for_status()
        return response


def callback_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
