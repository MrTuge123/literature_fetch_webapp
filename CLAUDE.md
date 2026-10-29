# Literature Fetch

Follow docs/SPEC.md. Python 3.12. CDK app goes in infra/, frontend in web/, Lambda handlers in api/.

- AWS: profile `litfetch`, region `us-east-2` only (the project's AWS rules block other regions).
- Run `main.py` with `--dry-run` only: slack_post (until the M9 cut-over) or AWS (after it) sends the real digest. Cut-over steps: docs/CUTOVER.md.
- No CI (Tiger doesn't want GitHub Actions): deploy with `scripts/deploy.sh`; the weekly schedule and dry run are set in `infra/cdk.json`.
- Never commit personal data: seen/, history/ and real subscribers/*.yaml stay git-ignored.
- Explain every AWS resource you add and what it costs. Never put secrets in code.
- Work one milestone at a time; plan first and wait for approval. One commit per step.
- Tests: `pytest` (no network; LLM and HTTP are mocked).
- Commits are credited to Tiger only: no Co-Authored-By or Claude-Session trailers in commit messages or PR descriptions.
- Never run git push (Tiger pushes himself). Commit locally and tell him what is ready to push.
