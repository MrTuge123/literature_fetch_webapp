"""Copy the file-based state into the LitFetch DynamoDB table:

    subscribers/<id>.yaml   -> PREFS item   (active subscribers only; files starting with _ are skipped)
    seen/<id>.json          -> SEEN# items  (every subscriber with a file, active or not)
    history/<id>.jsonl      -> HIST# items

Safe to run again: seen and history are merged (nothing duplicated, only changes written) and an
existing PREFS item is kept unless --overwrite-prefs. Afterwards it reads everything back and
fails if any count differs from the files.

    python scripts/migrate_files.py --dry-run                 # counts only, no AWS calls
    python scripts/migrate_files.py --profile litfetch        # do it
    python scripts/migrate_files.py --profile litfetch --only wang_lab
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from digest import config, history, store  # noqa: E402


def file_ids():
    """Every subscriber id that has a seen or history file."""
    stems = {os.path.splitext(os.path.basename(p))[0]
             for p in glob.glob(os.path.join(store.SEEN_DIR, "*.json")) + glob.glob(os.path.join(history.HISTORY_DIR, "*.jsonl"))}
    return sorted(s for s in stems if not s.startswith("."))


def from_files(sid):
    seen = store.read_seen(store.seen_path(sid))
    recs = history.read_history(history.history_path(sid))      # already one record per paper
    return seen, recs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copy subscribers/, seen/ and history/ into DynamoDB.")
    ap.add_argument("--profile", help="AWS CLI profile (e.g. litfetch)")
    ap.add_argument("--table", default=None, help="table name (default $LITFETCH_TABLE or LitFetch)")
    ap.add_argument("--only", metavar="ID", help="just this subscriber")
    ap.add_argument("--overwrite-prefs", action="store_true", help="replace PREFS items that already exist")
    ap.add_argument("--dry-run", action="store_true", help="print what would be copied; no AWS calls")
    args = ap.parse_args(argv)

    active = {p.id: p for p in config.load_preferences()}      # validated, like a real run
    ids = set(file_ids()) | set(active)
    if args.only:
        ids &= {args.only}
    ids = sorted(ids)
    if not ids:
        sys.exit("Nothing to migrate.")

    plan = {sid: (sid in active, *from_files(sid)) for sid in ids}
    print(f"{'subscriber':<20} {'prefs':>5} {'seen IDs':>9} {'history':>8}")
    for sid, (has_prefs, seen, recs) in plan.items():
        print(f"{sid:<20} {'yes' if has_prefs else '-':>5} {len(seen):>9} {len(recs):>8}")
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    import boto3
    from digest.dynamo_store import DynamoStore
    ds = DynamoStore(args.table, session=boto3.Session(profile_name=args.profile) if args.profile else None)
    problems = []
    for sid, (has_prefs, seen, recs) in plan.items():
        print(f"\n{sid}: ", end="", flush=True)
        if has_prefs:
            wrote = ds.save_preferences(active[sid], overwrite=args.overwrite_prefs)
            print("prefs " + ("written" if wrote else "kept (already there)") + ", ", end="", flush=True)
        ds.add_seen(sid, seen)
        print(f"{len(seen)} seen IDs, ", end="", flush=True)
        ds.merge_history(sid, recs)
        print(f"{len(recs)} history records... ", end="", flush=True)

        got_seen, got_hist = ds.load_seen(sid), ds.load_history(sid)   # read back and compare
        if not seen <= got_seen:
            problems.append(f"{sid}: {len(seen - got_seen)} seen IDs missing")
        if len(got_hist) < len(recs):
            problems.append(f"{sid}: {len(got_hist)} history records in DynamoDB, {len(recs)} in the file")
        if has_prefs and ds.load_preferences(sid) is None:
            problems.append(f"{sid}: PREFS missing")
        print("checked.")
    if problems:
        print("\nProblems:\n  " + "\n  ".join(problems))
        return 1
    print("\nAll counts match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
