"""Copy secrets into Parameter Store as /litfetch/<NAME> SecureStrings, for the worker Lambda.

    python scripts/put_secrets.py --dry-run                       # which names, no AWS calls
    python scripts/put_secrets.py --profile litfetch              # every NAME=value in .env
    python scripts/put_secrets.py --profile litfetch --set EMAIL_TO_WANG_LAB   # type a value (hidden)

Values are never printed. It also lists secret names your subscribers' settings refer to
(outputs.*.webhook_env / to_env) that aren't in .env, e.g. ones that only exist as GitHub
secrets: add those with --set. Standard-tier parameters are free.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import dotenv_values  # noqa: E402

from digest import config  # noqa: E402

PREFIX = "/litfetch/"


def referenced_names():
    """Secret names the active subscribers' outputs point to."""
    names = set()
    for p in config.load_preferences():
        for out in (p.to_sub().get("outputs") or {}).values():
            if out and out.get("enabled"):
                names |= {out[k] for k in ("webhook_env", "to_env") if out.get(k)}
    return names


def main(argv=None):
    ap = argparse.ArgumentParser(description="Copy .env secrets into Parameter Store (/litfetch/<NAME>).")
    ap.add_argument("--profile", help="AWS CLI profile (e.g. litfetch)")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--set", metavar="NAME", action="append", default=[],
                    help="also store NAME, typing its value (hidden); repeatable")
    ap.add_argument("--dry-run", action="store_true", help="list names only; no AWS calls")
    args = ap.parse_args(argv)

    values = {k: v for k, v in dotenv_values(args.env_file).items() if v} if os.path.exists(args.env_file) else {}
    for name in args.set:
        values[name] = getpass.getpass(f"Value for {name} (hidden): ").strip()
    missing = sorted(referenced_names() - set(values))

    print(f"Secrets to store under {PREFIX} ({len(values)}):")
    for name in sorted(values):
        print(f"  {PREFIX}{name}")
    if missing:
        print("\nYour subscribers refer to these, but they're not in .env (add with --set NAME):")
        for name in missing:
            print(f"  {name}")
    if args.dry_run:
        print("\nDry run: nothing stored.")
        return 0

    import boto3
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    ssm = session.client("ssm", region_name="us-east-2")
    for name, value in sorted(values.items()):
        ssm.put_parameter(Name=PREFIX + name, Value=value, Type="SecureString", Overwrite=True, Tier="Standard")
    print(f"\nStored {len(values)} secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
