# Pub/Sub example

A topic with three consumers' worth of wiring:

| Resource | Purpose |
|---|---|
| `jobs` | topic |
| `jobs-dlq` | dead-letter topic with 1-day retention |
| `jobs-worker` | pull subscription, filtered to `attributes.kind="work"`, retry + dead letter |
| `jobs-push` | push subscription delivering to the Cloud Run service |
| `push-receiver` | private-ish service (public ingress, IAM-protected) |
| `pubsub-push` | OIDC identity used for push and granted `run.invoker` |

```bash
python-tofu plan --config examples/gcp_pubsub/stack.py --workdir .tofu/pubsub
python-tofu apply --config examples/gcp_pubsub/stack.py --workdir .tofu/pubsub
```

Publish a message that matches the filter:

```python
import base64, json, os, urllib.request
from python_tofu import GcpProvider, GcpStack
from python_tofu.providers.gcp.live import access_token

project = os.environ["GOOGLE_PROJECT"]
token = access_token(GcpStack(provider=GcpProvider(project=project)))
body = {
    "messages": [
        {
            "data": base64.b64encode(b'{"job": 1}').decode(),
            "attributes": {"kind": "work"},
        }
    ]
}
request = urllib.request.Request(
    f"https://pubsub.googleapis.com/v1/projects/{project}/topics/jobs:publish",
    data=json.dumps(body).encode(),
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
)
print(urllib.request.urlopen(request).read().decode())
```

The push subscription delivers to the service's `uri`; the pull subscription
only receives messages whose `kind` attribute is `work`.

## Notes

- `push_service` resolves to `google_cloud_run_v2_service.<name>.uri`, so the
  subscription is created after the service and follows redeploys.
- Pushing needs three parts: `push_service_account` (the OIDC identity),
  `invoker_service_accounts` on the service, and a `serviceAccountTokenCreator`
  grant for the Pub/Sub service agent. The last two are emitted automatically —
  a missing token-creator grant shows up as a 403 "request was not authenticated"
  in Cloud Run logs while the subscription still publishes fine.
- `expiration_ttl=""` would silently expire after 31 days (the provider drops
  empty durations); the example sets an explicit ten-year TTL.
- Dead-letter topics receive a `roles/pubsub.publisher` grant for the Pub/Sub
  service agent automatically, via `data "google_project"`.
