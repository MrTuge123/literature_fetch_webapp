"""Fill in the publication year of papers already in history (DynamoDB), for the labels on the
Past digests graph ("Qian, 2025"). Papers found from now on get theirs when a digest runs
(digest/history.py); this is for the ones saved before that.

Years come from OpenAlex, 50 papers per request: by OpenAlex ID, or by DOI for papers without one.
Papers OpenAlex doesn't know keep no year, and the graph shows just the surname for them.
Safe to run again: only papers still missing a year are looked up, and only those items change.
Don't run it while the weekly round is running (Monday mornings), which also writes history.

    python scripts/backfill_years.py --profile litfetch --dry-run     # look up, write nothing
    python scripts/backfill_years.py --profile litfetch
    python scripts/backfill_years.py --profile litfetch --only wang_lab
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from digest import openalex  # noqa: E402


def publication_years(records):
    """{OpenAlex ID or DOI: year} for the records that have no year yet."""
    todo = [r for r in records if not r.get("year")]
    by_id = openalex.works_by_id([r["openalex_id"] for r in todo if r.get("openalex_id")],
                                 select="id,publication_year")
    by_doi = openalex.works_by_doi([r["doi"] for r in todo if r.get("doi") and not r.get("openalex_id")],
                                   select="id,doi,publication_year")
    return {k: w["publication_year"] for k, w in {**by_id, **by_doi}.items() if w.get("publication_year")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="AWS CLI profile (e.g. litfetch)")
    ap.add_argument("--table", help="DynamoDB table (default: LitFetch)")
    ap.add_argument("--only", help="one subscriber id")
    ap.add_argument("--dry-run", action="store_true", help="look the years up but write nothing")
    args = ap.parse_args(argv)

    import boto3
    from digest.dynamo_store import DynamoStore
    ds = DynamoStore(args.table, session=boto3.Session(profile_name=args.profile) if args.profile else None)
    total = 0
    for sid in [args.only] if args.only else ds.list_subscribers(include_paused=True):
        records = ds.load_history(sid)
        missing = [r for r in records if not r.get("year")]
        years = publication_years(missing) if missing else {}
        found = sum(bool(years.get(r.get("openalex_id")) or years.get(r.get("doi"))) for r in missing)
        print(f"{sid}: {len(records)} papers, {len(missing)} without a year, {found} found on OpenAlex")
        if not args.dry_run:
            ds.set_years(sid, years)
        total += found
    print(f"{'Would fill' if args.dry_run else 'Filled'} {total} publication years.")


if __name__ == "__main__":
    main()
