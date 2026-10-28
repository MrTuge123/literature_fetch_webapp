# infra/ — AWS CDK app (Python)

```bash
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk synth                              # build the templates (and the worker zip) locally, no AWS calls
cdk diff   --profile litfetch          # what a deploy would change
cdk deploy --all --profile litfetch    # create / update every stack
```

| Stack | Contents |
| --- | --- |
| `LitFetchData` | DynamoDB table `LitFetch` (PK/SK, provisioned 10/10, TTL on `ttl`, retained on delete, deletion protection on) |
| `LitFetchBackend` | Lambda `litfetch-worker` (Python 3.12, arm64, 1 GB, 15 min, no async retries, logs 14 days), its IAM role (table + `/litfetch/*` parameters only) |

Region is always `us-east-2` (see `app.py`). The worker is packaged without Docker:
`litfetch_infra/bundling.py` runs `pip install --platform manylinux2014_aarch64` and copies
`digest/`, `api/` and `config.yaml` (never `.env`, `seen/`, `history/` or `subscribers/`).
