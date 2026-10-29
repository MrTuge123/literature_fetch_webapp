"""API Lambda: everything the website calls, behind API Gateway (HTTP API).

Every route except GET /health needs a Cognito ID token (API Gateway checks it before this code
runs). The user is whoever the token says: their id is the token's `sub`, so a request can only
ever read or change that user's own items.

    GET    /health                 {"ok": true}                            no login
    GET    /me                     account, settings (or null), has_webhook, paused
    PUT    /me/preferences         save settings (api/settings.py UserSettings)
    PUT    /me/webhook             save their Slack webhook URL (Parameter Store, never returned)
    DELETE /me/webhook             remove it (and switch Slack off)
    POST   /me/preview             search with their settings now: counts + 5 titles, no LLM ranking
    POST   /me/test-delivery       a short test message to their chats (3 a day)
    GET    /me/digests             papers they were sent, newest first
    DELETE /me                     delete their account and everything stored for it
    GET    /admin/invites          list invite codes                       admins only
    POST   /admin/invites          make invite codes {"count", "days", "note"}

Errors: {"error": "<code>", "message": "..."} with 400 / 401 / 403 / 404 / 405 / 429 / 500.
"""
import base64
import json
import os
import re
import traceback
from email.message import EmailMessage

from pydantic import ValidationError

from api.settings import UserSettings, from_preferences, to_preferences, webhook_secret
from digest import env

SSM_PREFIX = os.getenv("LITFETCH_SSM_PREFIX", "/litfetch/")
WEBHOOK_RE = re.compile(r"^https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{10,200}$")
TEST_MESSAGES_PER_DAY = 3
MAX_BODY = 64 * 1024
ROUTES = {}

_store = _secrets = _ssm = None


class HttpError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class User:
    def __init__(self, claims):
        self.id = claims.get("sub")
        self.email = claims.get("email")
        groups = claims.get("cognito:groups") or ""
        if isinstance(groups, str):                       # API Gateway sends lists as "[a b]"
            groups = groups.strip("[]").replace(",", " ").split()
        self.admin = "admins" in groups


def route(method, path, *, login=True, admin=False):
    def register(fn):
        ROUTES[(method, path)] = (fn, login, admin)
        return fn
    return register


def _deps():
    global _store, _secrets, _ssm
    if _store is None:
        import boto3
        from digest.dynamo_store import DynamoStore
        from digest.ssm_secrets import ParameterStoreSecrets
        _store, _secrets = DynamoStore(), ParameterStoreSecrets()
        _ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-2"))
        env.use(_secrets)
    return _store, _secrets, _ssm


def _reply(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, default=str)}


def _body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    if len(raw) > MAX_BODY:
        raise HttpError(400, "too_large", "request body over 64 KB")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise HttpError(400, "bad_json", "the request body isn't valid JSON")
    if not isinstance(data, dict):
        raise HttpError(400, "bad_json", "the request body must be a JSON object")
    return data


def _has_webhook(user):
    _, _, ssm = _deps()
    try:
        ssm.get_parameter(Name=SSM_PREFIX + webhook_secret(user.id))
        return True
    except ssm.exceptions.ParameterNotFound:
        return False


def _settings_of(user):
    """(UserSettings or None, paused) from their PREFS item."""
    store, _, _ = _deps()
    prefs = store.load_preferences(user.id)
    if prefs is None:
        return None, False
    paused = (store.profile(user.id) or {}).get("paused", False)
    return from_preferences(prefs, paused=paused), paused


# ---------- routes ----------

@route("GET", "/health", login=False)
def health(user, event):
    return {"ok": True}


@route("GET", "/me")
def me(user, event):
    settings, paused = _settings_of(user)
    return {"id": user.id, "email": user.email, "admin": user.admin,
            "settings": settings.model_dump() if settings else None,
            "has_webhook": _has_webhook(user), "paused": paused}


@route("PUT", "/me/preferences")
def save_preferences(user, event):
    store, _, _ = _deps()
    settings = UserSettings.model_validate(_body(event))
    try:
        prefs = to_preferences(user.id, user.email, settings, _has_webhook(user))
    except ValueError as e:
        raise HttpError(400, "invalid", str(e))
    store.save_preferences(prefs, paused=settings.paused, email=user.email)
    return {"settings": settings.model_dump(), "paused": settings.paused}


@route("PUT", "/me/webhook")
def save_webhook(user, event):
    _, _, ssm = _deps()
    url = str(_body(event).get("url") or "").strip()
    if not WEBHOOK_RE.match(url):
        raise HttpError(400, "invalid", "that isn't a Slack incoming-webhook URL "
                                        "(https://hooks.slack.com/services/...)")
    ssm.put_parameter(Name=SSM_PREFIX + webhook_secret(user.id), Value=url, Type="SecureString",
                      Overwrite=True, Tier="Standard")
    return {"has_webhook": True}


@route("DELETE", "/me/webhook")
def delete_webhook(user, event):
    store, _, ssm = _deps()
    try:
        ssm.delete_parameter(Name=SSM_PREFIX + webhook_secret(user.id))
    except ssm.exceptions.ParameterNotFound:
        pass
    settings, paused = _settings_of(user)
    if settings and settings.delivery.slack:                  # don't leave Slack on with no webhook
        settings.delivery.slack = False
        store.save_preferences(to_preferences(user.id, user.email, settings, False),
                               paused=paused, email=user.email)
    return {"has_webhook": False}


