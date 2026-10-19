# infra/ — AWS CDK app (Python)

```bash
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk synth                              # print the CloudFormation template (no AWS calls)
cdk diff   --profile litfetch          # what a deploy would change
cdk deploy --profile litfetch          # create / update the stacks
```

| Stack | Contents |
| --- | --- |
| `LitFetchData` | DynamoDB table `LitFetch` (PK/SK, provisioned 10/10, TTL on `ttl`, retained on delete, deletion protection on) |

Region is always `us-east-2` (see `app.py`).
