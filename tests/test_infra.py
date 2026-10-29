"""The CDK data stack synthesizes to the table the code expects. Skipped when aws-cdk-lib isn't
installed (pip install -r infra/requirements.txt)."""
import os
import sys

import pytest

cdk = pytest.importorskip("aws_cdk")
from aws_cdk.assertions import Match, Template  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "infra"))
from litfetch_infra.data_stack import TABLE_NAME, DataStack  # noqa: E402

from digest import dynamo_store  # noqa: E402


@pytest.fixture(scope="module")
def template():
    app = cdk.App()
    stack = DataStack(app, "Test", env=cdk.Environment(account="123456789012", region="us-east-2"))
    return Template.from_stack(stack)


def test_one_table_and_nothing_else(template):
    template.resource_count_is("AWS::DynamoDB::Table", 1)
    assert set(r["Type"] for r in template.to_json()["Resources"].values()) == {"AWS::DynamoDB::Table"}


def test_table_matches_what_dynamo_store_uses(template):
    assert TABLE_NAME == dynamo_store.DEFAULT_TABLE
    template.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": TABLE_NAME,
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
    })


def test_stays_inside_the_always_free_tier(template):
    template.has_resource_properties("AWS::DynamoDB::Table", {
        "ProvisionedThroughput": {"ReadCapacityUnits": Match.any_value(), "WriteCapacityUnits": Match.any_value()},
    })
    (table,) = template.find_resources("AWS::DynamoDB::Table").values()
    t = table["Properties"]["ProvisionedThroughput"]
    assert t["ReadCapacityUnits"] <= 25 and t["WriteCapacityUnits"] <= 25     # free: 25 each, account-wide
    assert "BillingMode" not in table["Properties"]                            # not PAY_PER_REQUEST


def test_data_survives_stack_deletion(template):
    (table,) = template.find_resources("AWS::DynamoDB::Table").values()
    assert table["DeletionPolicy"] == "Retain" and table["UpdateReplacePolicy"] == "Retain"
    assert table["Properties"]["DeletionProtectionEnabled"] is True


# ---- backend stack (worker Lambda) ----

from aws_cdk import aws_lambda as lambda_  # noqa: E402
from litfetch_infra.backend_stack import (DISPATCH_NAME, FAILED_QUEUE, JOBS_QUEUE, MAX_TRIES,  # noqa: E402
                                         SCHEDULE_NAME, SSM_PREFIX, WORKER_NAME, BackendStack)


def make_backend(**kw):
    app = cdk.App()
    stack = BackendStack(app, "Backend", env=cdk.Environment(account="123456789012", region="us-east-2"),
                         code=lambda_.Code.from_inline("def handler(event, context): pass"),   # no pip in tests
                         **kw)
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def backend():
    return make_backend()


def test_worker_function_settings(backend):
    backend.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": WORKER_NAME,
        "Runtime": "python3.12",
        "Architectures": ["arm64"],
        "Handler": "api.worker.handler",
        "Timeout": 900,
        "MemorySize": 1024,
        "Environment": {"Variables": {"LITFETCH_TABLE": TABLE_NAME, "LITFETCH_SSM_PREFIX": SSM_PREFIX,
                                      "LITFETCH_DRY_RUN_DEFAULT": "true"}},
    })


def test_failed_runs_are_not_retried(backend):
    backend.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})


def test_logs_expire(backend):
    backend.has_resource_properties("AWS::Logs::LogGroup", {
        "LogGroupName": f"/aws/lambda/{WORKER_NAME}", "RetentionInDays": 14})


def policy_of(template, role_prefix):
    (policy,) = [r for k, r in template.find_resources("AWS::IAM::Policy").items() if k.startswith(role_prefix)]
    return policy


def test_permissions_are_only_the_table_and_its_parameters(backend):
    policy = policy_of(backend, "WorkerServiceRole")
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    text = str(statements)
    assert "dynamodb:PutItem" in text and "dynamodb:Query" in text and f"table/{TABLE_NAME}" in text
    ssm = [s for s in statements if s["Action"] == "ssm:GetParametersByPath"]
    assert ssm and all("parameter/litfetch" in str(r) for r in ssm[0]["Resource"])
    kms = [s for s in statements if s["Action"] == "kms:Decrypt"]
    assert kms[0]["Condition"] == {"StringEquals": {"kms:ViaService": "ssm.us-east-2.amazonaws.com"}}
    assert any("sqs:ReceiveMessage" in s["Action"] for s in statements)      # reads its job queue
    assert not any(s["Action"] == "*" or s.get("Resource") == "*" and s["Action"] != "kms:Decrypt"
                   for s in statements)                    # no wildcard permissions besides the scoped KMS one


def test_package_contains_only_code_not_secrets_or_data():
    from litfetch_infra import bundling
    names = {rel.split("/")[0] for rel, _ in bundling._files()}
    assert names == {"digest", "api", "config.yaml", "requirements-lambda.txt"}


# ---- M4: queue, dispatch, schedule, alerts ----

