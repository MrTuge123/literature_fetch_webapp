"""What each provider is sent: Kimi gets the 'answer without reasoning' switch, Groq never does
(Groq rejects it with 400 "property 'thinking' is unsupported"), and a model that refuses the
switch is asked again without it and remembered."""
import httpx
import pytest
from openai import BadRequestError

from digest import llm


class FakeClient:
    """Records each request; fails the first one with `first_error` if given."""
    def __init__(self, first_error=None):
        self.requests, self.first_error = [], first_error
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.requests.append(kw)
        if self.first_error and len(self.requests) == 1:
            raise self.first_error
        msg = type("M", (), {"content": '{"1": 7}'})()
        return type("R", (), {"choices": [type("C", (), {"message": msg, "finish_reason": "stop"})()]})()


def bad_request(text):
    req = httpx.Request("POST", "https://api.example/v1/chat/completions")
    return BadRequestError(text, response=httpx.Response(400, request=req), body=None)


@pytest.fixture
def use(monkeypatch):
    def setup(provider, client):
        monkeypatch.setattr(llm, "_provider", llm.PROVIDERS[provider])
        monkeypatch.setattr(llm, "_client", client)
        monkeypatch.setattr(llm, "_always_thinks", set())
        return client
    return setup


def test_groq_is_never_sent_the_thinking_switch(use):
    client = use("groq", FakeClient())
    assert llm.ask_json("sys", "user", "openai/gpt-oss-120b", thinking=False) == {"1": 7}
    (req,) = client.requests
    assert "extra_body" not in req
    assert req["reasoning_effort"] == "low"                   # Groq's own way to keep reasoning short


def test_kimi_gets_the_thinking_switch_only_when_asked(use):
    client = use("kimi", FakeClient())
    llm.ask_json("sys", "user", "kimi-k2.6", thinking=False)
    llm.ask_json("sys", "user", "kimi-k2.6", thinking=True)
    assert client.requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in client.requests[1]


def test_a_model_that_refuses_the_switch_is_asked_again_and_remembered(use):
    client = use("kimi", FakeClient(first_error=bad_request("property 'thinking' is unsupported")))
    assert llm.ask_json("sys", "user", "some-model", thinking=False) == {"1": 7}
    assert "extra_body" in client.requests[0] and "extra_body" not in client.requests[1]
    llm.ask_json("sys", "user", "some-model", thinking=False)
    assert "extra_body" not in client.requests[2]             # remembered: not tried again
    assert "some-model" in llm._always_thinks


def test_other_bad_requests_still_fail(use):
    use("kimi", FakeClient(first_error=bad_request("context length exceeded")))
    with pytest.raises(BadRequestError):
        llm.ask_json("sys", "user", "kimi-k2.6", thinking=False)
