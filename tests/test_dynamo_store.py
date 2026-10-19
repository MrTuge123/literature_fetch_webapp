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
