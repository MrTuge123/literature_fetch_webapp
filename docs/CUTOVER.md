# M9 cut-over: AWS takes over the weekly digest from slack_post

Two phases, so nothing reaches the lab twice or not at all:

| Phase | Weekly schedule | Dry run | Who really sends |
| --- | --- | --- | --- |
| Now (M1–M8) | off | on | slack_post (GitHub Actions) |
| **A. Shadow** (1–2 Mondays) | **on** | on | slack_post; AWS only logs what it would send |
| **B. Live** | on | **off** | **AWS**; slack_post's workflow disabled |

Both settings live in `infra/cdk.json` (`"schedule"`, `"dryRun"`), so every deploy keeps them.
There is no CI: you deploy with `scripts/deploy.sh`.

## One-time setup

```bash
# 1. Alarm email, outside the repo (every deploy needs it, or the alarm emails get unsubscribed)
cat ~/.cdk.json 2>/dev/null          # if this prints something, add the "context" part by hand instead
echo '{"context": {"alertEmail": "tigercui@umich.edu"}}' > ~/.cdk.json

# 2. Test packages for scripts/deploy.sh (in the Python you run scripts with)
python -m pip install -r requirements-dev.txt
```

## Phase A: shadow runs

```bash
git switch main && git merge m9-cutover && git push
scripts/sync_slack_post.sh          # latest settings, seen and history from slack_post -> DynamoDB
scripts/deploy.sh                   # schedule on, still dry run
```

Each Monday after 7:00 (New York), check what AWS would have sent:

```bash
aws logs tail /aws/lambda/litfetch-worker --since 6h --profile litfetch --region us-east-2 | less
```

- Every subscriber has a `DRY RUN: would post to ...` block, and no `Traceback`.
- The papers roughly match what slack_post posted to Slack that morning (small differences are
  normal: the two runs search a few minutes apart).
- No alarm email arrived, and the failed-jobs queue is empty:
  `aws sqs get-queue-attributes --queue-url $(aws sqs get-queue-url --queue-name litfetch-jobs-failed.fifo --query QueueUrl --output text --profile litfetch --region us-east-2) --attribute-names ApproximateNumberOfMessages --profile litfetch --region us-east-2`

## Before phase B

- [ ] **Email sender works:** with `"email": "smtp"` in `infra/cdk.json` (the default now), the
      Gmail login `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` must be in Parameter Store;
      "Send test" on the website should land in the inbox. (With `"email": "ses"` you'd need SES
      production access instead: SES console → Account dashboard → Request production access.)
- [ ] **Real recipients:** `python scripts/put_secrets.py --dry-run` lists the secret names the
      subscribers use; set each real value with `python scripts/put_secrets.py --profile litfetch --set EMAIL_TO_WANG_LAB` (etc.).

## Phase B: go live (any day after a Monday's slack_post run)

```bash
# 1. Stop slack_post: GitHub → slack_post repo → Actions → "Paper digest" → ⋯ → Disable workflow

# 2. Bring over what slack_post sent last, so AWS doesn't send it again
scripts/sync_slack_post.sh

# 3. Dry run off
git switch main && git merge m9-go-live && git push
scripts/deploy.sh
```

From the next Monday, AWS sends the real digests. Watch the first one with the `aws logs tail`
command above, and check Slack / email.

Then invite people from the website's Admin page. To stop the local dev server being allowed to
call the API: `cd infra && cdk deploy LitFetchApi -c localDev=off --profile litfetch`.

## Undo

- **Pause everything:** set `"schedule": "off"` in `infra/cdk.json`, then `scripts/deploy.sh`.
- **Back to slack_post:** set `"dryRun": "on"`, deploy, and re-enable the GitHub workflow. Papers
  AWS sent aren't in slack_post's `seen/`, so a few may be sent again once.

## After the cut-over

- Lab subscriptions without website accounts (wang_lab, ...): edit `subscribers/<id>.yaml` here,
  then `python scripts/migrate_files.py --profile litfetch --only <id> --overwrite-prefs`.
  Switch one off by renaming its file to `_<id>.yaml` and running the same command (it gets paused).
- Run `main.py` locally only with `--dry-run`: AWS is the real sender now, and the local
  `seen/` / `history/` files are no longer updated.
