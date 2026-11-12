"""The API Lambda, called the way API Gateway calls it (HTTP API v2 events with the claims of a
checked Cognito ID token), against moto's DynamoDB and Parameter Store."""
import json

import boto3
import pytest

from api import http
from digest import env, history, paper
from digest.dynamo_store import DynamoStore

ALICE = {"sub": "alice-0001", "email": "alice@umich.edu"}
BOB = {"sub": "bob-0002", "email": "bob@umich.edu"}
ADMIN = {"sub": "tiger-0003", "email": "tiger@umich.edu", "cognito:groups": "[admins]"}
SETTINGS = {"name": "Alice's digest", "topic": "graph neural networks for spatial omics",
            "sources": {"pubmed": {"enabled": True}}, "delivery": {"email": True}}
WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXX"


def call(method, path, body=None, claims=ALICE, raw=None, query=None):
    event = {"rawPath": path, "requestContext": {"http": {"method": method}}}
    if query:
        event["queryStringParameters"] = query
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


def test_graph_links_a_digest_to_earlier_papers():
    def p(title, doi, refs, oa=None):
        x = paper.new("PubMed", title, doi=doi, journal="J", openalex_id=oa)
        x.update(score=0.5, keyword_hits=[], references=refs, relevance=8)
        return x
    old = p("An earlier paper on spatial graph learning methods", "10.1/old", ["W1", "W2"], oa="W50")
    new = p("This week's paper on spatial graph learning methods", "10.1/new", ["W1", "W2", "W50"])
    store = DynamoStore()
    store.merge_history("alice-0001", history.new_records([old], [old], today="2026-11-02"))
    store.merge_history("alice-0001", history.new_records([new], [new], today="2026-11-09"))
    status, g = call("GET", "/me/graph")
    assert status == 200 and g["date"] == "2026-11-09"
    assert [n["title"] for n in g["nodes"]] == [new["title"], old["title"]]
    assert [(e["shared"], e["direct"]) for e in g["edges"]] == [(2, True)]
    assert call("GET", "/me/graph", query={"date": "2026-11-02"})[1]["nodes"][0]["title"] == old["title"]
    assert call("GET", "/me/graph", query={"date": "2026-11-01"})[1]["error"] == "no_digest"
    assert call("GET", "/me/graph", query={"date": "last week"})[1]["error"] == "invalid"
    assert call("GET", "/me/graph", claims=BOB)[0] == 404              # only ever their own history


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


# ---------- invite requests ----------

REQUEST = {"name": "Ann Lee", "email": "Ann@UMich.edu", "note": "PhD student, cardiology"}


@pytest.fixture
def sent(monkeypatch):
    """Emails the API sends, as (to, subject, text); SMTP login of the bot in the environment."""
    out = []
    monkeypatch.setattr(http, "_send_email", lambda to, subject, text: out.append((to, subject, text)))
    boto3.client("ssm", region_name="us-east-2").put_parameter(      # the API reads Parameter Store
        Name="/litfetch/SMTP_USER", Value="literaturebot@gmail.com", Type="SecureString")
    monkeypatch.setenv("LITFETCH_SITE_URL", "https://site.example/")
    return out


def request(body=REQUEST, ip="1.2.3.4"):
    event = {"rawPath": "/invite-requests", "body": json.dumps(body),
             "requestContext": {"http": {"method": "POST", "sourceIp": ip}}}
    r = http.handler(event, None)
    return r["statusCode"], json.loads(r["body"])


def test_anyone_can_request_an_invite_and_the_bot_is_emailed(sent):
    assert request() == (200, {"ok": True})
    assert [(to, subj) for to, subj, _ in sent] == [("literaturebot@gmail.com", "Invite request: Ann Lee <ann@umich.edu>")]
    assert "PhD student" in sent[0][2] and "https://site.example/admin" in sent[0][2]
    assert request() == (200, {"ok": True}) and len(sent) == 1            # same answer, no second email


def test_invite_request_is_checked(sent):
    assert request({**REQUEST, "email": "not-an-email"})[0] == 400
    assert request({**REQUEST, "name": ""})[0] == 400
    assert request({**REQUEST, "note": "x" * 501})[0] == 400
    assert request({**REQUEST, "website": "http://spam"}) == (200, {"ok": True})   # bot filled the trap
    assert sent == [] and DynamoStore().list_invite_requests() == []


def test_invite_requests_are_limited_per_ip(sent):
    for i in range(http.REQUESTS_PER_IP):
        assert request({**REQUEST, "email": f"p{i}@umich.edu"})[0] == 200
    assert request({**REQUEST, "email": "late@umich.edu"})[0] == 429
    assert request({**REQUEST, "email": "late@umich.edu"}, ip="5.6.7.8")[0] == 200


def test_admin_approves_a_request_and_the_person_gets_a_link(sent):
    request()
    assert call("GET", "/admin/invite-requests")[0] == 403                # admins only
    reqs = call("GET", "/admin/invite-requests", claims=ADMIN)[1]["requests"]
    assert [(r["email"], r["status"]) for r in reqs] == [("ann@umich.edu", "pending")]
    status, body = call("POST", "/admin/invite-requests/approve", {"email": "ann@umich.edu", "days": 7}, claims=ADMIN)
    assert status == 200 and body["emailed"] is True
    assert body["link"] == f"https://site.example/login?invite={body['code']}"
    to, subject, text = sent[-1]
    assert to == "ann@umich.edu" and body["link"] in text and "valid 7 days" in text
    invite = next(i for i in DynamoStore().list_invites() if i["code"] == body["code"])
    assert invite["created_by"] == "tiger@umich.edu" and invite["note"] == "request: Ann Lee"
    assert call("POST", "/admin/invite-requests/approve", {"email": "ann@umich.edu"}, claims=ADMIN)[0] == 409


def test_admin_rejects_a_request(sent):
    request()
    assert call("POST", "/admin/invite-requests/reject", {"email": "ann@umich.edu"}, claims=ADMIN) == (200, {"status": "rejected"})
    assert DynamoStore().get_invite_request("ann@umich.edu")["status"] == "rejected"
    assert call("POST", "/admin/invite-requests/reject", {"email": "ann@umich.edu"}, claims=ADMIN)[0] == 409
    assert len(sent) == 1                                                  # only the bot's notice


def test_approval_still_returns_the_code_if_the_email_fails(sent, monkeypatch):
    request()
    monkeypatch.setattr(http, "_send_email", lambda *a: (_ for _ in ()).throw(RuntimeError("SMTP down")))
    status, body = call("POST", "/admin/invite-requests/approve", {"email": "ann@umich.edu"}, claims=ADMIN)
    assert status == 200 and body["emailed"] is False and "SMTP down" in body["email_error"] and body["code"]
