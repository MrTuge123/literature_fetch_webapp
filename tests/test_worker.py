"""The worker Lambda handler: finds the user's settings in DynamoDB, secrets in Parameter Store,
runs the pipeline, defaults to a dry run, and reports failures the way SQS expects."""
import json

import boto3
import pytest

from api import worker
from digest import env
from digest.dynamo_store import DynamoStore
from digest.ssm_secrets import ParameterStoreSecrets
from tests.test_pipeline import A, B, WEBHOOK, prefs, world  # noqa: F401  (world is a fixture)


@pytest.fixture
def lambda_env(dynamo_table, monkeypatch):
    """A table with user 'lab', its webhook in Parameter Store, and a fresh worker module state."""
    boto3.client("ssm", region_name="us-east-2").put_parameter(
        Name="/litfetch/SLACK_WEBHOOK_URL", Value=WEBHOOK, Type="SecureString")
    DynamoStore().save_preferences(prefs())
    monkeypatch.setattr(worker, "_store", None)
    monkeypatch.setattr(worker, "_secrets", None)
    previous = env.use(env.EnvSecrets())
    yield
    env.use(previous)


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "run_subscriber",
                        lambda p, store, secrets, dry_run: seen.append((p, store, secrets, dry_run)) or [])
    return seen


def test_direct_invoke_is_a_dry_run_by_default(lambda_env, calls):
    assert worker.handler({"user": "lab"}, None) == {"user": "lab", "dry_run": True, "failed": []}
    (p, store, secrets, dry), = calls
    assert p.id == "lab" and p.max_papers == 2
    assert isinstance(store, DynamoStore) and isinstance(secrets, ParameterStoreSecrets)
    assert env.get("SLACK_WEBHOOK_URL") == WEBHOOK            # every module now reads Parameter Store


def test_dry_run_can_be_turned_off(lambda_env, calls, monkeypatch):
    worker.handler({"user": "lab", "dry_run": False}, None)
    monkeypatch.setenv("LITFETCH_DRY_RUN_DEFAULT", "false")   # after the cut-over
    worker.handler({"user": "lab"}, None)
    assert [c[3] for c in calls] == [False, False]


def test_bad_jobs_raise_clear_errors(lambda_env, calls):
    with pytest.raises(ValueError, match="needs a user"):
        worker.handler({}, None)
    with pytest.raises(LookupError, match="nobody"):
        worker.handler({"user": "nobody"}, None)
    assert calls == []


def test_sqs_batch_reports_only_the_failed_messages(lambda_env, calls):
    event = {"Records": [{"messageId": "m1", "body": json.dumps({"user": "lab"})},
                         {"messageId": "m2", "body": json.dumps({"user": "nobody"})},
                         {"messageId": "m3", "body": "not json"}]}
    assert worker.handler(event, None) == {"batchItemFailures": [{"itemIdentifier": "m2"},
                                                                 {"itemIdentifier": "m3"}]}
    assert len(calls) == 1


def test_end_to_end_with_the_real_pipeline(lambda_env, world):
    """Nothing mocked between the handler and the pipeline: webhook from SSM, state in DynamoDB."""
    result = worker.handler({"user": "lab", "dry_run": False}, None)
    assert result == {"user": "lab", "dry_run": False, "failed": []}
    (url, text), = world["slack"]
    assert url == WEBHOOK and A["title"] in text
    from digest import paper
    assert DynamoStore().load_seen("lab") == paper.ids(A) | paper.ids(B)
