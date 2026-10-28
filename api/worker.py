"""Worker Lambda: one subscriber's digest per job.

    {"user": "wang_lab"}                     run it (dry run unless told otherwise, see below)
    {"user": "wang_lab", "dry_run": false}   really post and save
    an SQS event whose message bodies are those JSON objects (M4: the weekly queue)

dry_run defaults to true until the M9 cut-over, because the old slack_post repo still sends the
real digest; set the function's LITFETCH_DRY_RUN_DEFAULT=false then. A dry run prints the
messages to the logs (CloudWatch) and saves nothing.

Settings come from the subscriber's PREFS item, seen papers and history from DynamoDB, API keys
and webhook URLs from Parameter Store (/litfetch/<NAME>)."""
import json
import os
import traceback

from digest import env
from digest.pipeline import run_subscriber

_store = _secrets = None          # created on the first job, then reused while the Lambda is warm


def _deps():
    global _store, _secrets
    if _store is None:
        from digest.dynamo_store import DynamoStore
        from digest.ssm_secrets import ParameterStoreSecrets
        _store, _secrets = DynamoStore(), ParameterStoreSecrets()
        env.use(_secrets)
    return _store, _secrets


def _dry_run(job):
    if "dry_run" in job:
        return bool(job["dry_run"])
    return os.getenv("LITFETCH_DRY_RUN_DEFAULT", "true").lower() != "false"


def run_job(job):
    """One subscriber's digest. Returns {"user", "dry_run", "failed": [chats that failed]}."""
    user = job.get("user") if isinstance(job, dict) else None
    if not user:
        raise ValueError('a job needs a user, e.g. {"user": "wang_lab"}')
    store, secrets = _deps()
    prefs = store.load_preferences(user)
    if prefs is None:
        raise LookupError(f"no settings (PREFS item) for user {user!r}")
    dry = _dry_run(job)
    failed = run_subscriber(prefs, store, secrets, dry_run=dry)
    if failed:
        print(f"Warning: {user}: posting failed for {', '.join(failed)}")
    return {"user": user, "dry_run": dry, "failed": failed}


def handler(event, context):
    if isinstance(event, dict) and "Records" in event:        # SQS: report each failed message
        failures = []
        for record in event["Records"]:
            try:
                run_job(json.loads(record["body"]))
            except Exception:
                traceback.print_exc()
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}
    return run_job(event)
