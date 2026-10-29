"""Pre sign-up trigger: an unused, unexpired invite code is required (and used up)."""
import pytest

from api import presignup
from digest.dynamo_store import DynamoStore


@pytest.fixture
def ds(dynamo_table, monkeypatch):
    monkeypatch.setattr(presignup, "_store", None)
    return DynamoStore()


def event(code=None, source="PreSignUp_SignUp", where="clientMetadata"):
    request = {"userAttributes": {"email": "new@umich.edu"}}
    if code:
        request[where] = {"invite": code}
    return {"triggerSource": source, "request": request, "response": {}}


def test_a_valid_code_lets_one_person_in(ds):
    code, = ds.create_invites(1)
    assert presignup.handler(event(code), None)["triggerSource"] == "PreSignUp_SignUp"
    assert ds.list_invites()[0]["used_by"] == "new@umich.edu"
    with pytest.raises(Exception, match="invite code"):
        presignup.handler(event(code), None)                  # second person, same code


def test_no_code_or_wrong_code_is_refused(ds):
    for e in (event(), event("WRONG123")):
        with pytest.raises(Exception, match="invite code"):
            presignup.handler(e, None)


def test_code_can_come_as_validation_data(ds):
    code, = ds.create_invites(1)
    presignup.handler(event(code, where="validationData"), None)


def test_accounts_made_by_an_admin_need_no_code(ds):
    assert presignup.handler(event(source="PreSignUp_AdminCreateUser"), None)["request"]
