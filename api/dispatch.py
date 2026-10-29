"""Dispatch Lambda: start a round of digests by queueing one job per subscriber.

Triggered by the weekly EventBridge schedule (or by hand). Reads every subscriber that has a
PREFS item and sends one message per user to the FIFO queue the worker reads:

    {}                                          everyone, worker decides dry run (its default)
    {"users": ["wang_lab"]}                     just these
    {"dry_run": true}                           pass a dry_run flag on to every job

All messages share one message group, so the worker gets them one at a time (Groq's per-minute
limit can't take several users at once). The deduplication ID is user + date, so if the
schedule fires twice the same day, nobody gets two digests.
"""
import datetime as dt
import json
import os

import boto3

GROUP = "weekly-digest"
BATCH = 10                         # SQS SendMessageBatch takes at most 10 messages


def _queue_url():
    url = os.getenv("LITFETCH_QUEUE_URL")
    if not url:
        raise RuntimeError("LITFETCH_QUEUE_URL is not set (the queue the worker reads)")
    return url


def _users(event):
    from digest.dynamo_store import DynamoStore
    everyone = DynamoStore().list_subscribers()
    wanted = event.get("users")
    if wanted is None:
        return everyone
    unknown = sorted(set(wanted) - set(everyone))
    if unknown:
        raise LookupError(f"no settings (PREFS item) for: {', '.join(unknown)}")
    return [u for u in everyone if u in set(wanted)]


def handler(event, context):
    event = event or {}
    users = _users(event)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-2"))
    url = _queue_url()

    jobs = []
    for user in users:
        job = {"user": user}
        if "dry_run" in event:
            job["dry_run"] = bool(event["dry_run"])
        jobs.append(job)

    failed = []
    for i in range(0, len(jobs), BATCH):
        entries = [{"Id": str(n), "MessageBody": json.dumps(job), "MessageGroupId": GROUP,
                    "MessageDeduplicationId": f"{job['user']}-{today}"}
                   for n, job in enumerate(jobs[i:i + BATCH])]
        r = sqs.send_message_batch(QueueUrl=url, Entries=entries)
        failed += [jobs[i + int(f["Id"])]["user"] for f in r.get("Failed", [])]
    if failed:
        raise RuntimeError(f"could not queue: {', '.join(failed)}")
    print(f"Queued {len(jobs)} digests: {', '.join(users) or '(nobody)'}")
    return {"queued": [j["user"] for j in jobs]}
