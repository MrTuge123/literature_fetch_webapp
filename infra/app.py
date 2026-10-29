"""CDK app for Literature Fetch. Every stack goes to the project's home region, us-east-2
(the account's AWS-managed rules block most services in other regions).

    cdk diff   --profile litfetch     what a deploy would change
    cdk deploy --profile litfetch     apply it
"""
import os

import aws_cdk as cdk

from litfetch_infra.backend_stack import BackendStack
from litfetch_infra.data_stack import DataStack

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

cdk.Tags.of(app).add("project", "literature-fetch")       # every resource, so costs can be filtered
app.synth()
