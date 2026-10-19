"""One subscriber's whole digest: search -> drop what they've had -> look up authors/journals ->
score relevance -> rank -> summarize -> find connections -> post -> remember.

run_subscriber() only reaches state through `store` (digest.storage) and secrets through
`secrets` (digest.env), so the same function runs from main.py (files, .env) and, from M3,
on Lambda (DynamoDB, Parameter Store)."""
import requests

from digest import connections, env, llm, notify, openalex, paper, ranking, relevance, sources, summarizer
from digest.prefs import Preferences


def run_subscriber(prefs, store, secrets=None, dry_run=False):
    """The whole digest for one subscriber. Returns the chats that failed (empty if none).
    prefs: a Preferences (or the plain settings dict). secrets: where API keys and webhook URLs
    come from (default: whatever digest.env already uses). dry_run prints instead of posting/saving."""
    if secrets is not None:
        env.use(secrets)
    sub = prefs.to_sub() if isinstance(prefs, Preferences) else prefs
    sid = sub["id"]

    print(f"\n========== {sub['name']} ({sid}) ==========")
    seen = store.load_seen(sid)
    papers, report = sources.search_all(sub)
    print("Found:", sources.describe(report))
    papers = [p for p in papers if not paper.ids(p) & seen]      # any shared ID = already sent
    if not papers:
        print("No new papers found.")
        return []
    print(f"{len(papers)} new candidates. Looking up authors/journals in OpenAlex...")
    try:
        openalex.enrich(papers)
    except requests.RequestException as e:
        print(f"Warning: OpenAlex lookup failed ({e}); ranking without it.")
    if relevance.wanted(sub["ranking"]):
        print(f"Scoring relevance with {llm.name()}...")
        relevance.score_all(papers, sub, store)

    papers = ranking.rank_papers(papers, sub["ranking"])
    ranking.print_ranking(papers)
    top = [p for p in papers if p["passed"]][:sub["max_papers"]]
    if not top:
        print("No papers passed the filters.")
        if not dry_run:
            store.save_history(sid, papers, posted=[])
        return []

    print(f"Summarizing {len(top)} papers and writing the overview...")       # once, shared by every chat
    overview = summarizer.summarize_all(top, sub["model"], sub, pool=papers)   # None for one paper, or if Kimi fails
    overview_zh = None
    if notify.wants_chinese(sub):           # some chat has chinese_summary: true (not saved to history/)
        print("Translating into Chinese...")
        overview_zh = summarizer.translate_all(top, overview, sub["model"], sub)
    context = {"candidates": len(papers), "found": report, "overview": overview, "overview_zh": overview_zh}
    refreshed = {}
    try:                                    # links to earlier papers by references (OpenAlex, no Kimi)
        context["connections"], refreshed = connections.find(top, sub, store)
        c = context["connections"]
        print(f"Connections: {c['n_shared']} shared references, {c['n_direct']} direct citations of earlier papers."
              if c else "Connections: none to earlier papers.")
    except requests.RequestException as e:
        print(f"Warning: couldn't look up connections to earlier papers ({e}).")

    posted, failed = notify.post(top, sub, dry_run, context)
    if posted:                              # at least one chat has them, so don't post them again
        if not dry_run:
            store.add_seen(sid, set().union(*(paper.ids(p) for p in top)))
        print(f"Done: posted {len(top)} of {len(papers)} candidates to {' and '.join(posted)}.")
    if not dry_run:                         # every ranked candidate, for trend summaries
        store.save_history(sid, papers, posted=top if posted else [])
        store.set_references(sid, refreshed)   # reference lists OpenAlex didn't have before
    return failed
