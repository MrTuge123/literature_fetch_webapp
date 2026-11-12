"""How one digest's papers connect to the subscriber's earlier papers, as a graph for the website's
Past digests page (GET /me/graph). It uses the same reference lists as the email's "Connections"
box (digest/connections.py) but looks nothing up: it only reads history.

Nodes: the papers sent on that date ("week" papers) and earlier papers linked to them. Earlier
papers count if they were sent, or Kimi scored their relevance at least connections.min_relevance
(as in the email). Unscored candidates are left out, or a subscriber with relevance scoring off
would get every candidate.

Links: two papers share at least MIN_SHARED references (leaving out ones most of history cites,
connections.max_share), or one cites the other. Links have no direction: the newer paper is
always the one citing.

To keep the picture readable:
- at most MAX_EARLIER earlier papers, the most strongly linked to the week's papers first
- a paper keeps its MAX_LINKS strongest links, its strongest link to a week paper and any direct
  citation; other links are dropped
"""
from collections import Counter

from digest import connections

MIN_SHARED = 2          # shared references for a link (1 links nearly everything)
MAX_EARLIER = 30        # earlier papers shown per digest
MAX_LINKS = 3           # strongest links kept per paper


def _when(r):
    """The date a record belongs to: when it was sent, or first seen if never sent."""
    return r.get("posted_at") or r["first_seen"]


def _key(r):
    """A stable id for a record (its smallest ID, as DynamoDB keys history items)."""
    return min(r["ids"]) if r.get("ids") else "untitled:" + r["title"][:80]


def _counts(r, cfg):
    rel = r.get("relevance")
    return bool(r.get("posted_at")) or (rel is not None and rel >= cfg["min_relevance"])


def label(r):
    """The first author's surname and the publication year ('Qian, 2025'; just 'Qian' while the
    year is unknown), from the key authors history keeps; else a short title."""
    authors = list(r.get("key_authors") or []) + ([r["top_author"]] if r.get("top_author") else [])
    first = next((a.get("name") for a in authors if "first" in (a.get("role") or "")), None)
    name = connections._surname(first) if first else ""
    if name:
        name = name.title() if name.isupper() and len(name) > 3 else name
        return f"{name}, {r['year']}" if r.get("year") else name
    t = r["title"]
    return t[:40].rstrip() + ("…" if len(t) > 40 else "")


def build(records, date=None, sub=None):
    """The graph for the digest sent on `date` (default: the latest one), or None if nothing was
    sent that day (or ever). records: the subscriber's history; sub: their settings (to_sub()),
    for connections.min_relevance and max_share.

    {"date", "papers": week papers, "with_refs": week papers with reference lists,
     "linked": earlier papers linked to them, "more": linked but not shown (over MAX_EARLIER),
     "nodes": [{"id", "label", "title", "link", "journal", "year", "date", "sent", "this_week",
                "relevance", "has_refs", "summary"}],
     "edges": [{"source", "target", "shared": shared references, "direct": one cites the other}]}"""
    cfg = connections.settings(sub or {})
    sent_dates = sorted({r["posted_at"] for r in records if r.get("posted_at")})
    date = date or (sent_dates[-1] if sent_dates else None)
    week = [r for r in records if date and r.get("posted_at") == date]
    if not week:
        return None
    earlier = [r for r in records if _counts(r, cfg) and _when(r) < date]

    # References most earlier papers cite (GSEA, TCGA, surveys) say little: leave them out
    with_refs = [r for r in earlier if r.get("references")]
    cited = Counter(w for r in with_refs for w in set(r["references"]))
    generic = ({w for w, n in cited.items() if n > cfg["max_share"] * len(with_refs)}
               if len(with_refs) >= connections.MIN_FOR_GENERIC else set())
    refs = {_key(r): set(r.get("references") or []) - generic for r in week + earlier}
    cites = {_key(r): set(r.get("references") or []) for r in week + earlier}

    def link(a, b):
        """(direct, shared) between two records: one cites the other, how many references they share."""
        ka, kb = _key(a), _key(b)
        direct = (b.get("openalex_id") in cites[ka]) or (a.get("openalex_id") in cites[kb])
        return bool(direct), len(refs[ka] & refs[kb])

    def linked(strength):
        return strength[0] or strength[1] >= MIN_SHARED

    # Earlier papers linked to a week paper, the strongest first
    best = {}
    for e in earlier:
        s = max(link(w, e) for w in week)
        if linked(s):
            best[_key(e)] = (s, e)
    ranked = sorted(best.values(), key=lambda x: (x[0], x[1].get("relevance") or 0), reverse=True)
    shown = [e for _, e in ranked[:MAX_EARLIER]]

    # Links among everything shown, then prune
    nodes = week + shown
    week_keys = {_key(r) for r in week}
    candidates = {}
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            s = link(a, b)
            if linked(s):
                candidates[(_key(a), _key(b))] = s
    keep = {pair for pair, s in candidates.items() if s[0]}               # direct citations
    by_node = {}
    for pair, s in candidates.items():
        for k in pair:
            by_node.setdefault(k, []).append((s, pair))
    for k, lst in by_node.items():
        lst.sort(reverse=True)
        keep.update(pair for _, pair in lst[:MAX_LINKS])
        if k not in week_keys:                     # its strongest link to a week paper: why it's shown
            keep.add(next(pair for _, pair in lst if week_keys & set(pair)))

    return {
        "date": date,
        "papers": len(week),
        "with_refs": sum(bool(r.get("references")) for r in week),
        "linked": len(best),
        "more": len(best) - len(shown),
        "nodes": [{"id": _key(r), "label": label(r), "title": r["title"], "link": r.get("link"),
                   "journal": r.get("journal"), "year": r.get("year"), "date": _when(r), "sent": bool(r.get("posted_at")),
                   "this_week": _key(r) in week_keys, "relevance": r.get("relevance"),
                   "has_refs": bool(r.get("references")), "summary": r.get("summary")}
                  for r in nodes],
        "edges": [{"source": a, "target": b, "shared": candidates[(a, b)][1], "direct": candidates[(a, b)][0]}
                  for a, b in sorted(keep)],
    }
