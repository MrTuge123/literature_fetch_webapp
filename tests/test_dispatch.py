"""The dispatch Lambda queues one FIFO message per subscriber, in one group, deduplicated per day."""
import json

import boto3
import pytest

from api import dispatch
from digest.dynamo_store import DynamoStore
from digest.prefs import Preferences
from tests.test_prefs import merged


@pytest.fixture
def queue(dynamo_table, monkeypatch):
    sqs = boto3.client("sqs", region_name="us-east-2")
    url = sqs.create_queue(QueueName="litfetch-jobs.fifo",
                           Attributes={"FifoQueue": "true"})["QueueUrl"]
    monkeypatch.setenv("LITFETCH_QUEUE_URL", url)
    return sqs, url


def add_users(*ids):
    ds = DynamoStore()
    for sid in ids:
        ds.save_preferences(Preferences.model_validate({**merged("subscribers/_template.yaml"), "id": sid}))


def received(sqs, url):
    out = []
    while True:
        r = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10,
                                MessageSystemAttributeNames=["MessageGroupId"])
        if not r.get("Messages"):
            return out
        for m in r["Messages"]:
            out.append((json.loads(m["Body"]), m["Attributes"]["MessageGroupId"]))
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])


def test_queues_one_job_per_subscriber_in_one_group(queue):
    sqs, url = queue
    add_users("b_lab", "a_lab")
    DynamoStore().add_seen("left_lab", {"x"})                # data but no PREFS: not a subscriber
    assert dispatch.handler({}, None) == {"queued": ["a_lab", "b_lab"]}
    msgs = received(sqs, url)
    assert sorted(m[0]["user"] for m in msgs) == ["a_lab", "b_lab"]
    assert {m[1] for m in msgs} == {"weekly-digest"}          # one group = one at a time
    assert all("dry_run" not in m[0] for m in msgs)           # the worker's default decides


def test_some_users_and_a_dry_run_flag(queue):
    sqs, url = queue
    add_users("a_lab", "b_lab", "c_lab")
    assert dispatch.handler({"users": ["c_lab"], "dry_run": True}, None) == {"queued": ["c_lab"]}
    assert received(sqs, url) == [({"user": "c_lab", "dry_run": True}, "weekly-digest")]


def test_unknown_users_are_refused(queue):
    add_users("a_lab")
    with pytest.raises(LookupError, match="nobody"):
        dispatch.handler({"users": ["a_lab", "nobody"]}, None)


def test_more_than_ten_users_and_no_duplicates_the_same_day(queue):
    sqs, url = queue
    add_users(*[f"lab{i:02d}" for i in range(23)])
    assert len(dispatch.handler({}, None)["queued"]) == 23
    dispatch.handler({}, None)                                # retried right away
    assert len(received(sqs, url)) == 23                      # FIFO deduplication dropped the repeats


def test_needs_the_queue_url(dynamo_table, monkeypatch):
    monkeypatch.delenv("LITFETCH_QUEUE_URL", raising=False)
    add_users("a_lab")
    with pytest.raises(RuntimeError, match="LITFETCH_QUEUE_URL"):
        dispatch.handler({}, None)


def test_dispatch_to_worker_round_trip(queue, monkeypatch):
    """What AWS does each Monday: dispatch queues jobs, SQS hands each one to the worker."""
    from api import worker
    from digest import env
    sqs, url = queue
    add_users("a_lab", "b_lab")
    runs = []
    monkeypatch.setattr(worker, "run_subscriber", lambda p, store, secrets, dry_run: runs.append((p.id, dry_run)) or [])
    monkeypatch.setattr(worker, "_store", None)
    monkeypatch.setattr(worker, "_secrets", None)
    previous = env.use(env.EnvSecrets())
    try:
        dispatch.handler({}, None)
        while True:                                               # like the event source: 1 message per run
            r = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1)
            if not r.get("Messages"):
                break
            m = r["Messages"][0]
            out = worker.handler({"Records": [{"messageId": m["MessageId"], "body": m["Body"]}]}, None)
            assert out == {"batchItemFailures": []}
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    finally:
        env.use(previous)
    assert runs == [("a_lab", True), ("b_lab", True)]             # in order, dry runs until M9
