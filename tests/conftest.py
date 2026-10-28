"""Shared test setup: run from the repo root (config.yaml is read by relative path), block the
network so no test can reach PubMed, an LLM or Slack by accident, and provide a fake DynamoDB."""
import os
import socket

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch):
    monkeypatch.chdir(ROOT)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise RuntimeError("network access in a test (mock it instead)")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def dynamo_table(aws):
    """An empty LitFetch table in moto's in-memory DynamoDB (same keys and TTL as infra/)."""
    import boto3
    client = boto3.client("dynamodb", region_name="us-east-2")
    client.create_table(
        TableName="LitFetch",
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                              {"AttributeName": "SK", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 10, "WriteCapacityUnits": 10},
    )
    client.update_time_to_live(TableName="LitFetch",
                               TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"})
    return boto3.resource("dynamodb", region_name="us-east-2").Table("LitFetch")


@pytest.fixture
def aws(monkeypatch):
    """moto's in-memory AWS (every service) with fake credentials; yields the moto module."""
    moto = pytest.importorskip("moto")
    for k, v in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
                 "AWS_SESSION_TOKEN": "test", "AWS_DEFAULT_REGION": "us-east-2"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with moto.mock_aws():
        yield moto
