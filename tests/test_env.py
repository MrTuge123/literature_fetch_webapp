"""Every secret goes through digest.env: from the environment / GitHub JSON by default, or from
whatever backend env.use() plugs in (Parameter Store on Lambda, a dict in tests)."""
import json

import pytest

from digest import env, llm, openalex


class DictSecrets:
    def __init__(self, **values):
        self.values = values

    def get(self, name):
        return self.values.get(name)


@pytest.fixture
def secrets():
    fake = DictSecrets(GROQ_API_KEY="groq-test", OPENALEX_API_KEY="oa-test", SLACK_WEBHOOK_URL="https://hooks.slack.com/test")
    previous = env.use(fake)
    yield fake
    env.use(previous)


def test_env_secrets_reads_the_environment_then_github_json(monkeypatch):
    s = env.EnvSecrets()
    monkeypatch.setenv("SOME_KEY", "from-env")
    monkeypatch.setenv("GITHUB_SECRETS_JSON", json.dumps({"OTHER_KEY": "from-github"}))
    assert s.get("SOME_KEY") == "from-env"
    assert s.get("other_key") == "from-github"          # GitHub stores names upper-cased
    assert s.get("MISSING") is None and s.get(None) is None


def test_use_swaps_the_backend_for_every_reader(secrets):
    assert isinstance(secrets, env.Secrets)
    assert env.get("SLACK_WEBHOOK_URL") == "https://hooks.slack.com/test"
    assert env.get("NOT_SET") is None


def test_llm_key_comes_from_the_backend(secrets, monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "OpenAI", lambda api_key, base_url: seen.update(key=api_key, url=base_url) or object())
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm, "_provider", llm.PROVIDERS["groq"])
    llm._llm()
    assert seen == {"key": "groq-test", "url": llm.PROVIDERS["groq"]["base_url"]}


def test_llm_says_which_key_is_missing(monkeypatch):
    previous = env.use(DictSecrets())
    try:
        monkeypatch.setattr(llm, "_client", None)
        monkeypatch.setattr(llm, "_provider", llm.PROVIDERS["groq"])
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            llm._llm()
    finally:
        env.use(previous)


def test_openalex_key_is_read_per_call_not_at_import(secrets, monkeypatch):
    sent = {}

    class Reply:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ok": True}

    monkeypatch.setattr(openalex.session, "get", lambda url, params, timeout: sent.update(params) or Reply())
    assert openalex._get("works/W1") == {"ok": True}
    assert sent["api_key"] == "oa-test"
