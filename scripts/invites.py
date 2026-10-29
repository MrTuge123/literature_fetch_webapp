"""Make or list invite codes from your laptop (the first one, before any admin account exists).
Once you're in the admins group, the website's POST /admin/invites does the same.

    python scripts/invites.py --profile litfetch new --count 1 --note "Tiger's own account"
    python scripts/invites.py --profile litfetch list
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Literature Fetch invite codes")
    ap.add_argument("--profile", help="AWS CLI profile (e.g. litfetch)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="make codes")
    new.add_argument("--count", type=int, default=1)
    new.add_argument("--days", type=int, default=14, help="valid for this many days")
    new.add_argument("--note", default="", help="who it's for")
    sub.add_parser("list", help="show every code and who used it")
    args = ap.parse_args(argv)

    import boto3
    from digest.dynamo_store import DynamoStore
    ds = DynamoStore(session=boto3.Session(profile_name=args.profile) if args.profile else None)
    if args.cmd == "new":
        for code in ds.create_invites(args.count, args.days, created_by="scripts/invites.py", note=args.note):
            print(code)
        print(f"(valid {args.days} days, one sign-up each)")
    else:
        for i in ds.list_invites():
            used = f"used by {i['used_by']} on {i['used_at']}" if i.get("used_by") else "unused"
            print(f"{i['code']}  expires {i['expires_at']}  {used}  {i.get('note') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
