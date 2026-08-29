import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS media (
  id TEXT PRIMARY KEY,
  owner_sub TEXT NOT NULL,
  original_name TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
  content_type TEXT NOT NULL,
  checksum_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  source_path TEXT NOT NULL,
  thumbnail_path TEXT,
  source_url TEXT NOT NULL,
  thumbnail_url TEXT,
  tags_json TEXT NOT NULL DEFAULT '{}',
  model_version TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(owner_sub, checksum_sha256)
);
CREATE INDEX IF NOT EXISTS media_owner_created_idx ON media(owner_sub, created_at DESC);
CREATE INDEX IF NOT EXISTS media_owner_thumb_idx ON media(owner_sub, thumbnail_url);
CREATE TABLE IF NOT EXISTS media_tags (
  media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
  owner_sub TEXT NOT NULL,
  species TEXT NOT NULL,
  tag_count INTEGER NOT NULL CHECK (tag_count >= 1),
  source TEXT NOT NULL,
  confidence REAL,
  PRIMARY KEY(media_id, species)
);
CREATE INDEX IF NOT EXISTS media_tags_lookup_idx ON media_tags(owner_sub, species, tag_count, media_id);
CREATE TABLE IF NOT EXISTS subscriptions (
  owner_sub TEXT NOT NULL,
  species TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(owner_sub, species)
);
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  owner_sub TEXT NOT NULL,
  species TEXT NOT NULL,
  media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  channel TEXT NOT NULL,
  status TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, settings: Settings):
        self.path = settings.database_path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def row_to_dict(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["tags"] = json.loads(value.pop("tags_json"))
        return value

    def get_media(self, media_id: str, owner_sub: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM media WHERE id = ? AND owner_sub = ?", (media_id, owner_sub)).fetchone()
        return self.row_to_dict(row) if row else None

    def get_media_by_checksum(self, checksum: str, owner_sub: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM media WHERE checksum_sha256 = ? AND owner_sub = ?", (checksum, owner_sub)
            ).fetchone()
        return self.row_to_dict(row) if row else None

    def create_media(self, media: dict) -> None:
        now = utc_now()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO media (
                  id, owner_sub, original_name, media_type, content_type, checksum_sha256,
                  status, source_path, source_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    media["id"], media["owner_sub"], media["original_name"], media["media_type"],
                    media["content_type"], media["checksum_sha256"], media["status"], media["source_path"],
                    media["source_url"], now, now,
                ),
            )

    def update_processing_result(
        self, media_id: str, owner_sub: str, *, status: str, thumbnail_path: str | None,
        thumbnail_url: str | None, tags: dict, model_version: str | None, expected_status: str | None = None,
    ) -> bool:
        now = utc_now()
        with self.connection() as conn:
            sql = """UPDATE media SET status=?, thumbnail_path=?, thumbnail_url=?, tags_json=?,
                   model_version=?, updated_at=? WHERE id=? AND owner_sub=?"""
            params: list[object] = [status, thumbnail_path, thumbnail_url, json.dumps(tags, sort_keys=True), model_version, now, media_id, owner_sub]
            if expected_status:
                sql += " AND status=?"
                params.append(expected_status)
            result = conn.execute(
                sql, params,
            )
            if result.rowcount != 1:
                return False
            conn.execute("DELETE FROM media_tags WHERE media_id = ?", (media_id,))
            for species, detail in tags.items():
                conn.execute(
                    """INSERT INTO media_tags (media_id, owner_sub, species, tag_count, source, confidence)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (media_id, owner_sub, species, detail["count"], detail["source"], detail.get("confidence")),
                )
        return True

    def mark_processing(self, media_id: str, owner_sub: str) -> bool:
        with self.connection() as conn:
            result = conn.execute(
                "UPDATE media SET status=?, updated_at=? WHERE id=? AND owner_sub=? AND status=?",
                ("PROCESSING", utc_now(), media_id, owner_sub, "UPLOADING"),
            )
        return result.rowcount == 1

    def search_tags(self, owner_sub: str, requested: dict[str, int]) -> list[dict]:
        normalized = {name.strip().lower(): count for name, count in requested.items()}
        placeholders = ",".join("?" for _ in normalized)
        conditions = " OR ".join("(species = ? AND tag_count >= ?)" for _ in normalized)
        params: list[object] = [owner_sub, *normalized.keys()]
        # First filter to candidate species, then require every requested species/count pair.
        params = [owner_sub, *sum(([species, count] for species, count in normalized.items()), [])]
        sql = f"""
          SELECT m.* FROM media m
          JOIN media_tags t ON t.media_id = m.id
          WHERE m.owner_sub = ? AND m.status = 'READY' AND ({conditions})
          GROUP BY m.id
          HAVING COUNT(DISTINCT t.species) = ?
          ORDER BY m.created_at DESC
        """
        params.append(len(normalized))
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self.row_to_dict(row) for row in rows]

    def media_by_thumbnail_url(self, owner_sub: str, thumbnail_url: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM media WHERE owner_sub = ? AND thumbnail_url = ?", (owner_sub, thumbnail_url)
            ).fetchone()
        return self.row_to_dict(row) if row else None

    def list_media(self, owner_sub: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM media WHERE owner_sub = ? ORDER BY created_at DESC", (owner_sub,)
            ).fetchall()
        return [self.row_to_dict(row) for row in rows]

    def manual_tags(self, owner_sub: str, media_ids: list[str], tags: list[str], operation: int) -> list[dict]:
        now = utc_now()
        changed: list[dict] = []
        normalized = sorted({tag.strip().lower() for tag in tags if tag.strip()})
        with self.connection() as conn:
            for media_id in media_ids:
                row = conn.execute("SELECT * FROM media WHERE id=? AND owner_sub=?", (media_id, owner_sub)).fetchone()
                if not row:
                    continue
                item = self.row_to_dict(row)
                tag_map = item["tags"]
                for tag in normalized:
                    if operation == 1:
                        tag_map[tag] = {"count": tag_map.get(tag, {}).get("count", 1), "source": "manual", "confidence": None}
                    else:
                        tag_map.pop(tag, None)
                conn.execute(
                    "UPDATE media SET tags_json=?, updated_at=? WHERE id=?",
                    (json.dumps(tag_map, sort_keys=True), now, media_id),
                )
                conn.execute("DELETE FROM media_tags WHERE media_id=?", (media_id,))
                for species, detail in tag_map.items():
                    conn.execute(
                        "INSERT INTO media_tags VALUES (?, ?, ?, ?, ?, ?)",
                        (media_id, owner_sub, species, detail["count"], detail["source"], detail.get("confidence")),
                    )
                item["tags"] = tag_map
                changed.append(item)
        return changed

    def delete_media(self, owner_sub: str, media_ids: list[str]) -> list[dict]:
        deleted: list[dict] = []
        with self.connection() as conn:
            for media_id in media_ids:
                row = conn.execute("SELECT * FROM media WHERE id=? AND owner_sub=?", (media_id, owner_sub)).fetchone()
                if row:
                    deleted.append(self.row_to_dict(row))
                    conn.execute("DELETE FROM media WHERE id=? AND owner_sub=?", (media_id, owner_sub))
        return deleted

    def subscribe(self, owner_sub: str, species: str) -> bool:
        with self.connection() as conn:
            result = conn.execute(
                "INSERT OR IGNORE INTO subscriptions VALUES (?, ?, ?)", (owner_sub, species.lower(), utc_now())
            )
        return result.rowcount == 1

    def subscriptions_for(self, species: str) -> list[str]:
        with self.connection() as conn:
            return [row["owner_sub"] for row in conn.execute("SELECT owner_sub FROM subscriptions WHERE species=?", (species.lower(),))]

    def record_notification(self, notification_id: str, owner_sub: str, species: str, media_id: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO notifications VALUES (?, ?, ?, ?, ?, ?, ?)",
                (notification_id, owner_sub, species, media_id, utc_now(), "email", status),
            )


def create_database(settings: Settings):
    """Select a durable DynamoDB repository in production, SQLite locally."""
    if settings.uses_cloud_persistence:
        from app.services.dynamo_repository import DynamoRepository
        return DynamoRepository(settings)
    return Database(settings)
