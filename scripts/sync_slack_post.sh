#!/usr/bin/env bash
# Copy slack_post's latest subscribers/, seen/ and history/ into DynamoDB, so AWS knows which
# papers were already sent (no repeats) and has the current lab settings. Run it right before
# each step of the cut-over (docs/CUTOVER.md); safe to run again.
#
#   scripts/sync_slack_post.sh                   slack_post next to this repo
#   scripts/sync_slack_post.sh ~/path/to/slack_post
set -euo pipefail
cd "$(dirname "$0")/.."
src=${1:-../slack_post}
[ -d "$src/subscribers" ] || { echo "No slack_post repo at $src"; exit 1; }

echo "== pulling $src (the GitHub job commits seen/ and history/ there every Monday)"
git -C "$src" pull --ff-only

echo "== copying subscribers/, seen/, history/ (git-ignored here)"
for d in subscribers seen history; do
  mkdir -p "$d"
  rsync -a --exclude _template.yaml "$src/$d/" "$d/"
done

echo "== writing to DynamoDB (settings replaced by the files; seen and history merged)"
"${PYTHON:-python}" scripts/migrate_files.py --profile "${AWS_PROFILE_NAME:-litfetch}" --overwrite-prefs
