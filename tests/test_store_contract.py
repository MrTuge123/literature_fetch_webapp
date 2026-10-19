"""What every Store must do, checked against FileStore (the files) and DynamoStore (a fake
DynamoDB), so swapping one for the other can't change what subscribers get."""
import pytest

from digest import paper
from digest.storage import FileStore, Store


def make(title, doi=None, pmid=None, **extra):
    p = paper.new("PubMed", title, abstract="An abstract.", doi=doi, pmid=pmid, journal="J")
    p.update(score=0.5, preprint=False, keyword_hits=[], **extra)
    return p


A = make("Graph neural networks for spatial transcriptomics data", doi="10.1/a", pmid="111", relevance=7.5)
B = make("Single-cell multi-omics integration with graph attention", doi="10.1/b", relevance=3)


@pytest.fixture(params=["files", "dynamodb"])
def store(request, tmp_path, monkeypatch):
    if request.param == "files":
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GITHUB_ACTIONS", "1")        # skip the git lookup of the GitHub copy
        return FileStore()
    request.getfixturevalue("dynamo_table")
    from digest.dynamo_store import DynamoStore
    return DynamoStore()


def test_is_a_store(store):
    assert isinstance(store, Store)


def test_seen_starts_empty_and_only_grows(store):
    assert store.load_seen("lab") == set()
    store.add_seen("lab", paper.ids(A))
    store.add_seen("lab", paper.ids(B))
    store.add_seen("lab", paper.ids(A))                       # again: no change
    assert store.load_seen("lab") == paper.ids(A) | paper.ids(B)


def test_subscribers_are_kept_apart(store):
    store.add_seen("lab", {"10.1/a"})
    store.save_history("lab", [A], posted=[A])
    assert store.load_seen("other") == set() and store.load_history("other") == []


def test_history_saves_every_candidate_and_marks_the_posted_ones(store):
    store.save_history("lab", [A, B], posted=[A])
    recs = sorted(store.load_history("lab"), key=lambda r: r["rank"])
    assert [r["title"] for r in recs] == [A["title"], B["title"]]
    assert recs[0]["posted_at"] and recs[1]["posted_at"] is None


def test_numbers_come_back_as_they_went_in(store):
    store.save_history("lab", [A, B], posted=[])
    rel = {r["doi"]: r["relevance"] for r in store.load_history("lab")}
    assert rel == {"10.1/a": 7.5, "10.1/b": 3}
    assert type(rel["10.1/b"]) is int and type(rel["10.1/a"]) is float


def test_same_paper_in_two_runs_is_one_record(store):
    store.save_history("lab", [A], posted=[])
    store.save_history("lab", [B, A], posted=[A])
    recs = store.load_history("lab")
    assert len(recs) == 2
    a = next(r for r in recs if r["doi"] == "10.1/a")
    assert a["posted_at"] and a["rank"] == 2                  # newest rank, earliest posted date


def test_records_that_turn_out_to_be_one_paper_are_merged(store):
    by_doi = make("A long enough title about graph learning on omics", doi="10.1/x")
    by_pmid = make("A different title for the same graph learning paper", pmid="999")
    store.save_history("lab", [by_doi, by_pmid], posted=[])
    assert len(store.load_history("lab")) == 2
    both = make("A long enough title about graph learning on omics", doi="10.1/x", pmid="999")
    store.save_history("lab", [both], posted=[])              # links the two
    (r,) = store.load_history("lab")
    assert {"10.1/x", "999"} <= set(r["ids"])


def test_set_references_fills_in_later_lookups(store):
    store.save_history("lab", [make("Paper with references found later on", doi="10.1/c")], posted=[])
    store.set_references("lab", {"10.1/c": {"openalex_id": "W123", "references": ["W1", "W2"]}})
    store.set_references("lab", {})                           # nothing to do
    (r,) = store.load_history("lab")
    assert r["openalex_id"] == "W123" and r["references"] == ["W1", "W2"]
