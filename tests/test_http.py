"""The API Lambda, called the way API Gateway calls it (HTTP API v2 events with the claims of a
checked Cognito ID token), against moto's DynamoDB and Parameter Store."""
import json

import boto3
import pytest

from api import http
from digest import env, paper
from digest.dynamo_store import DynamoStore

ALICE = {"sub": "alice-0001", "email": "alice@umich.edu"}
BOB = {"sub": "bob-0002", "email": "bob@umich.edu"}
ADMIN = {"sub": "tiger-0003", "email": "tiger@umich.edu", "cognito:groups": "[admins]"}
SETTINGS = {"name": "Alice's digest", "topic": "graph neural networks for spatial omics",
            "sources": {"pubmed": {"enabled": True}}, "delivery": {"email": True}}
WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXX"


def call(method, path, body=None, claims=ALICE, raw=None):
    event = {"rawPath": path, "requestContext": {"http": {"method": method}}}
    if claims:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    if body is not None or raw is not None:
        event["body"] = raw if raw is not None else json.dumps(body)
    r = http.handler(event, None)
    return r["statusCode"], json.loads(r["body"])


@pytest.fixture(autouse=True)
def api(dynamo_table, monkeypatch):
    monkeypatch.setattr(http, "_store", None)
    previous = env.use(env.EnvSecrets())
    yield
    env.use(previous)


def ssm_names():
    ssm = boto3.client("ssm", region_name="us-east-2")
    return {p["Name"]: p["Type"] for p in ssm.get_parameters_by_path(Path="/litfetch")["Parameters"]}


def test_health_needs_no_login_everything_else_does():
    assert call("GET", "/health", claims=None) == (200, {"ok": True})
    assert call("GET", "/me", claims=None)[0] == 401


def test_unknown_routes_and_bad_bodies():
    assert call("GET", "/nope")[0] == 404
    assert call("POST", "/me")[0] == 405
    assert call("PUT", "/me/preferences", raw="{not json")[1]["error"] == "bad_json"
    assert call("PUT", "/me/preferences", raw="[1, 2]")[1]["error"] == "bad_json"


def test_new_user_has_no_settings():
    status, body = call("GET", "/me")
    assert status == 200
    assert body == {"id": "alice-0001", "email": "alice@umich.edu", "admin": False,
                    "settings": None, "has_webhook": False, "paused": False}


def test_save_and_read_back_settings():
    status, body = call("PUT", "/me/preferences", SETTINGS)
    assert status == 200 and body["settings"]["name"] == "Alice's digest"
    assert call("GET", "/me")[1]["settings"]["topic"] == SETTINGS["topic"]
    prefs = DynamoStore().load_preferences("alice-0001").to_sub()
    assert prefs["outputs"]["email"]["to"] == ["alice@umich.edu"]      # their address, from the token
    assert DynamoStore().list_subscribers() == ["alice-0001"]


def test_users_only_see_their_own_settings():
    call("PUT", "/me/preferences", SETTINGS)
    assert call("GET", "/me", claims=BOB)[1]["settings"] is None


@pytest.mark.parametrize("change", [{"model": "x"}, {"outputs": {"slack": {"webhook_env": "SLACK_WEBHOOK_URL"}}},
                                    {"max_papers": 99}, {"topic": None}])
def test_unsafe_or_bad_settings_are_refused(change):
    status, body = call("PUT", "/me/preferences", {**SETTINGS, **change})
    assert status == 400 and body["error"] == "invalid" and body["fields"]


def test_paused_users_are_skipped_by_the_weekly_round():
    call("PUT", "/me/preferences", {**SETTINGS, "paused": True})
    assert call("GET", "/me")[1]["paused"] is True
    assert DynamoStore().list_subscribers() == []


def test_slack_webhook_lifecycle():
    status, body = call("PUT", "/me/preferences", {**SETTINGS, "delivery": {"slack": True}})
    assert status == 400 and "webhook first" in body["message"]
    assert call("PUT", "/me/webhook", {"url": "https://evil.example/hook"})[0] == 400
    assert call("PUT", "/me/webhook", {"url": WEBHOOK}) == (200, {"has_webhook": True})
    assert ssm_names() == {"/litfetch/SLACK_WEBHOOK_alice_0001": "SecureString"}
    me = call("GET", "/me")[1]
    assert me["has_webhook"] is True and WEBHOOK not in json.dumps(me)     # never sent back
    assert call("PUT", "/me/preferences", {**SETTINGS, "delivery": {"slack": True}})[0] == 200
    assert call("DELETE", "/me/webhook") == (200, {"has_webhook": False})
    assert ssm_names() == {}
    assert call("GET", "/me")[1]["settings"]["delivery"]["slack"] is False


