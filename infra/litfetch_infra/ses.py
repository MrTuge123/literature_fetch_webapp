"""Email from the Lambdas through Amazon SES (M8).

SES sends only from identities (addresses or domains) verified in this account and region. While
the account is in the SES sandbox it also sends only TO verified identities, at most 200 a day;
production access lifts that (request it in the SES console). The sender address is the
Parameter Store value /litfetch/SES_FROM, read by digest/notify/mail.py.

Cost: 3,000 messages a month free for the first 12 months, then $0.10 per 1,000.
"""
from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_

ENVIRONMENT = {"LITFETCH_EMAIL_VIA": "ses"}       # digest/notify/mail.py: send with SES, not SMTP


def allow_sending(fn: lambda_.Function) -> None:
    """Let fn send email through SES from (and, in the sandbox, to) verified identities.
    Identities are the only resource SES checks, and unverified ones can't send anyway."""
    stack = Stack.of(fn)
    for name, value in ENVIRONMENT.items():
        fn.add_environment(name, value)
    fn.add_to_role_policy(iam.PolicyStatement(
        actions=["ses:SendEmail", "ses:SendRawEmail"],
        resources=[f"arn:aws:ses:{stack.region}:{stack.account}:identity/*"],
    ))
