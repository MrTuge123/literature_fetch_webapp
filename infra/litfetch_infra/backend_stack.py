"""The backend stack: everything that runs the weekly digest.

    litfetch-weekly        EventBridge Scheduler, Mondays 7:00 New York time -> litfetch-dispatch.
                           Created switched off; deploy with -c schedule=on at the M9 cut-over.
    litfetch-dispatch      Lambda: one job per subscriber -> litfetch-jobs.fifo.
    litfetch-jobs.fifo     SQS FIFO queue. One message group, so the worker gets one user at a time.
                           A job that fails twice moves to litfetch-jobs-failed.fifo (kept 14 days).
    litfetch-worker        Lambda (M3): Python 3.12 on arm64, 1 GB, 15 min, one subscriber per job.
                           Reads/writes only the LitFetch table, reads only /litfetch/* parameters.
    litfetch-alerts        SNS topic; emails you when a job fails, dispatch errors, or posting fails.
"""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, TimeZone
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_scheduler_targets as scheduler_targets
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subscriptions
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from litfetch_infra.data_stack import TABLE_NAME

WORKER_NAME = "litfetch-worker"
DISPATCH_NAME = "litfetch-dispatch"
JOBS_QUEUE = "litfetch-jobs.fifo"
FAILED_QUEUE = "litfetch-jobs-failed.fifo"
SCHEDULE_NAME = "litfetch-weekly"
ALERTS_TOPIC = "litfetch-alerts"
SSM_PREFIX = "/litfetch/"
MAX_TRIES = 2                       # a job that fails twice goes to the failed-jobs queue


class BackendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, code: lambda_.Code | None = None,
                 schedule_enabled: bool = False, alert_email: str | None = None, **kwargs) -> None:
        """code: the Lambda zip (default: built by bundling.py; tests pass a stub).
        schedule_enabled: whether the weekly schedule runs (off until the M9 cut-over).
        alert_email: who gets alarm emails (AWS sends a confirmation link first)."""
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

        # ---- Queue: one job per subscriber, handed to the worker one at a time ----
        self.failed_jobs = sqs.Queue(
            self, "FailedJobs",
            queue_name=FAILED_QUEUE,
            fifo=True,
            retention_period=Duration.days(14),          # time to look at what failed and resend it
        )
        self.jobs = sqs.Queue(
            self, "Jobs",
            queue_name=JOBS_QUEUE,
            fifo=True,                                   # + one message group = strictly one at a time
            visibility_timeout=Duration.minutes(90),     # AWS: >= 6 x the worker's 15-min timeout
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(queue=self.failed_jobs, max_receive_count=MAX_TRIES),
        )
        self.worker.add_event_source(event_sources.SqsEventSource(
            self.jobs,
            batch_size=1,                                # one subscriber per worker run
            report_batch_item_failures=True,             # api/worker.py returns batchItemFailures
        ))

        # ---- Dispatch: who gets a digest this round ----
        dispatch_logs = logs.LogGroup(
            self, "DispatchLogs",
            log_group_name=f"/aws/lambda/{DISPATCH_NAME}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.dispatch = lambda_.Function(
            self, "Dispatch",
            function_name=DISPATCH_NAME,
            description="Literature Fetch: queue one digest job per subscriber",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="api.dispatch.handler",
            code=code,                                   # same zip as the worker, different entry point
            memory_size=256,
            timeout=Duration.minutes(1),
            log_group=dispatch_logs,
            environment={"LITFETCH_TABLE": TABLE_NAME, "LITFETCH_QUEUE_URL": self.jobs.queue_url},
        )
        table.grant_read_data(self.dispatch)             # list subscribers (PREFS items)
        self.jobs.grant_send_messages(self.dispatch)

        # ---- Schedule: Mondays 7:00 New York time (handles daylight saving) ----
        self.schedule = scheduler.Schedule(
            self, "Weekly",
            schedule_name=SCHEDULE_NAME,
            description="Literature Fetch: weekly digests",
            schedule=scheduler.ScheduleExpression.cron(
                minute="0", hour="7", week_day="MON", time_zone=TimeZone.AMERICA_NEW_YORK),
            target=scheduler_targets.LambdaInvoke(
                self.dispatch, input=scheduler.ScheduleTargetInput.from_object({}),
                retry_attempts=3, max_event_age=Duration.hours(1)),   # if Lambda can't be reached
            enabled=schedule_enabled,
        )

        # ---- Alerts: email when something needs a look ----
        self.alerts = sns.Topic(self, "Alerts", topic_name=ALERTS_TOPIC)
        if alert_email:
            self.alerts.add_subscription(sns_subscriptions.EmailSubscription(alert_email))
        posting_failures = logs.MetricFilter(
            self, "PostingFailures",
            log_group=log_group,
            metric_namespace="LitFetch",
            metric_name="PostingFailures",
            filter_pattern=logs.FilterPattern.literal('"posting failed"'),   # api/worker.py's warning
            metric_value="1",
        )
        alarms = {
            "FailedJobsAlarm": ("A digest job failed twice and is in the failed-jobs queue",
                                self.failed_jobs.metric_approximate_number_of_messages_visible(
                                    period=Duration.minutes(5), statistic="Maximum")),
            "DispatchErrorsAlarm": ("The weekly dispatch Lambda failed",
                                    self.dispatch.metric_errors(period=Duration.minutes(5))),
            "PostingFailuresAlarm": ("A digest ran but could not post to a chat (Slack/WeCom/email)",
                                     posting_failures.metric(period=Duration.minutes(5), statistic="Sum")),
        }
        for alarm_id, (text, metric) in alarms.items():
            alarm = cloudwatch.Alarm(
                self, alarm_id,
                alarm_description=f"Literature Fetch: {text}",
                metric=metric,
                threshold=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                evaluation_periods=1,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.alerts))

        CfnOutput(self, "WorkerName", value=self.worker.function_name)
        CfnOutput(self, "DispatchName", value=self.dispatch.function_name)
        CfnOutput(self, "JobsQueueUrl", value=self.jobs.queue_url)
        CfnOutput(self, "FailedJobsQueueUrl", value=self.failed_jobs.queue_url)
        CfnOutput(self, "ScheduleEnabled", value=str(schedule_enabled))
