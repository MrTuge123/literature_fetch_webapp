"""Write web/.env.local from the LitFetchApi stack's outputs, so the website knows which API and
Cognito pool to talk to.

    python scripts/web_env.py --profile litfetch
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = {"ApiUrl": "VITE_API_URL", "UserPoolId": "VITE_USER_POOL_ID",
         "UserPoolClientId": "VITE_USER_POOL_CLIENT_ID"}


def env_text(outputs):
    """CloudFormation outputs [{"OutputKey", "OutputValue"}] -> the .env.local file's text."""
    got = {o["OutputKey"]: o["OutputValue"] for o in outputs}
    missing = [k for k in NAMES if k not in got]
    if missing:
        raise SystemExit(f"stack has no output {', '.join(missing)}: deploy LitFetchApi first")
    return "".join(f"{var}={got[key]}\n" for key, var in NAMES.items())


def main(argv=None):
    ap = argparse.ArgumentParser(description="write web/.env.local from the LitFetchApi outputs")
    ap.add_argument("--profile", help="AWS CLI profile (e.g. litfetch)")
    ap.add_argument("--stack", default="LitFetchApi")
    ap.add_argument("--out", default=os.path.join(ROOT, "web", ".env.local"))
    args = ap.parse_args(argv)

    import boto3
    session = boto3.Session(profile_name=args.profile, region_name="us-east-2")
    stack = session.client("cloudformation").describe_stacks(StackName=args.stack)["Stacks"][0]
    text = env_text(stack.get("Outputs", []))
    with open(args.out, "w") as f:
        f.write(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
