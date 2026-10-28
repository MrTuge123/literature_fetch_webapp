"""The backend stack: the worker Lambda (M3). The queue and weekly schedule join it in M4.

    litfetch-worker   Python 3.12 on arm64 (Graviton: ~20% cheaper than x86), 1 GB, 15 min.
                      Reads/writes only the LitFetch table and reads only /litfetch/* parameters.
                      Async retries off: a failed run must not post twice. Logs kept 2 weeks.
"""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from litfetch_infra.data_stack import TABLE_NAME

WORKER_NAME = "litfetch-worker"
SSM_PREFIX = "/litfetch/"


class BackendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, code: lambda_.Code | None = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if code is None:
            from litfetch_infra.bundling import worker_code
            code = worker_code()

        # By name, not a cross-stack reference: the data stack stays independent of this one.
        table = dynamodb.Table.from_table_name(self, "Table", TABLE_NAME)

        log_group = logs.LogGroup(
            self, "WorkerLogs",
            log_group_name=f"/aws/lambda/{WORKER_NAME}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.worker = lambda_.Function(
            self, "Worker",
            function_name=WORKER_NAME,
            description="Literature Fetch: one subscriber's paper digest per job",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="api.worker.handler",
            code=code,
            memory_size=1024,
            timeout=Duration.minutes(15),
            retry_attempts=0,
            log_group=log_group,
            environment={
                "LITFETCH_TABLE": TABLE_NAME,
                "LITFETCH_SSM_PREFIX": SSM_PREFIX,
                "LITFETCH_DRY_RUN_DEFAULT": "true",          # until the M9 cut-over
            },
        )

        table.grant_read_write_data(self.worker)
        path = SSM_PREFIX.rstrip("/")
        self.worker.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParametersByPath"],
            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter{path}",
                       f"arn:aws:ssm:{self.region}:{self.account}:parameter{path}/*"],
        ))
        self.worker.add_to_role_policy(iam.PolicyStatement(        # decrypt SecureStrings, via SSM only
            actions=["kms:Decrypt"],
            resources=["*"],
            conditions={"StringEquals": {"kms:ViaService": f"ssm.{self.region}.amazonaws.com"}},
        ))

        CfnOutput(self, "WorkerName", value=self.worker.function_name)
