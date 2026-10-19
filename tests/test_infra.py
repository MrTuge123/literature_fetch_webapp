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
