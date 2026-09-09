"""SNS email subscription reconciliation for species notifications."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from app.config import Settings


@dataclass(frozen=True)
class EmailSubscriptionStatus:
    confirmation_pending: bool
    state: str


def _is_arn(value: str | None) -> bool:
    return bool(value and value.startswith("arn:"))


def _find_email_subscription(client: Any, topic_arn: str, email: str) -> dict[str, Any] | None:
    paginator = client.get_paginator("list_subscriptions_by_topic")
    for page in paginator.paginate(TopicArn=topic_arn):
        for subscription in page.get("Subscriptions", []):
            if str(subscription.get("Endpoint", "")).casefold() == email.casefold():
                return subscription
    return None


def _filter_species(client: Any, subscription_arn: str) -> set[str]:
    raw_policy = client.get_subscription_attributes(SubscriptionArn=subscription_arn)["Attributes"].get("FilterPolicy")
    if not raw_policy:
        return set()
    try:
        values = json.loads(raw_policy).get("species", [])
    except (TypeError, ValueError):
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def ensure_email_subscription(settings: Settings, database: Any, owner_sub: str, email: str | None) -> EmailSubscriptionStatus:
    """Keep one SNS email subscription per archive user and merge its species filter.

    Older deployments stored per-species records without the SNS subscription
    ARN. Looking up the existing email endpoint migrates it lazily and avoids
    SNS rejecting a duplicate endpoint with a different filter policy.
    """
    if not settings.sns_topic_arn or not email:
        return EmailSubscriptionStatus(confirmation_pending=False, state="not-configured")

    species = database.subscriptions_for_owner(owner_sub)
    if not species:
        return EmailSubscriptionStatus(confirmation_pending=False, state="not-configured")

    import boto3

    client = boto3.client("sns", region_name=settings.aws_region)
    existing = _find_email_subscription(client, settings.sns_topic_arn, email)
    if existing:
        subscription_arn = str(existing.get("SubscriptionArn", ""))
        if _is_arn(subscription_arn):
            merged = sorted(_filter_species(client, subscription_arn) | set(species))
            client.set_subscription_attributes(
                SubscriptionArn=subscription_arn,
                AttributeName="FilterPolicy",
                AttributeValue=json.dumps({"species": merged}),
            )
            database.upsert_sns_subscription(owner_sub, email, subscription_arn, "CONFIRMED")
            return EmailSubscriptionStatus(confirmation_pending=False, state="active")

        if subscription_arn == "PendingConfirmation":
            database.upsert_sns_subscription(owner_sub, email, subscription_arn, "PENDING")
            return EmailSubscriptionStatus(confirmation_pending=True, state="confirmation-pending")
        # SNS retains a Deleted placeholder after an unsubscribe. It cannot
        # receive notifications or be updated, so create a fresh subscription.

    subscribe_args = {
        "TopicArn": settings.sns_topic_arn,
        "Protocol": "email",
        "Endpoint": email,
        "ReturnSubscriptionArn": True,
    }
    try:
        response = client.subscribe(
            **subscribe_args,
            Attributes={"FilterPolicy": json.dumps({"species": sorted(species)})},
        )
    except ClientError as error:
        message = error.response.get("Error", {}).get("Message", "")
        if "Subscription already exists with different attributes" not in message:
            raise
        # SNS can retain old subscription attributes after an unsubscribe even
        # when ListSubscriptions reports Deleted. Retrying without attributes
        # sends a fresh confirmation; after confirmation, a later request
        # reconciles the merged filter policy through the real ARN.
        response = client.subscribe(**subscribe_args)
    subscription_arn = str(response.get("SubscriptionArn", "PendingConfirmation"))
    # Email protocol subscriptions require the recipient to confirm delivery.
    # SNS can return an ARN before that confirmation, so it is not evidence
    # that notifications are active yet.
    database.upsert_sns_subscription(owner_sub, email, subscription_arn, "PENDING")
    return EmailSubscriptionStatus(confirmation_pending=True, state="confirmation-pending")
