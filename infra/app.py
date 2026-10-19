"""CDK app for Literature Fetch. Every stack goes to the project's home region, us-east-2
(the account's AWS-managed rules block most services in other regions).

    cdk diff   --profile litfetch     what a deploy would change
    cdk deploy --profile litfetch     apply it
"""
import os

import aws_cdk as cdk

from litfetch_infra.data_stack import DataStack

REGION = "us-east-2"

app = cdk.App()
env = cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=REGION)

DataStack(app, "LitFetchData", env=env,
          description="Literature Fetch: one DynamoDB table for preferences, seen papers and history")

cdk.Tags.of(app).add("project", "literature-fetch")       # every resource, so costs can be filtered
app.synth()
