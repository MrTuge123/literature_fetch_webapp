"""Cognito pre sign-up trigger: only people with an unused, unexpired invite code can sign up.

The website passes the code as client metadata {"invite": "9F3A61C2"} with the sign-up call. A
valid code is marked used by that email (one person per code). Accounts an admin creates in the
console or CLI (AdminCreateUser) don't need a code."""
from digest.dynamo_store import DynamoStore

_store = None


def handler(event, context):
    global _store
    if event.get("triggerSource") == "PreSignUp_AdminCreateUser":
        return event
    request = event.get("request") or {}
    code = (request.get("clientMetadata") or {}).get("invite") or (request.get("validationData") or {}).get("invite")
    email = (request.get("userAttributes") or {}).get("email", "")
    _store = _store or DynamoStore()
    if not _store.use_invite(code, email):
        raise Exception("A valid invite code is required to sign up.")
    return event
