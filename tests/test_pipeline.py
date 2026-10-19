"""run_subscriber end to end, with nothing real: three canned papers instead of PubMed, a fixed
reply instead of the LLM, an in-memory store instead of seen/ and history/, a fake Slack."""
import copy

import pytest
import requests
import yaml

from digest import config, env, llm, notify, openalex, paper, relevance, sources, summarizer
from digest.pipeline import run_subscriber
from digest.prefs import Preferences

A = paper.new("PubMed", "Graph neural networks for spatial transcriptomics data",
              abstract="We map tissue with a GNN.", doi="10.1/a", pmid="111", journal="Nature Methods")
B = paper.new("PubMed", "Single-cell multi-omics integration with graph attention",
              abstract="We integrate omics layers.", doi="10.1/b", journal="Genome Biology")
C = paper.new("PubMed", "Traffic forecasting on city road graphs with transformers",
              abstract="Unrelated to biology.", doi="10.1/c", journal="Transportation Research")
WEBHOOK = "https://hooks.slack.com/services/TEST"


class FakeStore:
    """In memory; records every write so tests can check what the pipeline saved."""
    def __init__(self, seen=(), history=()):
        self.seen, self.history, self.saved, self.refs = set(seen), list(history), [], []

    def load_seen(self, sid):
        return set(self.seen)

    def add_seen(self, sid, ids):
        self.seen |= set(ids)

    def load_history(self, sid):
        return list(self.history)

    def save_history(self, sid, ranked, posted):
        self.saved.append({"ranked": [p["doi"] for p in ranked], "posted": [p["doi"] for p in posted]})

    def set_references(self, sid, updates):
        self.refs.append(updates)


class FakeSecrets:
    def get(self, name):
        return {"SLACK_WEBHOOK_URL": WEBHOOK, "GROQ_API_KEY": "test"}.get(name)


def prefs():
    with open(config.CONFIG_FILE) as f:
        shared = yaml.safe_load(f)
    sub = config._deep_merge(shared, {
        "id": "lab", "name": "Test Lab", "query": '"graph neural network" AND omics',
        "interest": "GNNs for omics data", "max_papers": 2,
        "sources": {"pubmed": {"enabled": True}},
        "connections": {"enabled": False},                     # no OpenAlex reference lookups
        "outputs": {"slack": {"enabled": True, "webhook_env": "SLACK_WEBHOOK_URL"},
                    "wecom": {"enabled": False}, "email": {"enabled": False}},
    })
    return Preferences.model_validate(sub)


@pytest.fixture
def world(monkeypatch):
    """Patch every outside call; returns what the fakes saw."""
    seen = {"llm_batches": [], "slack": []}
    monkeypatch.setattr(relevance, "_cache", {})               # scores from other tests don't leak in
    monkeypatch.setattr(sources, "search_all",
                        lambda sub: ([copy.deepcopy(p) for p in (A, B, C)], {"PubMed": 3}))
    monkeypatch.setattr(openalex, "enrich", lambda papers: None)

    def fake_ask_json(system, user, model, **kw):             # relevance: A 9, B 7, C 1
        titles = [line.split("] ", 1)[1] for line in user.splitlines() if line.startswith("[")]
        seen["llm_batches"].append(titles)
        score = {A["title"]: 9, B["title"]: 7, C["title"]: 1}
        return {str(i): score[t] for i, t in enumerate(titles, 1)}
    monkeypatch.setattr(llm, "ask_json", fake_ask_json)

    def fake_summaries(top, model, sub, pool=None):
        for p in top:
            p["summary"] = f"Summary of {p['title']}"
        return "Overview of this week."
    monkeypatch.setattr(summarizer, "summarize_all", fake_summaries)
    monkeypatch.setattr(notify.slack, "send", lambda url, text: seen["slack"].append((url, text)))
    previous = env.use(env.EnvSecrets())
    yield seen
    env.use(previous)


