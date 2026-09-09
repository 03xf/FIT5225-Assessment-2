import json

from app.config import Settings
from app.services.notifications import ensure_email_subscription


class FakeDatabase:
    def __init__(self):
        self.records = []

    def subscriptions_for_owner(self, owner_sub):
        assert owner_sub == "user-a"
        return ["alectura_lathami", "casuarius_casuarius"]

    def upsert_sns_subscription(self, owner_sub, email, subscription_arn, status):
        self.records.append((owner_sub, email, subscription_arn, status))


class FakePaginator:
    def paginate(self, **_kwargs):
        return [{"Subscriptions": [{"Endpoint": "user@example.com", "SubscriptionArn": "arn:aws:sns:subscription"}]}]


class FakeSns:
    def __init__(self):
        self.attributes = []
        self.subscribe_called = False

    def get_paginator(self, name):
        assert name == "list_subscriptions_by_topic"
        return FakePaginator()

    def get_subscription_attributes(self, **_kwargs):
        return {"Attributes": {"FilterPolicy": json.dumps({"species": ["felis_catus"]})}}

    def set_subscription_attributes(self, **kwargs):
        self.attributes.append(kwargs)

    def subscribe(self, **_kwargs):
        self.subscribe_called = True
        raise AssertionError("An existing email subscription must be reused")


def test_existing_email_subscription_merges_species_filter(monkeypatch):
    sns = FakeSns()
    monkeypatch.setattr("boto3.client", lambda *_args, **_kwargs: sns)
    database = FakeDatabase()
    settings = Settings(sns_topic_arn="arn:aws:sns:topic", aws_region="ap-southeast-2")

    result = ensure_email_subscription(settings, database, "user-a", "user@example.com")

    assert result.confirmation_pending is False
    assert result.state == "active"
    assert sns.subscribe_called is False
    assert json.loads(sns.attributes[0]["AttributeValue"]) == {
        "species": ["alectura_lathami", "casuarius_casuarius", "felis_catus"]
    }
    assert database.records == [("user-a", "user@example.com", "arn:aws:sns:subscription", "CONFIRMED")]


def test_deleted_email_subscription_is_recreated(monkeypatch):
    class DeletedPaginator:
        def paginate(self, **_kwargs):
            return [{"Subscriptions": [{"Endpoint": "user@example.com", "SubscriptionArn": "Deleted"}]}]

    class DeletedSns:
        def get_paginator(self, name):
            assert name == "list_subscriptions_by_topic"
            return DeletedPaginator()

        def subscribe(self, **kwargs):
            assert json.loads(kwargs["Attributes"]["FilterPolicy"]) == {
                "species": ["alectura_lathami", "casuarius_casuarius"]
            }
            return {"SubscriptionArn": "PendingConfirmation"}

    monkeypatch.setattr("boto3.client", lambda *_args, **_kwargs: DeletedSns())
    database = FakeDatabase()
    settings = Settings(sns_topic_arn="arn:aws:sns:topic", aws_region="ap-southeast-2")

    result = ensure_email_subscription(settings, database, "user-a", "user@example.com")

    assert result.confirmation_pending is True
    assert database.records == [("user-a", "user@example.com", "PendingConfirmation", "PENDING")]
