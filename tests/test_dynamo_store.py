"""DynamoDB-only behavior: item layout, TTL, minimal writes, preferences."""
import copy
import time

import pytest

from digest import paper
from tests.test_prefs import FILES, merged
from tests.test_store_contract import A, B

pytest.importorskip("moto")
from digest.dynamo_store import SEEN_TTL_DAYS, DynamoStore, from_dynamo, to_dynamo  # noqa: E402
from digest.prefs import Preferences  # noqa: E402


@pytest.fixture
def ds(dynamo_table):
    return DynamoStore()


def items(table):
    return sorted(table.scan()["Items"], key=lambda i: (i["PK"], i["SK"]))


def test_decimal_round_trip_keeps_types():
    data = {"a": 7, "b": 7.5, "c": 7.0, "d": [0.3, 2], "e": None, "f": "x", "g": True}
    assert from_dynamo(to_dynamo(data)) == data
    assert [type(v) for v in from_dynamo(to_dynamo(data)).values()] == [int, float, float, list, type(None), str, bool]


def test_item_layout(ds, dynamo_table):
    ds.add_seen("lab", {"10.1/a"})
    ds.save_history("lab", [A], posted=[A])
    keys = [(i["PK"], i["SK"]) for i in items(dynamo_table)]
    assert ("USER#lab", "SEEN#10.1/a") in keys
    assert ("USER#lab", "HIST#" + min(paper.ids(A))) in keys


def test_seen_items_expire_after_more_than_a_year(ds, dynamo_table):
    ds.add_seen("lab", {"10.1/a"})
    (item,) = items(dynamo_table)
    days = (int(item["ttl"]) - time.time()) / 86400
    assert 365 < days <= SEEN_TTL_DAYS


def test_an_unchanged_run_writes_nothing(ds, dynamo_table, monkeypatch):
    ds.save_history("lab", [A, B], posted=[A])
    writes = []
    real = dynamo_table.meta.client.batch_write_item
    monkeypatch.setattr(dynamo_table.meta.client, "batch_write_item",
                        lambda **kw: writes.append(kw) or real(**kw))
    ds.merge_history("lab", copy.deepcopy(ds.load_history("lab")))   # the same records again
    ds.add_seen("lab", set())
    assert writes == []


@pytest.mark.parametrize("path", FILES)
def test_preferences_round_trip_for_every_settings_file(ds, path):
    prefs = Preferences.model_validate(merged(path))
    assert ds.save_preferences(prefs) is True
    back = ds.load_preferences(prefs.id)
    expected = {k: v for k, v in prefs.to_sub().items() if k != "file"}
    assert back.to_sub() == expected                          # floats, ints, lists, None all survive


def test_save_preferences_can_refuse_to_overwrite(ds):
    prefs = Preferences.model_validate(merged("subscribers/_template.yaml"))
    assert ds.save_preferences(prefs) is True
    changed = prefs.model_copy(update={"name": "Changed"})
    assert ds.save_preferences(changed, overwrite=False) is False
    assert ds.load_preferences(prefs.id).name == prefs.name


def test_list_subscribers_and_missing_preferences(ds):
    assert ds.load_preferences("nobody") is None
    for sid in ("b_lab", "a_lab"):
        ds.save_preferences(Preferences.model_validate({**merged("subscribers/_template.yaml"), "id": sid}))
    ds.add_seen("c_lab", {"x"})                               # seen only: not a subscriber
    assert ds.list_subscribers() == ["a_lab", "b_lab"]


# ---- M5: accounts and invites ----

def template_prefs(sid):
    return Preferences.model_validate({**merged("subscribers/_template.yaml"), "id": sid})


def test_paused_subscribers_are_left_out_of_the_round(ds):
    ds.save_preferences(template_prefs("a_lab"))
    ds.save_preferences(template_prefs("b_lab"), paused=True, email="b@umich.edu")
    assert ds.list_subscribers() == ["a_lab"]
    assert ds.list_subscribers(include_paused=True) == ["a_lab", "b_lab"]
    assert ds.profile("b_lab")["paused"] is True and ds.profile("b_lab")["email"] == "b@umich.edu"
    assert ds.profile("a_lab")["paused"] is False and ds.profile("nobody") is None


def test_delete_user_removes_everything_of_theirs_only(ds, dynamo_table):
    ds.save_preferences(template_prefs("a_lab"))
    ds.add_seen("a_lab", {"x", "y"})
    ds.save_history("a_lab", [A], posted=[A])
    ds.add_seen("other", {"z"})
    assert ds.delete_user("a_lab") == 4
    assert [i["PK"] for i in dynamo_table.scan()["Items"]] == ["USER#other"]


def test_daily_quota(ds):
    assert [ds.take_quota("a", "test", 3) for _ in range(4)] == [True, True, True, False]
    assert ds.take_quota("b", "test", 3) is True                     # per user


def test_invites_are_single_use(ds):
    code, = ds.create_invites(1, days=7, created_by="tiger", note="lab")
    assert ds.use_invite(code.lower(), "new@umich.edu") is True      # case doesn't matter
    assert ds.use_invite(code, "again@umich.edu") is False           # already used
    assert ds.use_invite("NOPE1234", "x@umich.edu") is False and ds.use_invite("", "x") is False
    (inv,) = ds.list_invites()
    assert inv["code"] == code and inv["used_by"] == "new@umich.edu" and inv["note"] == "lab"


def test_expired_invites_are_refused(ds):
    code, = ds.create_invites(1, days=-1)
    assert ds.use_invite(code, "late@umich.edu") is False