def test_jobs_queue_is_fifo_with_a_failed_jobs_queue(backend):
    backend.has_resource_properties("AWS::SQS::Queue", {
        "QueueName": JOBS_QUEUE, "FifoQueue": True,
        "VisibilityTimeout": 5400,                            # >= 6 x the worker's 900 s, as AWS advises
        "RedrivePolicy": {"maxReceiveCount": MAX_TRIES, "deadLetterTargetArn": Match.any_value()},
    })
    backend.has_resource_properties("AWS::SQS::Queue", {
        "QueueName": FAILED_QUEUE, "FifoQueue": True, "MessageRetentionPeriod": 14 * 86400})


def test_worker_reads_the_queue_one_job_at_a_time(backend):
    backend.has_resource_properties("AWS::Lambda::EventSourceMapping", {
        "BatchSize": 1, "FunctionResponseTypes": ["ReportBatchItemFailures"]})


def test_dispatch_function_and_its_permissions(backend):
    backend.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": DISPATCH_NAME, "Handler": "api.dispatch.handler", "Architectures": ["arm64"],
        "Environment": {"Variables": {"LITFETCH_TABLE": TABLE_NAME, "LITFETCH_QUEUE_URL": Match.any_value()}},
    })
    actions = str(policy_of(backend, "DispatchServiceRole")["Properties"]["PolicyDocument"])
    assert "dynamodb:Scan" in actions and "sqs:SendMessage" in actions
    assert "dynamodb:PutItem" not in actions and "ssm:" not in actions          # read-only, no secrets


def test_schedule_is_mondays_7am_new_york_and_off_by_default(backend):
    backend.has_resource_properties("AWS::Scheduler::Schedule", {
        "Name": SCHEDULE_NAME, "ScheduleExpression": "cron(0 7 ? * MON *)",
        "ScheduleExpressionTimezone": "America/New_York", "State": "DISABLED"})


def test_schedule_can_be_turned_on():
    make_backend(schedule_enabled=True).has_resource_properties(
        "AWS::Scheduler::Schedule", {"State": "ENABLED"})


def test_three_alarms_email_the_alerts_topic(backend):
    alarms = backend.find_resources("AWS::CloudWatch::Alarm")
    assert len(alarms) == 3                                   # free tier: 10
    assert all(a["Properties"]["AlarmActions"] and a["Properties"]["TreatMissingData"] == "notBreaching"
               for a in alarms.values())
    backend.has_resource_properties("AWS::Logs::MetricFilter", {"FilterPattern": '"posting failed"'})
    backend.resource_count_is("AWS::SNS::Subscription", 0)    # no email unless one is given


def test_alert_email_is_subscribed_when_given():
    make_backend(alert_email="me@example.edu").has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "me@example.edu"})


# ---- M5: sign-in and API ----

from litfetch_infra import api_stack  # noqa: E402
from api import http as api_http  # noqa: E402


@pytest.fixture(scope="module")
def api_template():
    app = cdk.App()
    stack = api_stack.ApiStack(app, "Api", env=cdk.Environment(account="123456789012", region="us-east-2"),
                               code=lambda_.Code.from_inline("def handler(event, context): pass"),
                               web_origins=["http://localhost:5173", "https://site.example"])
    return Template.from_stack(stack)


def test_user_pool_is_invite_only_email_login_and_kept(api_template):
    pools = api_template.find_resources("AWS::Cognito::UserPool")
    (pool,) = pools.values()
    props = pool["Properties"]
    assert pool["DeletionPolicy"] == "Retain" and props["DeletionProtection"] == "ACTIVE"
    assert props["UsernameAttributes"] == ["email"] and props["AutoVerifiedAttributes"] == ["email"]
    assert props["UserPoolTier"] == "LITE"
    assert "PreSignUp" in props["LambdaConfig"]
    api_template.has_resource_properties("AWS::Cognito::UserPoolGroup", {"GroupName": "admins"})


