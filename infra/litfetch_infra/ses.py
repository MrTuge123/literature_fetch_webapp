"""How the Lambdas send email: "ses" (Amazon SES) or "smtp" (a mail account, e.g. Gmail).

    ses    SES sends only from identities verified in this account and region; while the account
           is in the SES sandbox, also only TO verified identities (200 a day). Sender: the
           Parameter Store value /litfetch/SES_FROM. Mail from a gmail.com or umich.edu address
           sent by SES fails those domains' DMARC check, so it tends to land in spam; SES is
           best with a domain you own (DKIM). Cost: 3,000 a month free for 12 months, then
           $0.10 per 1,000.
    smtp   The account's own mail server (Gmail: smtp.gmail.com, an app password), so Google signs
           the mail and it reaches the inbox. No sandbox; Gmail allows about 500 recipients a day.
           Login: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD (+ optional SMTP_FROM) in
           Parameter Store. No AWS permission needed.

digest/notify/mail.py reads LITFETCH_EMAIL_VIA to pick one. Chosen in infra/cdk.json ("email").
"""
from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_

WAYS = ("ses", "smtp")


def allow_sending(fn: lambda_.Function, via: str = "ses") -> None:
    """Tell fn how to send email; with SES, also let it send from (and, in the sandbox, to)
    verified identities. Identities are the only resource SES checks."""
    if via not in WAYS:
        raise ValueError(f"email must be one of {WAYS}, not {via!r}")
    fn.add_environment("LITFETCH_EMAIL_VIA", via)
    if via == "ses":
        stack = Stack.of(fn)
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ses:SendEmail", "ses:SendRawEmail"],
            resources=[f"arn:aws:ses:{stack.region}:{stack.account}:identity/*"],
        ))
