"""FileStore keeps today's seen/ and history/ behavior: nothing sent is forgotten, the same paper
is one history record however many runs see it, and posted/first-seen dates are kept."""
import json

import pytest

from digest import paper
from digest.storage import FileStore, Store


@pytest.fixture
def fs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                    # seen/ and history/ are created here
    monkeypatch.setenv("GITHUB_ACTIONS", "1")      # skip the git lookup of the GitHub copy
    return FileStore()


def make(title, doi=None, pmid=None, **extra):
    p = paper.new("PubMed", title, abstract="An abstract.", doi=doi, pmid=pmid, journal="J")
    p.update(score=0.5, preprint=False, keyword_hits=[], **extra)
    return p


A = make("Graph neural networks for spatial transcriptomics data", doi="10.1/a", pmid="111")
B = make("Single-cell multi-omics integration with graph attention", doi="10.1/b")


def test_filestore_is_a_store():
    assert isinstance(FileStore(), Store)               # has all five methods


def test_seen_starts_empty_and_only_grows(fs):
    assert fs.load_seen("lab") == set()
    fs.add_seen("lab", paper.ids(A))
    fs.add_seen("lab", paper.ids(B))
    assert fs.load_seen("lab") == paper.ids(A) | paper.ids(B)
    assert json.load(open("seen/lab.json")) == sorted(paper.ids(A) | paper.ids(B))   # same file format


def test_subscribers_are_kept_apart(fs):
    fs.add_seen("lab", {"10.1/a"})
    assert fs.load_seen("other") == set()


def test_history_saves_every_candidate_and_marks_the_posted_ones(fs):
    fs.save_history("lab", [A, B], posted=[A])
    recs = fs.load_history("lab")
    assert [r["title"] for r in recs] == [A["title"], B["title"]]
    assert [r["rank"] for r in recs] == [1, 2]
    assert recs[0]["posted_at"] and recs[1]["posted_at"] is None


def test_same_paper_in_two_runs_is_one_record(fs):
    fs.save_history("lab", [A], posted=[])
    fs.save_history("lab", [B, A], posted=[A])           # A again (now posted), plus B
    recs = fs.load_history("lab")
    assert len(recs) == 2
    a = next(r for r in recs if r["doi"] == "10.1/a")
    assert a["posted_at"] and a["rank"] == 2             # newest run's rank, earliest posted date


def test_set_references_fills_in_later_lookups(fs):
    fs.save_history("lab", [make("Paper with references found later on", doi="10.1/c")], posted=[])
    fs.set_references("lab", {"10.1/c": {"openalex_id": "W123", "references": ["W1", "W2"]}})
    (r,) = fs.load_history("lab")
    assert r["openalex_id"] == "W123" and r["references"] == ["W1", "W2"]
