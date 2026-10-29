#!/usr/bin/env bash
# Test, build and deploy to AWS in one go. There's no CI: run this yourself after merging to main.
#
#   scripts/deploy.sh                 every stack
#   scripts/deploy.sh LitFetchApi     one stack (plus the stacks it depends on)
#
# Needs: the test packages (pip install -r requirements-dev.txt), web/node_modules (npm install in
# web/), infra/.venv (see infra/README.md) and the alarm email in ~/.cdk.json (docs/CUTOVER.md).
set -euo pipefail
cd "$(dirname "$0")/.."

branch=$(git branch --show-current)
if [ "$branch" != main ] && [ -z "${ALLOW_BRANCH:-}" ]; then
  echo "You're on $branch, not main. Merge first, or run with ALLOW_BRANCH=1 to deploy this branch."
  exit 1
fi
git diff --quiet HEAD || echo "Note: you have uncommitted changes; they will be deployed too."

echo "== 1/3 tests"
"${PYTHON:-python}" -m pytest -q
(cd web && npm test --silent)

echo "== 2/3 website build"
(cd web && npm run build)

echo "== 3/3 deploy"
[ $# -eq 0 ] && set -- --all
cd infra
# shellcheck disable=SC1091
source .venv/bin/activate
cdk deploy "$@" --profile "${AWS_PROFILE_NAME:-litfetch}"
