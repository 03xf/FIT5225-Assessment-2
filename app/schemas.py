from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class User(BaseModel):
    subject: str
    email: str | None = None
    display_name: str | None = None


class TagCount(BaseModel):
    count: int = Field(ge=1)
    source: Literal["auto", "manual", "demo"] = "auto"
    confidence: float | None = Field(default=None, ge=0, le=1)


class MediaResponse(BaseModel):
    id: str
    original_name: str
    media_type: Literal["image", "video"]
    content_type: str
    checksum_sha256: str
    status: str
    source_url: str
    thumbnail_url: str | None
    tags: dict[str, TagCount]
    model_version: str | None
    created_at: datetime


class TagSearchRequest(BaseModel):
    tags: dict[str, int] = Field(min_length=1)


class SpeciesSearchRequest(BaseModel):
    species: str = Field(min_length=1, max_length=120)


class ThumbnailResolveRequest(BaseModel):
    thumbnail_url: str = Field(min_length=1)


class BulkTagRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=100)
    tags: list[str] = Field(min_length=1, max_length=46)
    operation: Literal[0, 1]


class BulkDeleteRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=100)


class SubscriptionRequest(BaseModel):
    species: str = Field(min_length=1, max_length=120)


class UploadSessionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=120)
    checksum_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class UploadSessionResponse(BaseModel):
    media_id: str
    duplicate: bool
    upload_url: str | None
    existing_media: MediaResponse | None = None


class WorkerCallback(BaseModel):
    media_id: str
    owner_sub: str
    tags: dict[str, TagCount]
    model_version: str
    thumbnail_key: str | None = None
    callback_nonce: str = Field(min_length=16, max_length=256)


class ErrorResponse(BaseModel):
    detail: str
