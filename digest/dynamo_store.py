"""DynamoStore: the Store (digest/storage.py) on the LitFetch DynamoDB table, plus what the
website needs on top (preferences, the list of subscribers). Same behavior as FileStore: the
tests in tests/test_store_contract.py run against both.

Items (PK = USER#<subscriber id>):
    SK = PREFS               {"name", "settings": <Preferences.to_sub() minus id/file>, "updated_at"}
    SK = SEEN#<paper id>     {"sent_at", "ttl"}   one per ID (PMID, DOI, arxiv:..., title:...)
    SK = HIST#<paper id>     {"record": <digest.history.record>}   id = the record's smallest ID

DynamoDB has no float type: numbers go in as Decimal and come back as int (7) or float (7.5)
exactly as they went in (to_dynamo / from_dynamo)."""
import datetime as dt
import hashlib
import json
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from digest import history
from digest.prefs import Preferences

DEFAULT_TABLE = "LitFetch"
REGION = "us-east-2"
SEEN_TTL_DAYS = 400        # longer than any days_back (max 365), so an expired ID can't come back in a search


def to_dynamo(obj):
    """JSON-like data -> what boto3 accepts: floats become Decimal('7.5'), ints stay ints."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def from_dynamo(obj):
    """What boto3 returns -> plain Python: Decimal('7') -> 7, Decimal('7.5') -> 7.5, Decimal('7.0') -> 7.0."""
    if isinstance(obj, list):
        return [from_dynamo(v) for v in obj]
    if isinstance(obj, dict):
        return {k: from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj.as_tuple().exponent >= 0 else float(obj)
    return obj


def _pk(sid):
    return f"USER#{sid}"


def _hist_sk(r):
    """One stable key per paper: its smallest ID (records are merged on shared IDs, so a paper's
    smallest ID only changes when two records merge, and then the old item is deleted)."""
    if r.get("ids"):
        return "HIST#" + min(r["ids"])
    return "HIST#untitled:" + hashlib.sha1((r.get("title") or "").encode()).hexdigest()[:16]


class DynamoStore:
    def __init__(self, table_name=None, session=None, region=REGION):
        """table_name: default $LITFETCH_TABLE or LitFetch. session: e.g.
        boto3.Session(profile_name="litfetch") locally; the default (the Lambda's role) on AWS."""
        session = session or boto3.Session()
        name = table_name or os.getenv("LITFETCH_TABLE") or DEFAULT_TABLE
        self.table = session.resource("dynamodb", region_name=region).Table(name)

    def _query(self, sid, prefix):
        """Every item of this subscriber whose SK starts with prefix (all pages)."""
        kw = {"KeyConditionExpression": Key("PK").eq(_pk(sid)) & Key("SK").begins_with(prefix)}
        items = []
        while True:
            r = self.table.query(**kw)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                return items
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    # ---- seen ----

    def load_seen(self, sid):
        return {i["SK"][len("SEEN#"):] for i in self._query(sid, "SEEN#")}

    def add_seen(self, sid, ids):
        new = set(ids) - self.load_seen(sid)                 # only write what isn't there yet
        if not new:
            return
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        expires = int(time.time()) + SEEN_TTL_DAYS * 86400
        with self.table.batch_writer() as b:
            for i in sorted(new):
                b.put_item(Item={"PK": _pk(sid), "SK": "SEEN#" + i, "sent_at": today, "ttl": expires})

    # ---- history ----

    def _history(self, sid):
        """{SK: record} as stored."""
        return {i["SK"]: from_dynamo(i["record"]) for i in self._query(sid, "HIST#")}

    def load_history(self, sid):
        """One record per paper, oldest first (by first_seen, like the file's order)."""
        return sorted(self._history(sid).values(), key=lambda r: r.get("first_seen") or "")

    def save_history(self, sid, ranked, posted):
        self.merge_history(sid, history.new_records(ranked, posted))

    def merge_history(self, sid, records):
        """Add records with the same merge rule as the history/ files (digest.history.combine).
        Writes only items that changed and deletes ones merged into another, so a weekly run
        rewrites ~100 items, not the whole history."""
        self._write(sid, self._history(sid), records)

    def set_references(self, sid, updates):
        if not updates:
            return
        stored = self._history(sid)
        changed = history.apply_references(json.loads(json.dumps(list(stored.values()))), updates)
        self._write(sid, stored, changed, replace=True)

    def _write(self, sid, stored, records, replace=False):
        """Make the subscriber's HIST# items equal combine(stored + records) (or combine(records)
        when replace=True), touching only the items that differ."""
        combined = history.combine(list(records) if replace else list(stored.values()) + list(records))
        want = {_hist_sk(r): r for r in combined}
        with self.table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as b:
            for sk, r in want.items():
                if stored.get(sk) != r:
                    b.put_item(Item={"PK": _pk(sid), "SK": sk, "record": to_dynamo(r)})
            for sk in stored.keys() - want.keys():           # merged into another record
                b.delete_item(Key={"PK": _pk(sid), "SK": sk})

    # ---- preferences (the website and the scheduler use these) ----

    def save_preferences(self, prefs: Preferences, overwrite=True):
        """Store a subscriber's settings. overwrite=False keeps an existing item (returns False)."""
        settings = {k: v for k, v in prefs.to_sub().items() if k not in ("id", "file")}
        item = {"PK": _pk(prefs.id), "SK": "PREFS", "name": prefs.name, "settings": to_dynamo(settings),
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        kw = {} if overwrite else {"ConditionExpression": Attr("PK").not_exists()}
        try:
            self.table.put_item(Item=item, **kw)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def load_preferences(self, sid):
        """The subscriber's Preferences, or None if they have none."""
        item = self.table.get_item(Key={"PK": _pk(sid), "SK": "PREFS"}).get("Item")
        if not item:
            return None
        return Preferences.model_validate({**from_dynamo(item["settings"]), "id": sid})

    def list_subscribers(self):
        """Every subscriber id with a PREFS item (a Scan: fine for a lab, add an index past ~1,000 users)."""
        kw = {"FilterExpression": Attr("SK").eq("PREFS"), "ProjectionExpression": "PK"}
        ids = []
        while True:
            r = self.table.scan(**kw)
            ids += [i["PK"][len("USER#"):] for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return sorted(ids)
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
