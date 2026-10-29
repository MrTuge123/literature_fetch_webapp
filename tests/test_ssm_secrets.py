"""ParameterStoreSecrets reads /litfetch/<NAME> SecureStrings once and serves them like .env."""
import boto3
import pytest

from digest import env
from digest.ssm_secrets import ParameterStoreSecrets


@pytest.fixture
def ssm(aws):
    client = boto3.client("ssm", region_name="us-east-2")
    def put(name, value, type_="SecureString"):
        client.put_parameter(Name=name, Value=value, Type=type_)
    return client, put


def test_reads_secure_strings_by_name(ssm):
    _, put = ssm
    put("/litfetch/GROQ_API_KEY", "gsk-test")
    put("/litfetch/SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
    s = ParameterStoreSecrets()
    assert isinstance(s, env.Secrets)
    assert s.get("GROQ_API_KEY") == "gsk-test"
    assert s.get("SLACK_WEBHOOK_URL").startswith("https://hooks.slack.com/")
    assert s.get("MISSING") is None and s.get(None) is None


def test_only_its_own_prefix(ssm):
    _, put = ssm
    put("/litfetch/A", "mine")
    put("/other-app/A", "not mine")
    put("/litfetch/nested/B", "deeper")                       # not read: names are flat
    assert ParameterStoreSecrets().names() == ["A"]


def test_reads_every_page_and_only_once(ssm, monkeypatch):
    client, put = ssm
    for i in range(23):                                       # SSM returns at most 10 per page
        put(f"/litfetch/KEY_{i:02d}", f"v{i}")
    s = ParameterStoreSecrets()
    calls = []
    real = s._ssm.get_parameters_by_path
    monkeypatch.setattr(s._ssm, "get_parameters_by_path", lambda **kw: calls.append(kw) or real(**kw))
    assert s.get("KEY_22") == "v22" and s.get("KEY_00") == "v0"
    assert len(s.names()) == 23
    n = len(calls)
    s.get("KEY_05")
    assert len(calls) == n >= 3                               # every page once, then from memory


def test_plugs_into_digest_env(ssm):
    _, put = ssm
    put("/litfetch/OPENALEX_API_KEY", "oa")
    previous = env.use(ParameterStoreSecrets())
    try:
        assert env.get("OPENALEX_API_KEY") == "oa"
    finally:
        env.use(previous)


def test_a_secret_added_later_is_found_after_a_minute(ssm, monkeypatch):
    client, put = ssm
    put("/litfetch/A", "a")
    s = ParameterStoreSecrets()
    assert s.get("A") == "a" and s.get("NEW") is None
    put("/litfetch/NEW", "new")
    assert s.get("NEW") is None                               # just loaded: not asked again yet
    monkeypatch.setattr(s, "_loaded_at", s._loaded_at - 61)
    assert s.get("NEW") == "new"
