"""The Past digests graph (digest/graph.py): which earlier papers appear, how they are linked, and
how the picture is kept small."""
from digest import graph

WEEK = "2026-11-09"


def rec(title, posted=None, seen="2026-10-05", rel=None, refs=None, oa=None, first="Ann Smith", summary=None):
    """A history record (digest/history.py) with only what the graph reads."""
    return {"title": title, "posted_at": posted, "first_seen": posted or seen, "relevance": rel,
            "references": list(refs) if refs is not None else None, "openalex_id": oa,
            "ids": [f"title:{title}"], "key_authors": [{"name": first, "role": "first"}] if first else [],
            "top_author": None, "link": f"https://example.org/{title}", "journal": "J", "summary": summary}


def titles(g):
    return {n["title"] for n in g["nodes"]}


def links(g):
    """{frozenset of the two titles: (shared, direct)}"""
    name = {n["id"]: n["title"] for n in g["nodes"]}
    return {frozenset((name[e["source"]], name[e["target"]])): (e["shared"], e["direct"]) for e in g["edges"]}


def test_earlier_papers_sharing_two_references_are_linked():
    now = rec("now", posted=WEEK, refs=["W1", "W2", "W3"], summary="A summary.")
    two = rec("two", posted="2026-11-02", refs=["W1", "W2"])
    one = rec("one", posted="2026-11-02", refs=["W3", "W9"])            # one shared reference: not enough
    g = graph.build([two, one, now])
    assert titles(g) == {"now", "two"}
    assert links(g) == {frozenset(("now", "two")): (2, False)}
    assert (g["date"], g["papers"], g["with_refs"], g["linked"], g["more"]) == (WEEK, 1, 1, 1, 0)
    week, earlier = g["nodes"]
    assert week["this_week"] and week["sent"] and week["summary"] == "A summary." and week["date"] == WEEK
    assert not earlier["this_week"] and earlier["date"] == "2026-11-02"


def test_a_direct_citation_links_without_shared_references():
    old = rec("old", posted="2026-10-26", refs=["W5"], oa="W100")
    now = rec("now", posted=WEEK, refs=["W100", "W7"])
    assert links(graph.build([old, now])) == {frozenset(("now", "old")): (0, True)}


def test_which_earlier_papers_count():
    refs = ["W1", "W2"]
    papers = [
        rec("now", posted=WEEK, refs=refs),
        rec("sent", posted="2026-11-02", refs=refs),                     # sent: always
        rec("relevant", rel=5, refs=refs),                               # unsent, relevance >= 5
        rec("weak", rel=4, refs=refs),                                   # below min_relevance
        rec("unscored", refs=refs),                                      # never scored
        rec("same run", seen=WEEK, rel=9, refs=refs),                    # not earlier
        rec("later", posted="2026-11-16", refs=refs),                    # a later digest
    ]
    assert titles(graph.build(papers, WEEK)) == {"now", "sent", "relevant"}
    stricter = {"connections": {"min_relevance": 7}}                     # their own setting wins
    assert titles(graph.build(papers, WEEK, stricter)) == {"now", "sent"}


def test_which_digest():
    a = rec("first week", posted="2026-11-02", refs=["W1"])
    b = rec("second week", posted=WEEK, refs=["W1"])
    assert graph.build([a, b])["date"] == WEEK                           # the latest by default
    assert titles(graph.build([a, b], "2026-11-02")) == {"first week"}
    assert graph.build([a, b], "2026-11-03") is None
    assert graph.build([]) is None
    assert graph.build([rec("never sent", rel=9)]) is None


def test_references_most_papers_cite_do_not_link():
    now = rec("now", posted=WEEK, refs=["GSEA", "WX"])
    close = rec("close", posted="2026-11-02", refs=["GSEA", "WX", "W0"])
    others = [rec(f"other {i}", posted="2026-10-26", refs=["GSEA", f"U{i}"]) for i in range(19)]
    assert titles(graph.build([now, close, *others])) == {"now"}         # GSEA: cited by all 20
    assert titles(graph.build([now, close, *others[:5]])) == {"now", "close"}   # too few to judge


def test_only_the_most_strongly_linked_earlier_papers_are_shown(monkeypatch):
    monkeypatch.setattr(graph, "MAX_EARLIER", 3)
    now = rec("now", posted=WEEK, refs=[f"W{i}" for i in range(6)])
    weak = [rec(f"weak {i}", posted="2026-11-02", refs=["W0", "W1"]) for i in range(4)]
    strong = rec("strong", posted="2026-10-26", refs=[f"W{i}" for i in range(5)])
    g = graph.build([*weak, strong, now])
    assert len(g["nodes"]) == 4 and "strong" in titles(g)
    assert (g["linked"], g["more"]) == (5, 2)


def test_each_paper_keeps_only_its_strongest_links():
    now = rec("now", posted=WEEK, refs=["R1", "R2"])
    common = ["C1", "C2", "C3", "C4", "C5"]
    earlier = [rec(f"e{i}", posted="2026-11-02", refs=["R1", "R2", *common, f"own{i}"]) for i in range(6)]
    g = graph.build([now, *earlier])
    found = links(g)
    among_earlier = [pair for pair in found if "now" not in pair]
    assert len(among_earlier) < 15                                       # not all 6 * 5 / 2 pairs
    assert all(frozenset(("now", f"e{i}")) in found for i in range(6))   # each keeps why it's shown


def test_papers_without_references_are_still_shown():
    g = graph.build([rec("now", posted=WEEK), rec("old", posted="2026-11-02", refs=["W1", "W2"])])
    assert [n["has_refs"] for n in g["nodes"]] == [False] and g["with_refs"] == 0 and g["edges"] == []


def test_label_is_the_first_authors_surname():
    def r(authors, top=None, title="A fairly long paper title about spatial transcriptomics"):
        return {"title": title, "key_authors": authors, "top_author": top}
    assert graph.label(r([{"name": "Hyunju Lee", "role": "last"}, {"name": "Jisang Kim", "role": "first"}])) == "Kim"
    assert graph.label(r([{"name": "WANG X", "role": "first+corresponding"}])) == "Wang"
    assert graph.label(r([], top={"name": "Smith, John", "role": "first"})) == "Smith"
    assert graph.label(r([{"name": "Hyunju Lee", "role": "corresponding"}])) == "A fairly long paper title about spatial…"
    assert graph.label(r([], title="Short title")) == "Short title"
