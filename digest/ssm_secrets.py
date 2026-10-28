"""Secrets from AWS Systems Manager Parameter Store, for code running on AWS (the worker Lambda).

Every secret is a SecureString named <prefix><NAME>, e.g. /litfetch/GROQ_API_KEY or
/litfetch/SLACK_WEBHOOK_URL: the same NAMEs as in .env (scripts/put_secrets.py copies them).
All of them are fetched in one paginated call the first time one is needed, then kept in
memory, so a warm Lambda doesn't call Parameter Store again. Plug in with digest.env.use().
"""
import os

import boto3

DEFAULT_PREFIX = "/litfetch/"
REGION = "us-east-2"


class ParameterStoreSecrets:
    def __init__(self, prefix=None, session=None, region=REGION):
        prefix = prefix or os.getenv("LITFETCH_SSM_PREFIX") or DEFAULT_PREFIX
        self.prefix = prefix if prefix.endswith("/") else prefix + "/"
        self._ssm = (session or boto3.Session()).client("ssm", region_name=region)
        self._values = None

    def _load(self):
        values, kw = {}, {"Path": self.prefix, "Recursive": False, "WithDecryption": True}
        while True:
            r = self._ssm.get_parameters_by_path(**kw)
            for p in r["Parameters"]:
                values[p["Name"][len(self.prefix):]] = p["Value"]
            if not r.get("NextToken"):
                return values
            kw["NextToken"] = r["NextToken"]

    def get(self, name):
        if not name:
            return None
        if self._values is None:
            self._values = self._load()
        return self._values.get(name)

    def names(self):
        """Which secrets exist (never their values)."""
        if self._values is None:
            self._values = self._load()
        return sorted(self._values)
