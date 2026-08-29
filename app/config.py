from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PACIFICBIO_", extra="ignore")

    # Keep PACIFICBIO_ENV as the documented/deployed shorthand while also
    # accepting Pydantic's conventional PACIFICBIO_ENVIRONMENT spelling.
    environment: str = Field(default="development", validation_alias=AliasChoices("PACIFICBIO_ENV", "PACIFICBIO_ENVIRONMENT"))
    database_url: str = "sqlite:///./data/pacificbio.sqlite3"
    storage_root: Path = Path("./uploads")
    jwt_secret: str = "local-development-secret-change-me"
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None
    cognito_domain: str | None = None
    alibaba_processor_url: str | None = None
    alibaba_region: str | None = None
    alibaba_oss_bucket: str | None = None
    alibaba_oss_endpoint: str | None = None
    alibaba_model_prefix: str = "models/"
    aws_region: str = "ap-southeast-2"
    aws_media_bucket: str | None = None
    dynamodb_table: str | None = None
    sns_topic_arn: str | None = None
    aws_processing_queue_url: str | None = None
    worker_callback_hmac_secret: str | None = None
    worker_shared_key: str | None = None
    storage_backend: str = "local"
    model_manifest: Path = Path("models/model-manifest.json")
    inference_mode: str = "demo_filename"
    max_upload_bytes: int = 250 * 1024 * 1024
    query_upload_ttl_minutes: int = 15

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only SQLite is supported by the local adapter")
        return Path(self.database_url.removeprefix(prefix))

    @property
    def uses_cloud_persistence(self) -> bool:
        return self.environment == "production" and bool(self.dynamodb_table)


@lru_cache
def get_settings() -> Settings:
    return Settings()
