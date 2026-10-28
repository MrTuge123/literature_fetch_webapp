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
from litfetch_infra.backend_stack import SSM_PREFIX, WORKER_NAME, BackendStack  # noqa: E402


@pytest.fixture(scope="module")
def backend():
    app = cdk.App()
    stack = BackendStack(app, "Backend", env=cdk.Environment(account="123456789012", region="us-east-2"),
                         code=lambda_.Code.from_inline("def handler(event, context): pass"))   # no pip in tests
    return Template.from_stack(stack)


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


def test_permissions_are_only_the_table_and_its_parameters(backend):
    (policy,) = backend.find_resources("AWS::IAM::Policy").values()
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    text = str(statements)
    assert "dynamodb:PutItem" in text and "dynamodb:Query" in text and f"table/{TABLE_NAME}" in text
    ssm = [s for s in statements if s["Action"] == "ssm:GetParametersByPath"]
    assert ssm and all("parameter/litfetch" in str(r) for r in ssm[0]["Resource"])
    kms = [s for s in statements if s["Action"] == "kms:Decrypt"]
    assert kms[0]["Condition"] == {"StringEquals": {"kms:ViaService": "ssm.us-east-2.amazonaws.com"}}
    assert not any(s["Action"] == "*" or s.get("Resource") == "*" and s["Action"] != "kms:Decrypt"
                   for s in statements)                    # no wildcard permissions besides the scoped KMS one


def test_package_contains_only_code_not_secrets_or_data():
    from litfetch_infra import bundling
    names = {rel.split("/")[0] for rel, _ in bundling._files()}
    assert names == {"digest", "api", "config.yaml", "requirements-lambda.txt"}