def test_posts_the_top_papers_and_remembers_them(world):
    store = FakeStore()
    failed = run_subscriber(prefs(), store, FakeSecrets())
    assert failed == []
    (url, text), = world["slack"]
    assert url == WEBHOOK                                      # webhook came from the secrets backend
    assert A["title"] in text and B["title"] in text and C["title"] not in text
    assert store.seen == paper.ids(A) | paper.ids(B)           # only what was posted
    assert store.saved == [{"ranked": ["10.1/a", "10.1/b", "10.1/c"], "posted": ["10.1/a", "10.1/b"]}]
    assert len(world["llm_batches"]) == 1                      # one relevance call for all three


def test_papers_already_sent_are_skipped(world):
    store = FakeStore(seen={"10.1/a"})                         # any one shared ID is enough
    run_subscriber(prefs(), store, FakeSecrets())
    assert A["title"] not in world["llm_batches"][0]
    assert store.saved[0]["ranked"] == ["10.1/b", "10.1/c"]


def test_nothing_new_means_no_llm_calls_and_no_post(world):
    store = FakeStore(seen={"10.1/a", "10.1/b", "10.1/c"})
    assert run_subscriber(prefs(), store, FakeSecrets()) == []
    assert world["llm_batches"] == [] and world["slack"] == [] and store.saved == []


def test_dry_run_posts_and_saves_nothing(world, capsys):
    store = FakeStore()
    run_subscriber(prefs(), store, FakeSecrets(), dry_run=True)
    assert world["slack"] == []
    assert store.seen == set() and store.saved == [] and store.refs == []
    assert "DRY RUN: would post to Slack" in capsys.readouterr().out


def test_a_failed_post_is_not_marked_seen(world, monkeypatch):
    def down(url, text):
        raise requests.ConnectionError("Slack is down")
    monkeypatch.setattr(notify.slack, "send", down)
    store = FakeStore()
    assert run_subscriber(prefs(), store, FakeSecrets()) == ["Slack"]
    assert store.seen == set()                                 # so next week's run tries them again
    assert store.saved == [{"ranked": ["10.1/a", "10.1/b", "10.1/c"], "posted": []}]


def test_a_missing_webhook_secret_fails_that_chat(world):
    class NoSecrets:
        def get(self, name):
            return "test" if name == "GROQ_API_KEY" else None
    store = FakeStore()
    assert run_subscriber(prefs(), store, NoSecrets()) == ["Slack"]
    assert world["slack"] == [] and store.seen == set()


def test_relevance_scores_from_earlier_runs_are_reused(world):
    sub = prefs().to_sub()
    tag = relevance.stamp(summarizer.interest(sub), sub["model"], False)
    earlier = {"ids": sorted(paper.ids(A)), "relevance": 9, "relevance_for": tag,
               "title": A["title"], "first_seen": "2026-10-01", "posted_at": None}
    run_subscriber(prefs(), FakeStore(history=[earlier]), FakeSecrets())
    assert world["llm_batches"] == [[B["title"], C["title"]]]   # A wasn't sent to the LLM again


def test_a_plain_settings_dict_works_too(world):
    store = FakeStore()
    assert run_subscriber(prefs().to_sub(), store, FakeSecrets()) == []
    assert store.seen


def test_runs_the_same_on_dynamodb(world, dynamo_table):
    from digest.dynamo_store import DynamoStore
    ds = DynamoStore()
    assert run_subscriber(prefs(), ds, FakeSecrets()) == []
    assert ds.load_seen("lab") == paper.ids(A) | paper.ids(B)
    assert sorted(r["doi"] for r in ds.load_history("lab")) == ["10.1/a", "10.1/b", "10.1/c"]
    world["slack"].clear()
    run_subscriber(prefs(), ds, FakeSecrets())                # next week: A and B were sent already
    assert len(world["llm_batches"]) == 1                     # C's score came back from DynamoDB history
    (url, text), = world["slack"]
    assert C["title"] in text and A["title"] not in text
