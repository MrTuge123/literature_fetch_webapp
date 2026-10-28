"""scripts/put_secrets.py stores .env values as SecureStrings, never prints them, and points out
secrets the subscribers need that .env doesn't have."""
import importlib.util
import os
import shutil

import boto3
import pytest

from tests.test_prefs import ROOT_CONFIG

spec = importlib.util.spec_from_file_location("put_secrets", os.path.join("scripts", "put_secrets.py"))
put_secrets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(put_secrets)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    shutil.copy(ROOT_CONFIG, tmp_path / "config.yaml")
    (tmp_path / "subscribers").mkdir()
    (tmp_path / "subscribers" / "lab.yaml").write_text(
        'query: "a AND b"\noutputs:\n  slack: {enabled: true, webhook_env: SLACK_WEBHOOK_URL}\n'
        '  email: {enabled: true, to_env: EMAIL_TO_LAB}\n')
    (tmp_path / ".env").write_text("GROQ_API_KEY=gsk-secret-value\nSLACK_WEBHOOK_URL=https://hooks.slack.com/x\nEMPTY=\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_dry_run_lists_names_and_what_is_missing(folder, capsys):
    assert put_secrets.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "/litfetch/GROQ_API_KEY" in out and "/litfetch/SLACK_WEBHOOK_URL" in out
    assert "EMAIL_TO_LAB" in out.split("not in .env")[1]
    assert "EMPTY" not in out and "gsk-secret-value" not in out


def test_stores_secure_strings_without_printing_values(folder, aws, capsys, monkeypatch):
    monkeypatch.setattr(put_secrets.getpass, "getpass", lambda prompt: "lab@umich.edu ")
    assert put_secrets.main(["--set", "EMAIL_TO_LAB"]) == 0
    ssm = boto3.client("ssm", region_name="us-east-2")
    params = {p["Name"]: p for p in ssm.get_parameters_by_path(Path="/litfetch", WithDecryption=True)["Parameters"]}
    assert set(params) == {"/litfetch/GROQ_API_KEY", "/litfetch/SLACK_WEBHOOK_URL", "/litfetch/EMAIL_TO_LAB"}
    assert all(p["Type"] == "SecureString" for p in params.values())
    assert params["/litfetch/EMAIL_TO_LAB"]["Value"] == "lab@umich.edu"
    out = capsys.readouterr().out
    assert "gsk-secret-value" not in out and "lab@umich.edu" not in out
    assert put_secrets.main([]) == 0                          # running again overwrites, no error
