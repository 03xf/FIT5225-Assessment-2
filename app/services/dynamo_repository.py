"""DynamoDB implementation of the repository operations used by the API.

The item layout is deliberately single-table and query-first: owner media,
checksum, thumbnail, tag and subscription paths each have an indexed access
path. This avoids table scans and preserves user ownership at every lookup.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from app.config import Settings

logger = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(UTC).isoformat()


def thumb_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class DynamoRepository:
    def __init__(self, settings: Settings, table: Any | None = None):
        if not settings.dynamodb_table:
            raise ValueError("PACIFICBIO_DYNAMODB_TABLE is required in production")
        self.settings = settings
        self.table = table or boto3.resource("dynamodb", region_name=settings.aws_region).Table(settings.dynamodb_table)
        # Resource tables accept native Python values, while the transaction
        # API below uses the low-level AttributeValue representation.
        self._client = boto3.client("dynamodb", region_name=settings.aws_region) if table is None else table.meta.client

    @staticmethod
    def user_pk(owner: str) -> str: return f"USER#{owner}"
    @staticmethod
    def media_sk(media_id: str) -> str: return f"MEDIA#{media_id}"

    @staticmethod
    def _ddb_map(item: dict) -> dict:
        return TypeSerializer().serialize(item)["M"]

    def initialize(self) -> None:
        # Table lifecycle is Terraform-owned; Lambda never creates data stores.
        return None

    def _media(self, item: dict | None) -> dict | None:
        if not item:
            return None
        result = dict(item)
        for key in ("PK", "SK", "entity", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"):
            result.pop(key, None)
        result.setdefault("tags", {})
        return result

    def get_media(self, media_id: str, owner_sub: str) -> dict | None:
        response = self.table.get_item(Key={"PK": self.user_pk(owner_sub), "SK": self.media_sk(media_id)}, ConsistentRead=True)
        return self._media(response.get("Item"))

    def get_media_by_checksum(self, checksum: str, owner_sub: str) -> dict | None:
        # A checksum-claim record is the strongly consistent dedupe guard. The
        # GSI fallback supports records created by earlier deployments.
        claim = self.table.get_item(
            Key={"PK": self.user_pk(owner_sub), "SK": f"CHECKSUM#{checksum.lower()}"}, ConsistentRead=True
        ).get("Item")
        if claim and claim.get("media_id"):
            return self.get_media(claim["media_id"], owner_sub)
        key = f"CHECKSUM#{owner_sub}#{checksum.lower()}"
        response = self.table.query(IndexName="checksum-index", KeyConditionExpression=Key("GSI1PK").eq(key), Limit=1)
        records = response.get("Items", [])
        return self._media(records[0]) if records else None

    def create_media(self, media: dict) -> bool:
        timestamp = now()
        item = {
            **media, "PK": self.user_pk(media["owner_sub"]), "SK": self.media_sk(media["id"]), "entity": "media",
            "tags": {}, "thumbnail_path": None, "thumbnail_url": None, "model_version": None,
            "created_at": timestamp, "updated_at": timestamp,
            "GSI1PK": f"CHECKSUM#{media['owner_sub']}#{media['checksum_sha256'].lower()}", "GSI1SK": self.media_sk(media["id"]),
        }
        claim = {
            "PK": self.user_pk(media["owner_sub"]), "SK": f"CHECKSUM#{media['checksum_sha256'].lower()}",
            "entity": "checksum-claim", "media_id": media["id"], "created_at": timestamp,
        }
        try:
            self._client.transact_write_items(TransactItems=[
                {"Put": {"TableName": self.table.name, "Item": self._ddb_map(item), "ConditionExpression": "attribute_not_exists(PK)"}},
                {"Put": {"TableName": self.table.name, "Item": self._ddb_map(claim), "ConditionExpression": "attribute_not_exists(PK)"}},
            ])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                reasons = exc.response.get("CancellationReasons") or []
                if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
                    return False
                logger.exception("DynamoDB media reservation transaction cancelled")
            raise
        return True

    def _query_all(self, **kwargs) -> list[dict]:
        items: list[dict] = []
        while True:
            response = self.table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            kwargs["ExclusiveStartKey"] = last_key

    def _replace_tags(self, owner: str, media_id: str, tags: dict) -> None:
        # Tag entries are small (the supplied model has 46 labels), so batch
        # deletion/rewrite is well within DynamoDB batch limits.
        existing = self._query_all(KeyConditionExpression=Key("PK").eq(f"TAGOWNER#{owner}#MEDIA#{media_id}"))
        with self.table.batch_writer() as batch:
            for item in existing:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                # Remove the companion query item as well; otherwise a tag
                # removed through the bulk API could remain searchable.
                species = item["SK"].removeprefix("TAG#")
                batch.delete_item(Key={"PK": f"TAG#{owner}#{species}", "SK": self.media_sk(media_id)})
            for species, detail in tags.items():
                batch.put_item(Item={
                    "PK": f"TAGOWNER#{owner}#MEDIA#{media_id}", "SK": f"TAG#{species}",
                    "entity": "tag-link", "query_pk": f"TAG#{owner}#{species}", "query_sk": self.media_sk(media_id),
                    "media_id": media_id, "tag_count": int(detail["count"]), "source": detail["source"], "confidence": detail.get("confidence"),
                })
                batch.put_item(Item={
                    "PK": f"TAG#{owner}#{species}", "SK": self.media_sk(media_id), "entity": "tag-query",
                    "media_id": media_id, "tag_count": int(detail["count"]),
                })

    def update_processing_result(self, media_id: str, owner_sub: str, *, status: str, thumbnail_path: str | None, thumbnail_url: str | None, tags: dict, model_version: str | None, expected_status: str | None = None) -> bool:
        item = self.get_media(media_id, owner_sub)
        if not item:
            return False
        item.update({"status": status, "thumbnail_path": thumbnail_path, "thumbnail_url": thumbnail_url, "tags": tags, "model_version": model_version, "updated_at": now()})
        if thumbnail_url:
            item["GSI2PK"] = f"THUMB#{owner_sub}#{thumb_hash(thumbnail_url)}"
            item["GSI2SK"] = self.media_sk(media_id)
        kwargs: dict[str, Any] = {"Item": {**item, "PK": self.user_pk(owner_sub), "SK": self.media_sk(media_id), "entity": "media", "GSI1PK": f"CHECKSUM#{owner_sub}#{item['checksum_sha256'].lower()}", "GSI1SK": self.media_sk(media_id)}}
        if expected_status:
            kwargs.update({
                "ConditionExpression": "#status = :expected",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {":expected": expected_status},
            })
        try:
            self.table.put_item(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        self._replace_tags(owner_sub, media_id, tags)
        return True

    def mark_processing(self, media_id: str, owner_sub: str) -> bool:
        try:
            self.table.update_item(
                Key={"PK": self.user_pk(owner_sub), "SK": self.media_sk(media_id)},
                UpdateExpression="SET #status = :status, updated_at = :updated",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":status": "PROCESSING", ":updated": now(), ":uploading": "UPLOADING"},
                ConditionExpression="attribute_exists(PK) AND #status = :uploading",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def claim_dispatch(self, media_id: str, owner_sub: str) -> bool:
        try:
            self.table.update_item(
                Key={"PK": self.user_pk(owner_sub), "SK": self.media_sk(media_id)},
                UpdateExpression="SET #status = :dispatched, updated_at = :updated",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":dispatched": "DISPATCHED", ":processing": "PROCESSING", ":updated": now()},
                ConditionExpression="#status = :processing",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def release_dispatch(self, media_id: str, owner_sub: str) -> None:
        self.table.update_item(
            Key={"PK": self.user_pk(owner_sub), "SK": self.media_sk(media_id)},
            UpdateExpression="SET #status = :processing, updated_at = :updated",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":processing": "PROCESSING", ":dispatched": "DISPATCHED", ":updated": now()},
            ConditionExpression="#status = :dispatched",
        )

    def search_tags(self, owner_sub: str, requested: dict[str, int]) -> list[dict]:
        candidate_ids: set[str] | None = None
        for species, minimum in {key.strip().lower(): value for key, value in requested.items()}.items():
            entries = self._query_all(KeyConditionExpression=Key("PK").eq(f"TAG#{owner_sub}#{species}"))
            found = {entry["media_id"] for entry in entries if int(entry["tag_count"]) >= int(minimum)}
            candidate_ids = found if candidate_ids is None else candidate_ids & found
            if not candidate_ids:
                return []
        media = [self.get_media(media_id, owner_sub) for media_id in candidate_ids or set()]
        return sorted([item for item in media if item and item["status"] == "READY"], key=lambda item: item["created_at"], reverse=True)

    def media_by_thumbnail_url(self, owner_sub: str, thumbnail_url: str) -> dict | None:
        response = self.table.query(IndexName="thumbnail-index", KeyConditionExpression=Key("GSI2PK").eq(f"THUMB#{owner_sub}#{thumb_hash(thumbnail_url)}"), Limit=1)
        records = response.get("Items", [])
        return self._media(records[0]) if records else None

    def list_media(self, owner_sub: str) -> list[dict]:
        records = self._query_all(KeyConditionExpression=Key("PK").eq(self.user_pk(owner_sub)) & Key("SK").begins_with("MEDIA#"))
        return sorted((self._media(item) for item in records), key=lambda item: item["created_at"], reverse=True)

    def manual_tags(self, owner_sub: str, media_ids: list[str], tags: list[str], operation: int) -> list[dict]:
        changed = []
        normalized = {tag.strip().lower() for tag in tags if tag.strip()}
        for media_id in media_ids:
            item = self.get_media(media_id, owner_sub)
            if not item:
                continue
            tag_map = item["tags"]
            for tag in normalized:
                if operation:
                    tag_map[tag] = {"count": tag_map.get(tag, {}).get("count", 1), "source": "manual", "confidence": None}
                else:
                    tag_map.pop(tag, None)
            self.update_processing_result(media_id, owner_sub, status=item["status"], thumbnail_path=item["thumbnail_path"], thumbnail_url=item["thumbnail_url"], tags=tag_map, model_version=item["model_version"])
            item["tags"] = tag_map
            changed.append(item)
        return changed

    def delete_media(self, owner_sub: str, media_ids: list[str]) -> list[dict]:
        deleted = []
        with self.table.batch_writer() as batch:
            for media_id in media_ids:
                item = self.get_media(media_id, owner_sub)
                if not item:
                    continue
                deleted.append(item)
                batch.delete_item(Key={"PK": self.user_pk(owner_sub), "SK": self.media_sk(media_id)})
                batch.delete_item(Key={"PK": self.user_pk(owner_sub), "SK": f"CHECKSUM#{item['checksum_sha256'].lower()}"})
                for tag in item["tags"]:
                    batch.delete_item(Key={"PK": f"TAG#{owner_sub}#{tag}", "SK": self.media_sk(media_id)})
                    batch.delete_item(Key={"PK": f"TAGOWNER#{owner_sub}#MEDIA#{media_id}", "SK": f"TAG#{tag}"})
        return deleted

    def subscribe(self, owner_sub: str, species: str) -> bool:
        species = species.lower()
        try:
            self.table.put_item(
                Item={"PK": self.user_pk(owner_sub), "SK": f"SUB#{species}", "entity": "subscription", "owner_sub": owner_sub, "species": species, "created_at": now(), "GSI3PK": f"SUB#{species}", "GSI3SK": owner_sub},
                ConditionExpression="attribute_not_exists(PK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def subscriptions_for(self, species: str) -> list[str]:
        response = self.table.query(IndexName="subscription-index", KeyConditionExpression=Key("GSI3PK").eq(f"SUB#{species.lower()}"))
        return [item["owner_sub"] for item in response.get("Items", [])]

    def record_notification(self, notification_id: str, owner_sub: str, species: str, media_id: str, status: str) -> None:
        self.table.put_item(Item={"PK": self.user_pk(owner_sub), "SK": f"NOTIFICATION#{notification_id}", "entity": "notification", "species": species, "media_id": media_id, "channel": "email", "status": status, "created_at": now()})
