import hashlib
import json
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import Settings
from app.db import Database
from app.schemas import MediaResponse
from app.services.inference import InferenceService, create_thumbnail


class MediaService:
    def __init__(self, settings: Settings, database: Database, inference: InferenceService):
        self.settings = settings
        self.database = database
        self.inference = inference
        self.storage_root = settings.storage_root

    def initialize(self) -> None:
        for name in ("raw", "thumbnails", "temporary", "frames"):
            (self.storage_root / name).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def media_type(content_type: str) -> str:
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("video/"):
            return "video"
        raise ValueError("Only image and video files are supported")

    @staticmethod
    def response(item: dict) -> MediaResponse:
        return MediaResponse(
            id=item["id"], original_name=item["original_name"], media_type=item["media_type"],
            content_type=item["content_type"], checksum_sha256=item["checksum_sha256"], status=item["status"],
            source_url=item["source_url"], thumbnail_url=item["thumbnail_url"], tags=item["tags"],
            model_version=item["model_version"], created_at=item["created_at"],
        )

    async def upload(self, owner_sub: str, file: UploadFile) -> tuple[MediaResponse, bool]:
        content_type = (file.content_type or "application/octet-stream").lower()
        media_type = self.media_type(content_type)
        safe_extension = Path(file.filename or "upload.bin").suffix.lower()[:12] or (".jpg" if media_type == "image" else ".mp4")
        staging_path = self.storage_root / "temporary" / f"{uuid.uuid4().hex}{safe_extension}"
        checksum = hashlib.sha256()
        received = 0
        try:
            with staging_path.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    received += len(chunk)
                    if received > self.settings.max_upload_bytes:
                        raise ValueError("File exceeds the configured upload limit")
                    checksum.update(chunk)
                    destination.write(chunk)
            digest = checksum.hexdigest()
            duplicate = self.database.get_media_by_checksum(digest, owner_sub)
            if duplicate:
                return self.response(duplicate), True
            media_id = str(uuid.uuid4())
            source_path = self.storage_root / "raw" / f"{media_id}{safe_extension}"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            staging_path.replace(source_path)
            source_url = f"/api/media/{media_id}/content"
            self.database.create_media({
                "id": media_id, "owner_sub": owner_sub, "original_name": file.filename or "upload",
                "media_type": media_type, "content_type": content_type, "checksum_sha256": digest,
                "status": "PROCESSING", "source_path": str(source_path), "source_url": source_url,
            })
            try:
                self.process(media_id, owner_sub)
            except Exception:
                self.database.update_processing_result(
                    media_id, owner_sub, status="FAILED", thumbnail_path=None, thumbnail_url=None,
                    tags={}, model_version=None,
                )
                raise
            item = self.database.get_media(media_id, owner_sub)
            assert item is not None
            return self.response(item), False
        finally:
            if staging_path.exists():
                staging_path.unlink()

    def process(self, media_id: str, owner_sub: str) -> None:
        item = self.database.get_media(media_id, owner_sub)
        if not item:
            raise ValueError("Media does not exist")
        source = Path(item["source_path"])
        thumbnail_path: Path | None = None
        if item["media_type"] == "image":
            thumbnail_path = self.storage_root / "thumbnails" / f"{media_id}.jpg"
            create_thumbnail(source, thumbnail_path)
            inference = self.inference.infer_image(source, item["original_name"])
        else:
            frame_dir = self.storage_root / "frames" / media_id
            inference = self.inference.infer_video_frames(source, frame_dir)
            frames = sorted(frame_dir.glob("frame-*.jpg"))
            if frames:
                thumbnail_path = self.storage_root / "thumbnails" / f"{media_id}.jpg"
                create_thumbnail(frames[0], thumbnail_path)
        thumbnail_url = f"/api/media/{media_id}/thumbnail" if thumbnail_path and thumbnail_path.exists() else None
        self.database.update_processing_result(
            media_id, owner_sub, status="READY", thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
            thumbnail_url=thumbnail_url, tags=inference.tags, model_version=inference.model_version,
        )
        self._queue_tag_notifications(media_id, inference.tags)

    def _queue_tag_notifications(self, media_id: str, tags: dict[str, dict]) -> None:
        for species in tags:
            subscribers = self.database.subscriptions_for(species)
            if self.settings.sns_topic_arn and subscribers:
                import boto3
                boto3.client("sns", region_name=self.settings.aws_region).publish(
                    TopicArn=self.settings.sns_topic_arn,
                    Subject=f"Pacific BioArchive: {species} detected",
                    Message=json.dumps({"media_id": media_id, "species": species, "event": "tag-added"}),
                    MessageAttributes={"species": {"DataType": "String", "StringValue": species}},
                )
            for subscriber in subscribers:
                self.database.record_notification(str(uuid.uuid4()), subscriber, species, media_id, "QUEUED")

    def get_owned_path(self, media_id: str, owner_sub: str, thumbnail: bool = False) -> tuple[Path, str]:
        item = self.database.get_media(media_id, owner_sub)
        if not item:
            raise FileNotFoundError("Media not found")
        path = Path(item["thumbnail_path"] if thumbnail else item["source_path"])
        if not path.exists():
            raise FileNotFoundError("Media object not found")
        return path, item["content_type"] if not thumbnail else "image/jpeg"

    def delete(self, owner_sub: str, media_ids: list[str]) -> list[str]:
        deleted = self.database.delete_media(owner_sub, media_ids)
        for item in deleted:
            for key in ("source_path", "thumbnail_path"):
                if item.get(key):
                    Path(item[key]).unlink(missing_ok=True)
            shutil.rmtree(self.storage_root / "frames" / item["id"], ignore_errors=True)
        return [item["id"] for item in deleted]