def test_web_client_has_no_secret(api_template):
    api_template.has_resource_properties("AWS::Cognito::UserPoolClient", {
        "GenerateSecret": False, "PreventUserExistenceErrors": "ENABLED",
        "ExplicitAuthFlows": Match.array_with(["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])})


def test_every_api_route_exists_and_only_health_is_public(api_template):
    routes = {r["Properties"]["RouteKey"]: r["Properties"].get("AuthorizationType", "NONE")
              for r in api_template.find_resources("AWS::ApiGatewayV2::Route").values()}
    assert set(routes) == {f"{m} {p}" for (m, p) in api_http.ROUTES}       # infra matches api/http.py
    assert {k for k, auth in routes.items() if auth != "JWT"} == {"GET /health"}


def test_cors_and_throttling(api_template):
    api_template.has_resource_properties("AWS::ApiGatewayV2::Api", {"CorsConfiguration": {
        "AllowOrigins": ["http://localhost:5173", "https://site.example"],
        "AllowHeaders": ["authorization", "content-type"],
        "AllowMethods": Match.any_value(), "MaxAge": 3600}})
    api_template.has_resource_properties("AWS::ApiGatewayV2::Stage", {
        "DefaultRouteSettings": {"ThrottlingRateLimit": 10, "ThrottlingBurstLimit": 20}})


def test_api_function_permissions_are_scoped(api_template):
    policy = policy_of(api_template, "ApiFnServiceRole")
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    webhook = [s for s in statements if "ssm:PutParameter" in s["Action"]]
    assert webhook and all("SLACK_WEBHOOK_*" in str(r) for r in [webhook[0]["Resource"]])
    assert any(s["Action"] == "cognito-idp:AdminDeleteUser" for s in statements)
    assert not any(s.get("Resource") == "*" and "kms:" not in str(s["Action"]) for s in statements)
    presignup = str(policy_of(api_template, "PreSignUpServiceRole")["Properties"]["PolicyDocument"])
    assert "dynamodb:UpdateItem" in presignup and "PutItem" not in presignup and "Scan" not in presignup


# ---------- website stack (M7) ----------

from litfetch_infra import web_stack  # noqa: E402

ENV = cdk.Environment(account="123456789012", region="us-east-2")


@pytest.fixture(scope="module")
def built_site(tmp_path_factory):
    d = tmp_path_factory.mktemp("dist")
    (d / "assets").mkdir()
    (d / "index.html").write_text("<html></html>")
    (d / "assets" / "index-abc123.js").write_text("console.log(1)")
    return str(d)


@pytest.fixture(scope="module")
def web(built_site):
    app = cdk.App()
    stack = web_stack.WebStack(app, "Web", env=ENV, dist_dir=built_site)
    return stack, Template.from_stack(stack)


def test_bucket_is_private_and_https_only(web):
    _, t = web
    t.has_resource_properties("AWS::S3::Bucket", {"PublicAccessBlockConfiguration": {
        "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True}})
    statements = [s for p in t.find_resources("AWS::S3::BucketPolicy").values()
                  for s in p["Properties"]["PolicyDocument"]["Statement"]]
    assert any(s["Effect"] == "Deny" and s["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
               for s in statements)
    reads = [s for s in statements if s["Action"] == "s3:GetObject"]
    assert len(reads) == 1                                        # only CloudFront reads files
    assert reads[0]["Principal"] == {"Service": "cloudfront.amazonaws.com"}
    assert "AWS:SourceArn" in reads[0]["Condition"]["StringEquals"]   # ...and only this distribution


def test_cloudfront_uses_oac_https_and_spa_routing(web):
    _, t = web
    t.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)
    (dist,) = t.find_resources("AWS::CloudFront::Distribution").values()
    cfg = dist["Properties"]["DistributionConfig"]
    assert "OriginAccessControlId" in cfg["Origins"][0]
    assert cfg["DefaultRootObject"] == "index.html"
    assert cfg["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    assert cfg["PriceClass"] == "PriceClass_100"
    assert {(e["ErrorCode"], e["ResponseCode"], e["ResponsePagePath"]) for e in cfg["CustomErrorResponses"]} == {
        (403, 200, "/index.html"), (404, 200, "/index.html")}


def test_deploys_assets_cached_and_index_not_cached(web):
    _, t = web
    deployments = t.find_resources("Custom::CDKBucketDeployment")
    assert len(deployments) == 2
    by_cache = {str(d["Properties"].get("SystemMetadata")): d["Properties"] for d in deployments.values()}
    long = next(p for k, p in by_cache.items() if "immutable" in k)
    index = next(p for k, p in by_cache.items() if "no-cache" in k)
    assert "DistributionId" not in long and index["DistributionPaths"] == ["/index.html"]
    assert long["Prune"] is False and index["Prune"] is False


def test_index_and_assets_are_split(built_site, tmp_path):
    app = cdk.App(outdir=str(tmp_path))
    web_stack.WebStack(app, "Web", env=ENV, dist_dir=built_site)
    app.synth()
    folders = [p for p in tmp_path.glob("asset.*") if p.is_dir()]
    contents = {tuple(sorted(str(f.relative_to(p)) for f in p.rglob("*") if f.is_file())) for p in folders}
    assert ("index.html",) in contents and ("assets/index-abc123.js",) in contents


def test_no_build_means_no_deployment(tmp_path):
    app = cdk.App()
    stack = web_stack.WebStack(app, "Web", env=ENV, dist_dir=str(tmp_path))
    Template.from_stack(stack).resource_count_is("Custom::CDKBucketDeployment", 0)


def test_api_cors_allows_the_cloudfront_site(built_site):
    app = cdk.App()
    stack = web_stack.WebStack(app, "Web", env=ENV, dist_dir=built_site)
    api = api_stack.ApiStack(app, "ApiWithSite", env=ENV,
                             code=lambda_.Code.from_inline("def handler(event, context): pass"),
                             web_origins=[stack.url, "http://localhost:5173"])
    (cors_api,) = Template.from_stack(api).find_resources("AWS::ApiGatewayV2::Api").values()
    origins = cors_api["Properties"]["CorsConfiguration"]["AllowOrigins"]
    assert "http://localhost:5173" in origins and "Fn::ImportValue" in str(origins[0])
