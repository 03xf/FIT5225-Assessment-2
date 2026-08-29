import re
import shutil
import tempfile
import uuid
import hashlib
import hmac
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import create_database
from app.schemas import (
    BulkDeleteRequest, BulkTagRequest, MediaResponse, SpeciesSearchRequest,
    SubscriptionRequest, TagSearchRequest, ThumbnailResolveRequest, UploadSessionRequest, UploadSessionResponse, WorkerCallback,
)
from app.services.auth import CurrentUser
from app.services.alibaba_fc import invoke_worker
from app.services.inference import InferenceService
from app.services.media import MediaService
from app.services.s3_storage import S3Storage

MEDIA_URL = re.compile(r"^/api/media/([0-9a-f-]{36})/(?:content|thumbnail)$")


def get_database(settings: Settings = Depends(get_settings)):
    return create_database(settings)


def get_media_service(settings: Settings = Depends(get_settings), database=Depends(get_database)) -> MediaService:
    return MediaService(settings, database, InferenceService(settings))


def get_s3_storage(settings: Settings = Depends(get_settings)) -> S3Storage:
    return S3Storage(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    database = create_database(settings)
    database.initialize()
    MediaService(settings, database, InferenceService(settings)).initialize()
    yield


app = FastAPI(title="Pacific BioArchive", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {"status": "ok", "environment": settings.environment}


@app.get("/auth/config")
def auth_config(settings: Settings = Depends(get_settings)) -> dict:
    """Public, non-secret Cognito settings used by the browser PKCE flow."""
    return {
        "environment": settings.environment,
        "client_id": settings.cognito_app_client_id,
        "domain": settings.cognito_domain,
    }


@app.get("/api/me")
def me(user: CurrentUser) -> dict:
    return user.model_dump()


@app.get("/api/media", response_model=list[MediaResponse])
def list_media(user: CurrentUser, database=Depends(get_database)) -> list[MediaResponse]:
    return [MediaService.response(item) for item in database.list_media(user.subject)]


@app.post("/api/upload-sessions", response_model=UploadSessionResponse)
def create_upload_session(
    request: UploadSessionRequest, user: CurrentUser, database=Depends(get_database), settings: Settings = Depends(get_settings)
) -> UploadSessionResponse:
    duplicate = database.get_media_by_checksum(request.checksum_sha256.lower(), user.subject)
    if duplicate:
        return UploadSessionResponse(media_id=duplicate["id"], duplicate=True, upload_url=None, existing_media=MediaService.response(duplicate))
    if settings.uses_cloud_persistence:
        media_id = str(uuid.uuid4())
        storage = S3Storage(settings)
        key = storage.object_key(user.subject, media_id, request.filename)
        created = database.create_media({
            "id": media_id, "owner_sub": user.subject, "original_name": request.filename,
            "media_type": MediaService.media_type(request.content_type), "content_type": request.content_type,
            "checksum_sha256": request.checksum_sha256.lower(), "status": "UPLOADING", "source_path": key,
            "source_url": f"/api/media/{media_id}/content",
        })
        if created is False:
            # A concurrent request claimed the same owner+checksum first.
            existing = database.get_media_by_checksum(request.checksum_sha256.lower(), user.subject)
            if existing:
                return UploadSessionResponse(media_id=existing["id"], duplicate=True, upload_url=None, existing_media=MediaService.response(existing))
            raise HTTPException(status_code=409, detail="Upload checksum is being reserved; retry shortly")
        return UploadSessionResponse(media_id=media_id, duplicate=False, upload_url=storage.upload_url(key, request.content_type, request.checksum_sha256))
    # Local development has no object-store presigning; multipart performs upload.
    return UploadSessionResponse(media_id=str(uuid.uuid4()), duplicate=False, upload_url="/api/media/upload")


@app.post("/api/media/upload", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    user: CurrentUser, file: UploadFile = File(...), media_service: MediaService = Depends(get_media_service), settings: Settings = Depends(get_settings)
) -> MediaResponse:
    if settings.uses_cloud_persistence:
        raise HTTPException(status_code=405, detail="Production uploads use POST /api/upload-sessions and the returned S3 URL")
    try:
        result, duplicate = await media_service.upload(user.subject, file)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc
    if duplicate:
        return result
    return result


@app.post("/api/media/{media_id}/complete", response_model=MediaResponse)
def complete_cloud_upload(media_id: str, user: CurrentUser, database=Depends(get_database), settings: Settings = Depends(get_settings)) -> MediaResponse:
    if not settings.uses_cloud_persistence:
        raise HTTPException(status_code=405, detail="Completion endpoint is only used by cloud uploads")
    item = database.get_media(media_id, user.subject)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")
    if not settings.aws_processing_queue_url:
        raise HTTPException(status_code=503, detail="Processing queue is not configured")
    storage = S3Storage(settings)
    if not storage.checksum_matches(item["source_path"], item["checksum_sha256"]):
        raise HTTPException(status_code=409, detail="S3 object is missing or its checksum does not match the upload session")
    if not database.mark_processing(media_id, user.subject):
        # A browser retry must not enqueue a second model job. The existing
        # record is the stable, idempotent response for this upload session.
        current = database.get_media(media_id, user.subject)
        assert current is not None
        return MediaService.response(current)
    import boto3
    boto3.client("sqs", region_name=settings.aws_region).send_message(
        QueueUrl=settings.aws_processing_queue_url,
        MessageBody=__import__("json").dumps({"media_id": media_id, "owner_sub": user.subject}),
    )
    item = database.get_media(media_id, user.subject)
    assert item is not None
    return MediaService.response(item)


@app.get("/api/media/{media_id}/content")
def media_content(media_id: str, user: CurrentUser, media_service: MediaService = Depends(get_media_service), database=Depends(get_database), settings: Settings = Depends(get_settings)):
    if settings.uses_cloud_persistence:
        item = database.get_media(media_id, user.subject)
        if not item:
            raise HTTPException(status_code=404, detail="Media not found")
        return RedirectResponse(S3Storage(settings).download_url(item["source_path"]))
    try:
        path, media_type = media_service.get_owned_path(media_id, user.subject)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@app.get("/api/media/{media_id}/thumbnail")
def media_thumbnail(media_id: str, user: CurrentUser, media_service: MediaService = Depends(get_media_service), database=Depends(get_database), settings: Settings = Depends(get_settings)):
    if settings.uses_cloud_persistence:
        item = database.get_media(media_id, user.subject)
        if not item or not item.get("thumbnail_path"):
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return RedirectResponse(S3Storage(settings).download_url(item["thumbnail_path"]))
    try:
        path, media_type = media_service.get_owned_path(media_id, user.subject, thumbnail=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=media_type)


@app.post("/api/search/tags", response_model=list[MediaResponse])
def search_tags(request: TagSearchRequest, user: CurrentUser, database=Depends(get_database)) -> list[MediaResponse]:
    if any(count < 1 for count in request.tags.values()):
        raise HTTPException(status_code=422, detail="Minimum tag counts must be at least one")
    return [MediaService.response(item) for item in database.search_tags(user.subject, request.tags)]


@app.post("/api/search/species", response_model=list[MediaResponse])
def search_species(request: SpeciesSearchRequest, user: CurrentUser, database=Depends(get_database)) -> list[MediaResponse]:
    return [MediaService.response(item) for item in database.search_tags(user.subject, {request.species: 1})]


@app.post("/api/resolve-thumbnail")
def resolve_thumbnail(request: ThumbnailResolveRequest, user: CurrentUser, database=Depends(get_database)) -> dict:
    parsed = urlparse(request.thumbnail_url)
    # The database keeps stable same-origin API paths, while copying an image
    # from a browser normally produces an absolute URL. Never use the caller's
    # authority; only resolve the owned API path.
    thumbnail_url = parsed.path if parsed.scheme and parsed.netloc else request.thumbnail_url
    item = database.media_by_thumbnail_url(user.subject, thumbnail_url)
    if not item:
        raise HTTPException(status_code=404, detail="Thumbnail URL is not owned by this user")
    return {"source_url": item["source_url"], "media_id": item["id"]}


def media_ids_from_urls(urls: list[str]) -> list[str]:
    identifiers: list[str] = []
    for url in urls:
        match = MEDIA_URL.match(url)
        if not match:
            raise HTTPException(status_code=422, detail=f"Unsupported media URL: {url}")
        identifiers.append(match.group(1))
    return identifiers


@app.post("/api/media/tags", response_model=list[MediaResponse])
def edit_tags(request: BulkTagRequest, user: CurrentUser, database=Depends(get_database)) -> list[MediaResponse]:
    ids = media_ids_from_urls(request.urls)
    changed = database.manual_tags(user.subject, ids, request.tags, request.operation)
    return [MediaService.response(item) for item in changed]


@app.delete("/api/media")
def delete_media(request: BulkDeleteRequest, user: CurrentUser, media_service: MediaService = Depends(get_media_service), database=Depends(get_database), settings: Settings = Depends(get_settings)) -> dict:
    if settings.uses_cloud_persistence:
        ids = media_ids_from_urls(request.urls)
        # Delete objects first. If S3 reports a failure the metadata is kept,
        # making the retry visible instead of silently orphaning storage.
        candidates = [database.get_media(media_id, user.subject) for media_id in ids]
        existing = [item for item in candidates if item]
        S3Storage(settings).delete([item["source_path"] for item in existing] + [item["thumbnail_path"] for item in existing if item.get("thumbnail_path")])
        deleted = database.delete_media(user.subject, ids)
        return {"deleted_media_ids": [item["id"] for item in deleted]}
    deleted = media_service.delete(user.subject, media_ids_from_urls(request.urls))
    return {"deleted_media_ids": deleted}


@app.post("/api/subscriptions", status_code=status.HTTP_201_CREATED)
def subscribe(request: SubscriptionRequest, user: CurrentUser, database=Depends(get_database), settings: Settings = Depends(get_settings)) -> dict:
    created = database.subscribe(user.subject, request.species)
    confirmation_pending = False
    if created and settings.sns_topic_arn and user.email:
        import boto3
        boto3.client("sns", region_name=settings.aws_region).subscribe(
            TopicArn=settings.sns_topic_arn,
            Protocol="email",
            Endpoint=user.email,
            Attributes={"FilterPolicy": __import__("json").dumps({"species": [request.species.lower()]})},
            ReturnSubscriptionArn=True,
        )
        confirmation_pending = True
    return {"species": request.species.lower(), "status": "subscribed" if created else "already-subscribed", "email_confirmation_pending": confirmation_pending}


@app.post("/internal/worker-callback", response_model=MediaResponse)
async def worker_callback(request: Request, database=Depends(get_database), settings: Settings = Depends(get_settings)) -> MediaResponse:
    """Accept only signed Alibaba worker results, never browser traffic."""
    secret = settings.worker_callback_hmac_secret
    raw_body = await request.body()
    received = request.headers.get("x-pacificbio-signature", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Worker callback is not configured")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid worker callback signature")
    try:
        callback = WorkerCallback.model_validate_json(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid worker callback payload") from exc
    item = database.get_media(callback.media_id, callback.owner_sub)
    if not item:
        raise HTTPException(status_code=404, detail="Media does not exist")
    thumbnail_url = f"/api/media/{callback.media_id}/thumbnail" if callback.thumbnail_key else None
    saved_result = database.update_processing_result(
        callback.media_id, callback.owner_sub, status="READY", thumbnail_path=callback.thumbnail_key,
        thumbnail_url=thumbnail_url, tags={name: tag.model_dump() for name, tag in callback.tags.items()},
        model_version=callback.model_version, expected_status="DISPATCHED" if settings.uses_cloud_persistence else None,
    )
    if not saved_result:
        current = database.get_media(callback.media_id, callback.owner_sub)
        if current and current["status"] == "READY":
            return MediaService.response(current)
        raise HTTPException(status_code=409, detail="Worker result does not match a pending dispatch")
    MediaService(settings, database, InferenceService(settings))._queue_tag_notifications(callback.media_id, {name: tag.model_dump() for name, tag in callback.tags.items()})
    saved = database.get_media(callback.media_id, callback.owner_sub)
    assert saved is not None
    return MediaService.response(saved)


@app.post("/api/search/by-file", response_model=list[MediaResponse])
async def search_by_file(
    user: CurrentUser, file: UploadFile = File(...), database=Depends(get_database), settings: Settings = Depends(get_settings)
) -> list[MediaResponse]:
    """Process a temporary query upload and never persist it in the media database."""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="Query-by-file accepts images")
    with tempfile.TemporaryDirectory(prefix="pacificbio-query-") as temp_dir:
        destination = Path(temp_dir) / (Path(file.filename or "query.jpg").name)
        received = 0
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                received += len(chunk)
                if received > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="Query file exceeds the configured upload limit")
                output.write(chunk)
        if settings.uses_cloud_persistence:
            if not all([settings.alibaba_processor_url, settings.worker_shared_key]):
                raise HTTPException(status_code=503, detail="Cloud query worker is not configured")
            temporary_key = f"temporary-query/{user.subject}/{uuid.uuid4()}/{destination.name}"
            storage = S3Storage(settings)
            storage.upload_file(temporary_key, str(destination), file.content_type or "image/jpeg")
            try:
                response = await invoke_worker(
                    settings.alibaba_processor_url,
                    "/query",
                    {"input_url": storage.download_url(temporary_key, expires_seconds=900)},
                    settings.worker_shared_key,
                )
                tags = response.json().get("tags", {})
            finally:
                storage.delete([temporary_key])
        else:
            tags = InferenceService(settings).infer_image(destination, file.filename or destination.name).tags
    if not tags or "unclassified" in tags:
        return []
    requested = {species: detail["count"] for species, detail in tags.items()}
    return [MediaService.response(item) for item in database.search_tags(user.subject, requested)]


# Keep the SPA/static mount last: mounted routes are prefix routes and would
# otherwise swallow the authenticated API endpoints above.
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