@route("POST", "/me/preview")
def preview(user, event):
    """Search with the settings in the body (or the saved ones): what would be found right now.
    Search only (no relevance scoring or summaries), so it fits API Gateway's 30-second limit."""
    from digest import paper, sources
    body = _body(event)
    if body:
        settings = UserSettings.model_validate(body)
    else:
        settings, _ = _settings_of(user)
        if settings is None:
            raise HttpError(404, "no_settings", "save your settings first, or send them in the body")
    settings.delivery.slack = False                           # preview never posts
    sub = to_preferences(user.id, user.email, settings, False).to_sub()
    sub["candidate_pool"] = 20
    try:
        papers, report = sources.search_all(sub)
    except RuntimeError as e:                                 # every source failed
        raise HttpError(502, "sources_down", str(e))
    return {"found": {name: (n if isinstance(n, int) else f"failed: {n}"[:200]) for name, n in report.items()},
            "count": len(papers),
            "examples": [{"title": p["title"], "journal": p["journal"], "link": paper.url(p)} for p in papers[:5]]}


@route("POST", "/me/test-delivery")
def test_delivery(user, event):
    store, _, _ = _deps()
    from digest.notify import mail, slack
    settings, _ = _settings_of(user)
    if settings is None:
        raise HttpError(404, "no_settings", "save your settings first")
    if not (settings.delivery.slack or settings.delivery.email):
        raise HttpError(400, "invalid", "switch on Slack or email first")
    if not store.take_quota(user.id, "test", TEST_MESSAGES_PER_DAY):
        raise HttpError(429, "too_many", f"at most {TEST_MESSAGES_PER_DAY} test messages a day")
    text = f"Literature Fetch test message for {settings.name}: your digest will arrive here."
    sent, failed = [], {}
    if settings.delivery.slack:
        try:
            slack.send(env.get(webhook_secret(user.id)), text)
            sent.append("slack")
        except Exception as e:                                # report it, don't crash
            failed["slack"] = str(e)[:200]
    if settings.delivery.email:
        msg = EmailMessage()
        msg["Subject"] = "Literature Fetch test message"
        msg.set_content(text)
        try:
            mail.send([user.email], msg)
            sent.append("email")
        except Exception as e:
            failed["email"] = str(e)[:200]
    return {"sent": sent, "failed": failed}


@route("GET", "/me/digests")
def digests(user, event):
    """Papers they were sent, grouped by the day they were sent, newest first (last 20 days)."""
    store, _, _ = _deps()
    days = {}
    for r in store.load_history(user.id):
        if r.get("posted_at"):
            days.setdefault(r["posted_at"], []).append(
                {"title": r["title"], "link": r.get("link"), "journal": r.get("journal"),
                 "summary": r.get("summary"), "relevance": r.get("relevance"), "rank": r.get("rank")})
    return {"digests": [{"date": d, "papers": sorted(ps, key=lambda p: p["rank"] or 0)}
                        for d, ps in sorted(days.items(), reverse=True)[:20]]}


@route("DELETE", "/me")
def delete_me(user, event):
    store, _, ssm = _deps()
    removed = store.delete_user(user.id)
    try:
        ssm.delete_parameter(Name=SSM_PREFIX + webhook_secret(user.id))
    except ssm.exceptions.ParameterNotFound:
        pass
    pool = os.getenv("LITFETCH_USER_POOL_ID")
    if pool:
        import boto3
        boto3.client("cognito-idp", region_name=os.getenv("AWS_REGION", "us-east-2")).admin_delete_user(
            UserPoolId=pool, Username=user.id)
    return {"deleted_items": removed}


@route("GET", "/admin/invites", admin=True)
def list_invites(user, event):
    store, _, _ = _deps()
    return {"invites": store.list_invites()}


@route("POST", "/admin/invites", admin=True)
def make_invites(user, event):
    store, _, _ = _deps()
    body = _body(event)
    count, days = int(body.get("count", 1)), int(body.get("days", 14))
    if not (1 <= count <= 20 and 1 <= days <= 60):
        raise HttpError(400, "invalid", "count must be 1-20 and days 1-60")
    codes = store.create_invites(count, days, created_by=user.email or user.id,
                                 note=str(body.get("note", ""))[:200])
    return {"codes": codes, "days": days}


# ---------- entry point ----------

def handler(event, context):
    ctx = event.get("requestContext") or {}
    method, path = (ctx.get("http") or {}).get("method", ""), event.get("rawPath", "")
    match = ROUTES.get((method, path))
    if match is None:
        known = any(p == path for _, p in ROUTES)
        return _reply(405 if known else 404, {"error": "method_not_allowed" if known else "not_found",
                                              "message": f"{method} {path}"})
    fn, login, admin = match
    claims = ((ctx.get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    user = User(claims)
    try:
        if login and not user.id:
            raise HttpError(401, "unauthorized", "sign in first")
        if admin and not user.admin:
            raise HttpError(403, "forbidden", "admins only")
        return _reply(200, fn(user, event))
    except HttpError as e:
        return _reply(e.status, {"error": e.code, "message": e.message})
    except ValidationError as e:
        from digest.prefs import problems
        return _reply(400, {"error": "invalid", "message": "; ".join(problems(e)), "fields": problems(e)})
    except Exception:
        traceback.print_exc()
        return _reply(500, {"error": "internal", "message": "something went wrong; it has been logged"})
