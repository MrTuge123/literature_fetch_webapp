"""Email through SES (M8): what mail.send hands to SES, and how its errors are reported."""
from email.message import EmailMessage

import pytest
from botocore.exceptions import ClientError

from digest import env
from digest.notify import mail


class FakeSecrets:
    def __init__(self, values):
        self.values = values

    def get(self, name):
        return self.values.get(name)


class FakeSES:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def send_email(self, **kw):
        if self.error:
            raise ClientError({"Error": {"Code": "MessageRejected", "Message": self.error}}, "SendEmail")
        self.calls.append(kw)


@pytest.fixture
def ses(monkeypatch):
    monkeypatch.setenv("LITFETCH_EMAIL_VIA", "ses")
    previous = env.use(FakeSecrets({"SES_FROM": "digest@example.edu"}))
    fake = FakeSES()
    monkeypatch.setattr(mail, "_ses_client", lambda: fake)
    yield fake
    env.use(previous)


def message():
    msg = EmailMessage()
    msg["Subject"] = "3 new papers"
    msg.set_content("hello")
    return msg


def test_via_defaults_to_smtp(monkeypatch):
    monkeypatch.delenv("LITFETCH_EMAIL_VIA", raising=False)
    assert mail.via() == "smtp"
    monkeypatch.setenv("LITFETCH_EMAIL_VIA", "SES")
    assert mail.via() == "ses"


def test_sends_raw_message_from_ses_from_with_recipients_hidden(ses):
    mail.send(["a@umich.edu", "b@umich.edu"], message())
    (call,) = ses.calls
    assert call["FromEmailAddress"] == "digest@example.edu"
    assert call["Destination"] == {"ToAddresses": ["a@umich.edu", "b@umich.edu"]}
    raw = call["Content"]["Raw"]["Data"].decode()
    assert "From: Paper Digest <digest@example.edu>" in raw
    assert "a@umich.edu" not in raw and "b@umich.edu" not in raw          # like Bcc
    assert "Subject: 3 new papers" in raw


def test_more_than_50_recipients_go_in_batches(ses):
    mail.send([f"p{i}@umich.edu" for i in range(120)], message())
    assert [len(c["Destination"]["ToAddresses"]) for c in ses.calls] == [50, 50, 20]


def test_ses_refusal_becomes_a_readable_runtime_error(ses, monkeypatch):
    monkeypatch.setattr(mail, "_ses_client",
                        lambda: FakeSES("Email address is not verified. The following identities failed"))
    with pytest.raises(RuntimeError, match="sandbox"):
        mail.send(["a@umich.edu"], message())


def test_missing_sender_is_reported(ses):
    env.use(FakeSecrets({}))
    with pytest.raises(RuntimeError, match="SES_FROM"):
        mail.send(["a@umich.edu"], message())
    to, problem = mail.destination({"to": ["a@umich.edu"]})
    assert to is None and "SES_FROM" in problem and "Parameter Store" in problem


def test_destination_with_ses_needs_no_smtp_login(ses):
    assert mail.destination({"to": ["a@umich.edu"]}) == (["a@umich.edu"], None)
