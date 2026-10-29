import importlib.util
import os

import pytest

spec = importlib.util.spec_from_file_location("web_env", os.path.join("scripts", "web_env.py"))
web_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_env)


def test_env_text_maps_every_output():
    outputs = [{"OutputKey": "ApiUrl", "OutputValue": "https://x.execute-api.us-east-2.amazonaws.com"},
               {"OutputKey": "UserPoolId", "OutputValue": "us-east-2_abc"},
               {"OutputKey": "UserPoolClientId", "OutputValue": "client123"},
               {"OutputKey": "Other", "OutputValue": "ignored"}]
    assert web_env.env_text(outputs) == (
        "VITE_API_URL=https://x.execute-api.us-east-2.amazonaws.com\n"
        "VITE_USER_POOL_ID=us-east-2_abc\n"
        "VITE_USER_POOL_CLIENT_ID=client123\n")


def test_env_text_missing_output():
    with pytest.raises(SystemExit, match="UserPoolClientId"):
        web_env.env_text([{"OutputKey": "ApiUrl", "OutputValue": "u"},
                          {"OutputKey": "UserPoolId", "OutputValue": "p"}])
