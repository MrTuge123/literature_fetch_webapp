"""Every secret (API keys, webhook URLs, SMTP login) is read through get(name), from one backend:

    EnvSecrets   .env / the environment, else the GitHub secrets the workflow passes in as JSON
                 (GITHUB_SECRETS_JSON, so new secrets need no workflow edit; GitHub upper-cases names)
    (M3)         AWS Parameter Store, plugged in with use(...) when running on Lambda

Tests plug in a dict-backed fake the same way."""
import json
import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class Secrets(Protocol):
    def get(self, name: str) -> str | None:
        """The secret's value, or None if it isn't set."""


class EnvSecrets:
    def get(self, name):
        if not name:
            return None
        if os.getenv(name):
            return os.getenv(name)
        try:
            secrets = json.loads(os.getenv("GITHUB_SECRETS_JSON") or "{}")
        except ValueError:
            secrets = {}
        return secrets.get(name.upper())


_backend = EnvSecrets()


def use(secrets):
    """Read every secret from `secrets` from now on (returns the previous backend)."""
    global _backend
    previous, _backend = _backend, secrets
    return previous


def get(name):
    return _backend.get(name) if name else None