def test_preview_searches_without_saving(monkeypatch):
    from digest import sources
    seen = {}
    def search_all(sub):
        seen.update(sub)
        return [paper.new("PubMed", f"Paper number {i} about spatial graph learning methods", doi=f"10.1/{i}")
                for i in range(7)], {"PubMed": 7, "arXiv": RuntimeError("429")}
    monkeypatch.setattr(sources, "search_all", search_all)
    status, body = call("POST", "/me/preview", SETTINGS)
    assert status == 200 and body["count"] == 7 and len(body["examples"]) == 5
    assert body["found"] == {"PubMed": 7, "arXiv": "failed: 429"}
    assert seen["candidate_pool"] == 20 and seen["id"] == "alice-0001"
    assert DynamoStore().load_preferences("alice-0001") is None             # nothing saved
    assert call("POST", "/me/preview")[0] == 404                            # no body, nothing saved


def test_test_delivery_sends_to_their_chats_three_times_a_day(monkeypatch):
    from digest.notify import mail, slack
    sent = []
    monkeypatch.setattr(slack, "send", lambda url, text: sent.append(("slack", url)))
    monkeypatch.setattr(mail, "send", lambda to, msg: sent.append(("email", tuple(to))))
    assert call("PUT", "/me/webhook", {"url": WEBHOOK})[0] == 200
    call("PUT", "/me/preferences", {**SETTINGS, "delivery": {"slack": True, "email": True}})
    assert call("POST", "/me/test-delivery") == (200, {"sent": ["slack", "email"], "failed": {}})
    assert sent == [("slack", WEBHOOK), ("email", ("alice@umich.edu",))]     # URL read from Parameter Store
    call("POST", "/me/test-delivery"), call("POST", "/me/test-delivery")
    assert call("POST", "/me/test-delivery")[0] == 429


def test_digests_lists_what_was_sent_newest_first():
    call("PUT", "/me/preferences", SETTINGS)
    a = paper.new("PubMed", "A paper that was sent to Alice last week", doi="10.1/a", journal="J")
    b = paper.new("PubMed", "A candidate that was not sent to Alice", doi="10.1/b", journal="J")
    for p in (a, b):
        p.update(score=0.5, keyword_hits=[], summary="Short summary.")
    DynamoStore().save_history("alice-0001", [a, b], posted=[a])
    (day,) = call("GET", "/me/digests")[1]["digests"]
    assert [p["title"] for p in day["papers"]] == [a["title"]] and day["papers"][0]["summary"] == "Short summary."
    assert call("GET", "/me/digests", claims=BOB)[1]["digests"] == []


def test_delete_account_removes_everything():
    call("PUT", "/me/preferences", SETTINGS)
    call("PUT", "/me/webhook", {"url": WEBHOOK})
    DynamoStore().add_seen("alice-0001", {"x"})
    assert call("DELETE", "/me") == (200, {"deleted_items": 2})
    assert DynamoStore().load_preferences("alice-0001") is None and ssm_names() == {}


def test_invites_are_admin_only():
    assert call("POST", "/admin/invites", {"count": 2})[0] == 403
    status, body = call("POST", "/admin/invites", {"count": 2, "days": 7, "note": "lab"}, claims=ADMIN)
    assert status == 200 and len(body["codes"]) == 2
    invites = call("GET", "/admin/invites", claims=ADMIN)[1]["invites"]
    assert {i["code"] for i in invites} == set(body["codes"]) and invites[0]["created_by"] == "tiger@umich.edu"
    assert call("POST", "/admin/invites", {"count": 500}, claims=ADMIN)[0] == 400


def test_errors_do_not_leak_details(monkeypatch):
    monkeypatch.setattr(http, "_settings_of", lambda user: 1 / 0)
    status, body = call("GET", "/me")
    assert status == 500 and body == {"error": "internal", "message": "something went wrong; it has been logged"}
