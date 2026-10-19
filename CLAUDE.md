# Literature Fetch

Follow docs/SPEC.md. Python 3.12. CDK app goes in infra/, frontend in web/, Lambda handlers in api/.

- AWS: profile `litfetch`, region `us-east-2` only (the project's AWS rules block other regions).
- Until the M9 cut-over, run `main.py` with `--dry-run` only: the old slack_post repo still posts the real digest.
- Never commit personal data: seen/, history/ and real subscribers/*.yaml stay git-ignored.
- Explain every AWS resource you add and what it costs. Never put secrets in code.
- Work one milestone at a time; plan first and wait for approval. One commit per step.
- Tests: `pytest` (no network; LLM and HTTP are mocked).
