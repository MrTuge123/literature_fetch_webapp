"""Publication years in history: kept for new papers, and filled in for older ones by
scripts/backfill_years.py (against moto's DynamoDB and a stand-in for OpenAlex)."""
import importlib.util
import os

import pytest

from digest import history, openalex, paper
from digest.dynamo_store import DynamoStore

pytest.importorskip("moto")
spec = importlib.util.spec_from_file_location("backfill_years", os.path.join("scripts", "backfill_years.py"))
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)


def make(title, doi, oa=None, year=None):
    p = paper.new("PubMed", title, doi=doi, journal="J", openalex_id=oa)
    p.update(score=0.5, keyword_hits=[], year=year)
    return p


@pytest.fixture
def lookups(monkeypatch):
    """OpenAlex knows W1 (2025) and the DOI 10.1/b (2024). Returns what was asked for."""
    asked = []

    def by_id(ids, select):
        asked.append(("id", sorted(ids)))
        return {i: {"id": i, "publication_year": 2025} for i in ids if i == "W1"}

    def by_doi(dois, select):
        asked.append(("doi", sorted(dois)))
        return {d: {"doi": d, "publication_year": 2024} for d in dois if d == "10.1/b"}

    monkeypatch.setattr(openalex, "works_by_id", by_id)
    monkeypatch.setattr(openalex, "works_by_doi", by_doi)
    return asked


def stored(sid="lab"):
    return {r["title"]: r for r in DynamoStore().load_history(sid)}


def test_new_history_records_keep_the_publication_year():
    p = make("A paper whose year OpenAlex gave during the run", "10.1/k", year=2023)
    assert history.record(p, 1, "2026-11-09", False)["year"] == 2023


def test_older_papers_get_their_year_from_openalex(dynamo_table, lookups, capsys):
    a = make("Found on OpenAlex by its OpenAlex ID", "10.1/a", oa="W1")
    b = make("Found on OpenAlex by DOI, having no OpenAlex ID", "10.1/b")
    c = make("Not known to OpenAlex, so it keeps no year", "10.1/c", oa="W3")
    d = make("Already has the year from its digest run", "10.1/d", oa="W4", year=2022)
    DynamoStore().save_history("lab", [a, b, c, d], posted=[a])

    backfill.main(["--only", "lab", "--dry-run"])
    assert {t: r["year"] for t, r in stored().items()} == {a["title"]: None, b["title"]: None,
                                                           c["title"]: None, d["title"]: 2022}
    assert "Would fill 2 publication years." in capsys.readouterr().out

    backfill.main(["--only", "lab"])
    after = stored()
    assert {t: r["year"] for t, r in after.items()} == {a["title"]: 2025, b["title"]: 2024,
                                                        c["title"]: None, d["title"]: 2022}
    assert after[a["title"]]["posted_at"] and after[a["title"]]["openalex_id"] == "W1"   # the rest kept
    assert ("id", ["W1", "W3"]) in lookups and ("doi", ["10.1/b"]) in lookups          # d not asked
    assert "Filled 2 publication years." in capsys.readouterr().out

    backfill.main(["--only", "lab"])                                  # again: only c is still missing
    assert lookups[-2:] == [("id", ["W3"]), ("doi", [])]
