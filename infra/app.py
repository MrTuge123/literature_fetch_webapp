"""CDK app for Literature Fetch. Every stack goes to the project's home region, us-east-2
(the account's AWS-managed rules block most services in other regions).

    cdk diff   --profile litfetch     what a deploy would change
    cdk deploy --profile litfetch     apply it
"""
import os

import aws_cdk as cdk

from litfetch_infra.api_stack import ApiStack
from litfetch_infra.backend_stack import BackendStack
from litfetch_infra.data_stack import DataStack
from litfetch_infra.web_stack import WebStack

REGION = "us-east-2"

app = cdk.App()
env = cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=REGION)

DataStack(app, "LitFetchData", env=env,
          description="Literature Fetch: one DynamoDB table for preferences, seen papers and history")
# The weekly run is set in cdk.json (committed, so every deploy keeps it):
#   "schedule": "on" | "off"     whether litfetch-weekly runs on Mondays
#   "dryRun":   "on" | "off"     on = jobs only log what they'd send; off = really send (M9 cut-over)
# Who gets alarm emails is personal, so it stays out of the repo: put it in ~/.cdk.json as
#   {"context": {"alertEmail": "you@umich.edu"}}     (or set LITFETCH_ALERT_EMAIL).
# Without it, deploying would unsubscribe the alarm emails, so it's required (unless "none").
def flag(name, default):
    value = str(app.node.try_get_context(name) or default).lower()
    if value not in ("on", "off"):
        raise SystemExit(f'cdk.json context "{name}" must be "on" or "off", not {value!r}')
    return value == "on"


alert_email = app.node.try_get_context("alertEmail") or os.getenv("LITFETCH_ALERT_EMAIL")
if not alert_email:
    raise SystemExit('Set the alarm email first: ~/.cdk.json {"context": {"alertEmail": "you@umich.edu"}} '
                     '(or LITFETCH_ALERT_EMAIL=...); use "none" for no alarm emails.')
BackendStack(app, "LitFetchBackend", env=env,
             schedule_enabled=flag("schedule", "off"),
             dry_run_default=flag("dryRun", "on"),
             alert_email=None if alert_email == "none" else alert_email,
             description="Literature Fetch: weekly schedule, dispatch, jobs queue, worker, alerts")

# Build the site first (cd web && npm run build): this copies web/dist to S3 behind CloudFront.
web = WebStack(app, "LitFetchWeb", env=env,
               description="Literature Fetch: the website (private S3 bucket behind CloudFront)")

# Browsers may call the API only from the CloudFront site, plus the local dev server unless
#   cdk deploy -c localDev=off ...
# and any extra sites in  -c webOrigins=https://a.example,https://b.example
origins = [web.url]
if app.node.try_get_context("localDev") != "off":
    origins.append("http://localhost:5173")
origins += [o for o in (app.node.try_get_context("webOrigins") or "").split(",") if o]
ApiStack(app, "LitFetchApi", env=env, web_origins=origins,
         description="Literature Fetch: sign-in (Cognito) and the website's API")

cdk.Tags.of(app).add("project", "literature-fetch")       # every resource, so costs can be filtered
app.synth()
