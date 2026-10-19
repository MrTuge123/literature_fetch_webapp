"""For each subscriber: search PubMed, Europe PMC, OpenAlex, Semantic Scholar and arXiv for new
papers, merge duplicates, rank them by author/journal impact (OpenAlex),
score their relevance to the subscriber's interest (Kimi), summarize the top ones with Kimi, and post to that subscriber's Slack / WeCom.
The steps live in digest/pipeline.py (see digest/__init__.py for the map of digest/).

Subscribers:   one file each in subscribers/ (copy subscribers/_template.yaml)
Shared config: config.yaml (defaults; a subscriber's file overrides them)
Already sent:  seen/<subscriber>.json
All ranked:    history/<subscriber>.jsonl (every candidate with its score, for trend summaries)

Run all:          python main.py
One subscriber:   python main.py --subscriber wang_lab
Test only:        python main.py --dry-run   (prints ranking + messages, doesn't post or save)
On DynamoDB:      python main.py --dry-run --store dynamodb --profile litfetch
"""
import argparse
import sys
import traceback

from digest.config import load_preferences
from digest.env import EnvSecrets
from digest.pipeline import run_subscriber
from digest.storage import FileStore
from digest.store import run_lock


def main():
    ap = argparse.ArgumentParser(description="Post new-paper digests to each subscriber's chats.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the ranking and messages; don't post or save")
    ap.add_argument("--subscriber", metavar="NAME",
                    help="run only this subscriber (its file name in subscribers/, without .yaml)")
    ap.add_argument("--store", choices=["files", "dynamodb"], default="files",
                    help="where seen papers and history live (default: the seen/ and history/ files)")
    ap.add_argument("--profile", help="AWS CLI profile for --store dynamodb (e.g. litfetch)")
    args = ap.parse_args()

    secrets = EnvSecrets()                          # .env / GitHub secrets
    if args.store == "dynamodb":
        import boto3
        from digest.dynamo_store import DynamoStore
        store = DynamoStore(session=boto3.Session(profile_name=args.profile) if args.profile else None)
    else:
        store = FileStore()                         # seen/ + history/ files
    failures = []
    for prefs in load_preferences(args.subscriber):
        try:
            failed = run_subscriber(prefs, store, secrets, args.dry_run)
        except Exception as e:              # one subscriber's problem shouldn't stop the others
            traceback.print_exc()
            print(f"Error: {prefs.id} failed ({e})")
            failed = ["run"]
        failures += [f"{prefs.id} ({name})" for name in failed]
    if failures:
        sys.exit("Failed: " + ", ".join(failures))


if __name__ == "__main__":
    with run_lock():                        # one run at a time in this folder
        main()
