"""Relevance scoring: a batch too big for the provider's per-minute token limit (Groq returns
413 "Request too large") is split in half until it fits, instead of leaving it unscored."""
import httpx
import pytest
from openai import APIStatusError

from digest import llm, paper, relevance

MAX_PAPERS_PER_REQUEST = 10          # pretend anything bigger is over the token limit


def too_large():
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return APIStatusError("Request too large for model on tokens per minute (TPM): Limit 8000, Requested 8314",
                          response=httpx.Response(413, request=req), body=None)


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []
    def ask_json(system, user, model, **kw):
        n = sum(line.startswith("[") for line in user.splitlines())
        calls.append(n)
        if n > MAX_PAPERS_PER_REQUEST:
            raise too_large()
        return {str(i): 6 for i in range(1, n + 1)}
    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(relevance, "_cache", {})
    return calls


class NoHistory:
    def load_history(self, sid):
        return []


def papers(n):
    return [paper.new("PubMed", f"A sufficiently long paper title number {i} about graphs", abstract="x",
                      doi=f"10.1/{i}") for i in range(n)]


SUB = {"id": "lab", "model": "m", "interest": "graphs", "ranking": {"relevance_batch": 25}}


def test_too_large_batches_are_split_until_they_fit(fake_llm, capsys):
    ps = papers(25)
    relevance.score_all(ps, SUB, NoHistory())
    assert all(p["relevance"] == 6 for p in ps)                # nothing left unscored
    assert fake_llm == [25, 12, 6, 6, 13, 6, 7]                 # 25 -> 12 + 13 -> halves of each
    assert "splitting into 12 + 13" in capsys.readouterr().out


def test_other_errors_still_leave_the_batch_unscored(monkeypatch, capsys):
    monkeypatch.setattr(relevance, "_cache", {})
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: (_ for _ in ()).throw(ValueError("no JSON")))
    ps = papers(3)
    relevance.score_all(ps, SUB, NoHistory())
    assert all(p["relevance"] is None for p in ps)
    assert "Relevance scoring failed for 3 papers" in capsys.readouterr().out
