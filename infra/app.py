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
# cdk deploy -c schedule=on   turns the weekly schedule on (do it at the M9 cut-over)
# LITFETCH_ALERT_EMAIL=you@x  who gets alarm emails (kept out of the repo; AWS asks you to confirm)
BackendStack(app, "LitFetchBackend", env=env,
             schedule_enabled=app.node.try_get_context("schedule") == "on",
             alert_email=os.getenv("LITFETCH_ALERT_EMAIL"),
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
