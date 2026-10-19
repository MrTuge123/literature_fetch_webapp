"""The data stack: the LitFetch table, and nothing else, so redeploying the backend (Lambdas,
queue, API) can never touch user data.

Single-table design (docs/SPEC.md, Data model). Every item of one subscriber shares
PK = USER#<id>; SK says what the item is:
    PREFS                    their settings (digest.prefs.Preferences)
    SEEN#<paper id>          one item per ID of every paper they've received (PMID, DOI, arxiv:, title:)
    HIST#<paper id>          one item per ranked candidate (digest.history.record), id = its smallest ID

Capacity: provisioned 10 reads + 10 writes per second. DynamoDB's always-free tier covers 25 of
each, so this costs $0; on-demand would bill per request.
"""
from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

TABLE_NAME = "LitFetch"
READ_CAPACITY = 10
WRITE_CAPACITY = 10


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.table = dynamodb.Table(
            self, "Table",
            table_name=TABLE_NAME,                      # fixed name: scripts and Lambdas find it by name
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PROVISIONED,
            read_capacity=READ_CAPACITY,
            write_capacity=WRITE_CAPACITY,
            time_to_live_attribute="ttl",               # items with a past ttl (epoch seconds) are deleted, free
            removal_policy=RemovalPolicy.RETAIN,        # cdk destroy leaves the table and its data
            deletion_protection=True,                   # and nobody can delete it by accident in the console
        )

        CfnOutput(self, "TableName", value=self.table.table_name)
