# infra/ — AWS CDK app (Python)

```bash
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk synth                              # build the templates (and the Lambda zip) locally, no AWS calls
cdk diff   --profile litfetch          # what a deploy would change
cdk deploy --all --profile litfetch    # create / update every stack
```

Options for the backend stack:

| How | What |
| --- | --- |
| `LITFETCH_ALERT_EMAIL=you@umich.edu cdk deploy ...` | alarm emails go there (AWS emails a confirmation link first) |
| `cdk deploy -c schedule=on ...` | turn the Monday schedule on (M9 cut-over; it is off otherwise) |
| `cdk deploy -c webOrigins=https://site,http://localhost:5173 ...` | sites allowed to call the API from a browser (default: the local dev server) |

| Stack | Contents |
| --- | --- |
| `LitFetchData` | DynamoDB table `LitFetch` (PK/SK, provisioned 10/10, TTL on `ttl`, retained on delete, deletion protection on) |
| `LitFetchApi` | Cognito user pool `litfetch-users` (email login, invite-only via `litfetch-presignup`, group `admins`, Lite plan, retained), app client `litfetch-web`, HTTP API `litfetch-api` (JWT check on every route but `/health`, 10 req/s) → Lambda `litfetch-api-fn` (`api/http.py`) |
| `LitFetchBackend` | `litfetch-weekly` schedule (Mon 7:00 New York, off until M9) → `litfetch-dispatch` Lambda → `litfetch-jobs.fifo` queue (failed twice → `litfetch-jobs-failed.fifo`) → `litfetch-worker` Lambda (one user at a time). `litfetch-alerts` SNS topic + 3 alarms (failed job, dispatch error, posting failed). |

Region is always `us-east-2` (see `app.py`). Both Lambdas share one zip, built without Docker:
`litfetch_infra/bundling.py` runs `pip install --platform manylinux2014_aarch64` and copies
`digest/`, `api/` and `config.yaml` (never `.env`, `seen/`, `history/` or `subscribers/`).
