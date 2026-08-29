"""Private Alibaba Function Compute worker for supplied MegaDetector + SpeciesNet assets.

This service is intentionally separate from the web/API container: model
dependencies and video decoding are too large for ordinary Lambda ZIPs. It is
invoked only by the AWS dispatcher with an application-level shared key and
returns results through an HMAC-signed callback.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import torch
import torchvision.transforms as transforms
from fastapi import FastAPI, Header, HTTPException
from PIL import Image
from pydantic import BaseModel, Field


CLASSES = [
    "Alectura_lathami", "Antechinus_agilis", "Bos_taurus", "Burhinus_grallarius", "Canis_familiaris",
    "Chalcophaps_longirostris", "Colluricincla_harmonica", "Corcorax_melanorhamphos", "Dacelo_novaeguineae",
    "Dama_dama", "Eopsaltria_australis", "Felis_catus", "Geopelia_humeralis", "Gymnorhina_tibicen",
    "Homo_sapiens", "Isoodon_macrourus", "Lepus_europaeus", "Macropus_giganteus", "Menura_novaehollandiae",
    "Mus_musculus", "Oryctolagus_cuniculus", "Perameles_nasuta", "Pitta_versicolor", "Rattus",
    "Rattus_fuscipes", "Rattus_rattus", "Strepera_graculina", "Sus_scrofa", "Tachyglossus_aculeatus",
    "Thylogale_stigmatica", "Trichosurus_caninus", "Trichosurus_cunninghami", "Trichosurus_vulpecula",
    "Varanus_varius", "Vombatus_ursinus", "Vulpes_vulpes", "Wallabia_bicolor", "Canis_dingo",
    "Capra_hircus", "Casuarius_casuarius", "Heteromyias_cinereifrons", "Hypsiprymnodon_moschatus",
    "Megapodius_reinwardt", "Notamacropus_rufogriseus", "Orthonyx_spaldingii", "Uromys_caudimaculatus",
]
MODEL_ROOT = Path(os.getenv("MODEL_ROOT", "/models"))
MANIFEST_PATH = Path(os.getenv("MODEL_MANIFEST", str(MODEL_ROOT / "model-manifest.json")))
MODEL_BUCKET = os.getenv("ALIBABA_OSS_BUCKET", "")
MODEL_ENDPOINT = os.getenv("ALIBABA_OSS_ENDPOINT", "")
MODEL_PREFIX = os.getenv("ALIBABA_MODEL_PREFIX", "")
WORKER_KEY = os.getenv("WORKER_SHARED_KEY", "")
CALLBACK_SECRET = os.getenv("CALLBACK_HMAC_SECRET", "")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
TRANSFORM = transforms.Compose([transforms.Resize((480, 480)), transforms.ToTensor()])
_model: Any | None = None


class ProcessRequest(BaseModel):
    media_id: str
    owner_sub: str
    media_type: str
    input_url: str
    thumbnail_upload_url: str
    thumbnail_key: str
    callback_url: str
    callback_nonce: str = Field(min_length=16, max_length=256)


class QueryRequest(BaseModel):
    input_url: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def model_asset(entry: dict) -> Path:
    """Return a checksum-pinned model, restoring it from private Alibaba OSS if needed."""
    target = MODEL_ROOT / Path(entry["uri"]).name
    if target.exists():
        return target
    if not MODEL_BUCKET:
        raise RuntimeError(f"Model asset is unavailable: {target}")
    if not MODEL_ENDPOINT:
        raise RuntimeError("ALIBABA_OSS_ENDPOINT is required to restore model assets")
    import oss2
    target.parent.mkdir(parents=True, exist_ok=True)
    access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
    access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
    security_token = os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN", "")
    auth = (
        oss2.StsAuth(access_key_id, access_key_secret, security_token, auth_version=oss2.AUTH_VERSION_4)
        if security_token
        else oss2.ProviderAuthV4(access_key_id, access_key_secret)
    )
    bucket = oss2.Bucket(auth, MODEL_ENDPOINT, MODEL_BUCKET, region=os.getenv("ALIBABA_CLOUD_REGION", "cn-hangzhou"))
    object_name = entry["uri"].lstrip("/")
    if MODEL_PREFIX:
        object_name = f"{MODEL_PREFIX.rstrip('/')}/{object_name}"
    bucket.get_object_to_file(object_name, str(target))
    return target


def load_classifier(manifest: dict):
    global _model
    if _model is not None:
        return _model
    classifier = model_asset(manifest["classifier"])
    expected = manifest["classifier"]["sha256"].lower()
    if sha256_file(classifier).lower() != expected:
        raise RuntimeError("Classifier checksum does not match the active manifest")
    # The supplied, checksum-verified model requires legacy object loading.
    # Never load a user-uploaded model through this path.
    _model = torch.load(classifier, map_location=DEVICE, weights_only=False)
    _model.eval().to(DEVICE)
    return _model


def detector_records(image_path: Path, manifest: dict) -> list[dict]:
    from megadetector.detection import run_detector_batch

    detector = model_asset(manifest["detector"])
    expected = manifest["detector"]["sha256"].lower()
    if sha256_file(detector).lower() != expected:
        raise RuntimeError("Detector checksum does not match the active manifest")
    response = run_detector_batch.load_and_run_detector_batch(image_file_names=[str(image_path)], model_file=str(detector))
    if isinstance(response, dict):
        return response.get("images", response.get("results", []))
    return response


@torch.no_grad()
def classify_crop(crop: Image.Image, model: Any) -> tuple[str, float]:
    tensor = TRANSFORM(crop.convert("RGB")).unsqueeze(0).permute(0, 2, 3, 1).to(DEVICE)
    probabilities = torch.softmax(model(tensor), dim=1)[0].cpu().numpy()
    index = int(np.argmax(probabilities))
    return CLASSES[index], float(probabilities[index])


def process_image(image_path: Path, manifest: dict) -> Counter[str]:
    model = load_classifier(manifest)
    records = detector_records(image_path, manifest)
    if not records:
        return Counter()
    detections = records[0].get("detections", [])
    found: Counter[str] = Counter()
    with Image.open(image_path) as image:
        width, height = image.size
        for detection in detections:
            if str(detection.get("category")) != "1" or float(detection.get("conf", 0)) < 0.05:
                continue
            x, y, w, h = detection["bbox"]
            left, top = max(0, int(x * width)), max(0, int(y * height))
            right, bottom = min(width, int((x + w) * width)), min(height, int((y + h) * height))
            if right <= left or bottom <= top:
                continue
            species, _ = classify_crop(image.crop((left, top, right, bottom)), model)
            found[species] += 1
    return found


def video_frames(video_path: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video_path), "-vf", "fps=1", str(output / "frame-%05d.jpg")],
        check=True,
        timeout=600,
    )
    return sorted(output.glob("frame-*.jpg"))


def authenticate(internal_key: str | None) -> None:
    if not WORKER_KEY or not internal_key or not hmac.compare_digest(internal_key, WORKER_KEY):
        raise HTTPException(status_code=401, detail="Worker authentication failed")


async def deliver_callback(request: ProcessRequest, tags: Counter[str], manifest: dict) -> None:
    if not CALLBACK_SECRET:
        raise RuntimeError("Callback HMAC secret is not configured")
    payload = {
        "media_id": request.media_id,
        "owner_sub": request.owner_sub,
        "tags": {species.lower(): {"count": count, "source": "auto", "confidence": None} for species, count in tags.items()},
        "model_version": manifest["active_version"],
        "thumbnail_key": request.thumbnail_key,
        "callback_nonce": request.callback_nonce,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(CALLBACK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(request.callback_url, content=body, headers={"content-type": "application/json", "x-pacificbio-signature": signature})
        response.raise_for_status()


app = FastAPI(title="Pacific BioArchive ML Worker")


def create_thumbnail(source: Path, destination: Path) -> None:
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.thumbnail((480, 480))
        image.save(destination, format="JPEG", quality=82, optimize=True)


async def upload_thumbnail(upload_url: str, thumbnail: Path) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.put(upload_url, content=thumbnail.read_bytes(), headers={"content-type": "image/jpeg"})
        response.raise_for_status()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "device": DEVICE, "model_manifest": str(MANIFEST_PATH)}


@app.post("/process")
async def process(request: ProcessRequest, x_worker_key: str | None = Header(default=None)) -> dict:
    authenticate(x_worker_key)
    manifest = load_manifest()
    with tempfile.TemporaryDirectory(prefix="pacificbio-worker-") as temp:
        root = Path(temp)
        source = root / "input"
        async with httpx.AsyncClient(timeout=300, follow_redirects=False) as client:
            response = await client.get(request.input_url)
            response.raise_for_status()
            source.write_bytes(response.content)
        if request.media_type == "image":
            tags = process_image(source, manifest)
            thumbnail = root / "thumbnail.jpg"
            create_thumbnail(source, thumbnail)
        elif request.media_type == "video":
            tags: Counter[str] = Counter()
            frames = video_frames(source, root / "frames")
            for frame in frames:
                tags.update(process_image(frame, manifest))
            if not frames:
                raise HTTPException(status_code=422, detail="Video has no frames at one frame per second")
            thumbnail = root / "thumbnail.jpg"
            create_thumbnail(frames[0], thumbnail)
        else:
            raise HTTPException(status_code=422, detail="Unsupported media type")
        await upload_thumbnail(request.thumbnail_upload_url, thumbnail)
        await deliver_callback(request, tags, manifest)
        return {"status": "completed", "media_id": request.media_id, "tag_count": sum(tags.values())}


@app.post("/query")
async def query(request: QueryRequest, x_worker_key: str | None = Header(default=None)) -> dict:
    """Classify an ephemeral image and return tags without writing archive data."""
    authenticate(x_worker_key)
    manifest = load_manifest()
    with tempfile.TemporaryDirectory(prefix="pacificbio-query-") as temp:
        source = Path(temp) / "query-image"
        async with httpx.AsyncClient(timeout=300, follow_redirects=False) as client:
            response = await client.get(request.input_url)
            response.raise_for_status()
            source.write_bytes(response.content)
        tags = process_image(source, manifest)
    return {
        "tags": {species.lower(): {"count": count, "source": "auto", "confidence": None} for species, count in tags.items()},
        "model_version": manifest["active_version"],
    }
