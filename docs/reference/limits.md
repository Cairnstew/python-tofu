# Limits and Throttling

`python-tofu` can enforce provider usage ceilings before it renders or calls
`tofu`. The mechanism is provider-agnostic and lives in
`python_tofu/core/limits.py`; each provider supplies:

- a `LimitPolicy` — the ceilings, their units and areas;
- a `measure_usage(stack)` function — the amounts derived from the stack (plus
  any explicit estimates);
- optionally a `live_measure_usage(stack)` function — amounts read from
  infrastructure that already exists.

Core owns the arithmetic, reporting and enforcement. A provider cannot invent a
second enforcement path.

## CLI

```bash
python-tofu render --config infra.py --limits error   # default: block
python-tofu plan   --config infra.py --limits warn    # print, continue
python-tofu apply  --config infra.py --limits off     # skip checks
python-tofu limits --config infra.py                  # show measured usage
python-tofu limits --config infra.py --usage live     # include existing infra
python-tofu limits --config infra.py --all --json     # full policy as JSON
python-tofu render --config infra.py --fail-on-unknown  # block on unknowns
```

`--limits` is available on `render`, `init`, `validate`, `plan`, `apply` and
`destroy`. `plan --limits off` skips the check for that invocation; the policy
stays defined.

The default mode comes from the provider policy (`error` for the GCP free-tier
policy). Type-level limits (`Limit.action = warn`) still only warn in `error`
mode.

`--usage` defaults to `stack` (offline, declared resources only). `--usage live`
asks the provider to measure existing infrastructure; live values win for the
keys they cover, and stack estimates survive for everything else.

## Unknown is not zero

A limit with no measurement is `unknown`, not `0%`. `Usage` records which keys
it observed; `LimitCheck.status` is `ok`, `exceeded` or `unknown`. Unknown
limits never count as a pass — they simply cannot prove a breach.

- Default output summarises them: `54 limits checked; 0 exceeded, 0 warning, 51 unknown`.
- `--fail-on-unknown` turns any unknown into an error (ignored by `--limits off`).
- `python-tofu limits --all` lists each one with a `?` marker.

## Model

```python
Limit(key, area, unit, amount, period=MONTH, action=ERROR, description="")
AggregateLimit(key, amount=1.0, areas=(), keys=(), action=WARN)
LimitPolicy(limits, aggregates=(), default_mode=ERROR)
Usage({"gcp.bigquery.query_tib": 0.4})   # these keys are observed
Usage()                                   # every key unknown
Throttler(policy).check(usage)            # LimitReport
```

- `Limit` covers one metric in one **area** (`storage`, `compute`,
  `bigquery`, …). This is the "per area under X" case.
- `AggregateLimit` sums the **normalised utilisation** of selected limits
  (`used / amount`). `amount=1.0` means "one full free tier combined". This is
  the "summarised under X" case. An aggregate stays `unknown` until every
  included limit is observed.
- `Usage.override(other)` takes `other`'s values for the keys it observed —
  that is how live inventory wins over declared estimates.
- `LimitReport.by_area()` groups results; `as_dict()` is JSON-ready.

## GCP free tier

The GCP policy (`python_tofu.providers.gcp.limits.GCP_FREE_TIER`) is the Google
Cloud always-free tier as published at
<https://cloud.google.com/free/docs/free-cloud-features> (read 2026-11-10).
Limits are **per billing account** unless noted; Firestore and Logging are per
project. They do not roll over.

| Key | Area | Free amount | Period |
|---|---|---|---|
| `gcp.storage.standard_gb` | storage | 5 GB (US regions only) | month |
| `gcp.storage.class_a_ops` | storage | 5,000 operations | month |
| `gcp.storage.class_b_ops` | storage | 50,000 operations | month |
| `gcp.storage.egress_gb` | storage | 100 GB (North America) | month |
| `gcp.compute.e2_micro_hours` | compute | 720 hours (one e2-micro; conservative 30-day month) | month |
| `gcp.compute.standard_pd_gb` | compute | 30 GB standard PD | month |
| `gcp.compute.egress_gb` | compute | 1 GB (North America) | month |
| `gcp.bigquery.query_tib` | bigquery | 1 TiB queried | month |
| `gcp.bigquery.storage_gib` | bigquery | 10 GiB stored | month |
| `gcp.cloud_run.requests` | cloud_run | 2,000,000 requests | month |
| `gcp.cloud_run.gb_seconds` | cloud_run | 360,000 GB-seconds | month |
| `gcp.cloud_run.vcpu_seconds` | cloud_run | 180,000 vCPU-seconds | month |
| `gcp.cloud_run.egress_gb` | cloud_run | 1 GB | month |
| `gcp.cloud_functions.invocations` | functions | 2,000,000 | month |
| `gcp.cloud_functions.gb_seconds` | functions | 400,000 GB-seconds | month |
| `gcp.cloud_functions.ghz_seconds` | functions | 200,000 GHz-seconds | month |
| `gcp.cloud_functions.egress_gb` | functions | 5 GB | month |
| `gcp.firestore.storage_gib` | firestore | 1 GiB (per project) | total |
| `gcp.firestore.reads_per_day` | firestore | 50,000 | day |
| `gcp.firestore.writes_per_day` | firestore | 20,000 | day |
| `gcp.firestore.deletes_per_day` | firestore | 20,000 | day |
| `gcp.firestore.egress_gib` | firestore | 10 GiB | month |
| `gcp.pubsub.messages_gib` | pubsub | 10 GiB | month |
| `gcp.gke.free_clusters` | gke | 1 cluster | month |
| `gcp.secret_manager.active_versions` | secret_manager | 6 | month |
| `gcp.secret_manager.access_ops` | secret_manager | 10,000 | month |
| `gcp.secret_manager.rotation_notifications` | secret_manager | 3 | month |
| `gcp.artifact_registry.storage_gb` | artifact_registry | 0.5 GB | month |
| `gcp.cloud_build.minutes` | cloud_build | 2,500 build-minutes | month |
| `gcp.logging.log_gib` | logging | 50 GiB (per project) | month |
| `gcp.monitoring.timeseries_read` | logging | 1,000,000 time series | month |
| `gcp.kms.active_key_versions` | kms | 100 (Autokey) | month |
| `gcp.kms.crypto_ops` | kms | 10,000 | month |
| `gcp.workflows.internal_steps` | workflows | 5,000 | month |
| `gcp.workflows.external_calls` | workflows | 2,000 | month |
| `gcp.application_integration.executions` | integration | 400 | month |
| `gcp.application_integration.data_gib` | integration | 20 GiB | month |
| `gcp.datastream.cdc_gib` | datastream | 100 GiB | month |
| `gcp.source_repos.users` | source_repos | 5 | month |
| `gcp.source_repos.storage_gb` | source_repos | 50 GB | month |
| `gcp.source_repos.egress_gb` | source_repos | 50 GB | month |
| `gcp.cloud_shell.disk_gb` | cloud_shell | 5 GB | total |
| `gcp.app_engine.f1_hours_per_day` | app_engine | 28 h | day |
| `gcp.app_engine.b1_hours_per_day` | app_engine | 9 h | day |
| `gcp.app_engine.egress_gb_per_day` | app_engine | 1 GB | day |
| `gcp.natural_language.units` | ai_api | 5,000 units | month |
| `gcp.vision.units` | ai_api | 1,000 units | month |
| `gcp.video_intelligence.units` | ai_api | 1,000 units | month |
| `gcp.speech.minutes` | ai_api | 60 minutes | month |
| `gcp.recaptcha.assessments` | ai_api | 10,000 | month |
| `gcp.web_risk.calls` | ai_api | 100,000 | month |
| `gcp.workload_manager.evaluations` | misc | 5,000 | month |
| `gcp.cloud_deploy.active_pipelines` | misc | 1 | total |

Aggregate `gcp.free_tier.total` sums the normalised usage of every limit; it
warns at more than one full free tier by default so it does not block on its
own.

### Measured vs estimated vs live

`measure_usage` (stack mode, default) derives what the stack declares:

- `StorageBucket.estimated_size_gb` for buckets in `us-east1`, `us-west1` or
  `us-central1` (the only free-tier storage regions).

Everything else (BigQuery bytes, Cloud Run requests, …) comes from
`GcpStack.usage_estimates`:

```python
stack = GcpStack(
    provider=GcpProvider(project="my-project"),
    buckets=[
        StorageBucket(
            project="my-project",
            name="my-project-artifacts",
            location="us-central1",
            estimated_size_gb=4.5,
        )
    ],
    usage_estimates={
        "gcp.bigquery.query_tib": 0.2,
        "gcp.bigquery.storage_gib": 3,
    },
)
```

`live_measure_usage` (`--usage live`) reads **Cloud Asset Inventory** — free of
charge and read-only — so manually created and pre-existing resources count
too. It currently maps:

| Inventory | Limit key | Rule |
|---|---|---|
| `compute.googleapis.com/Instance` | `gcp.compute.e2_micro_hours` | non-preemptible, non-Spot `e2-micro` in `us-central1`/`us-east1`/`us-west1`, counted as 720 h |
| `compute.googleapis.com/Disk` | `gcp.compute.standard_pd_gb` | `pd-standard` size in those regions |
| `container.googleapis.com/Cluster` | `gcp.gke.free_clusters` | Autopilot or zonal Standard |

Inventory metadata has **no byte sizes**, so `gcp.storage.standard_gb`,
BigQuery storage/query, egress and request counts stay `unknown` in live mode
unless `usage_estimates` covers them. Storage bytes need Cloud Monitoring (or
Billing export); they are never assumed to be zero.

```bash
$ python-tofu limits --config infra.py --usage live --all
GCP limits: 54 limits checked; 0 exceeded, 0 warning, 50 unknown
  gcp.storage.standard_gb: 1/5 GB (20.0%)
  gcp.compute.e2_micro_hours: 0/720 hours (0.0%)
? gcp.bigquery.query_tib: unknown/1 TiB
```

Live measurement authenticates with the provider's `credentials` path, then
`GOOGLE_APPLICATION_CREDENTIALS`, then Application Default Credentials. It needs
`cloudasset.assets.listResource` (e.g. `roles/cloudasset.viewer`) and the Cloud
Asset Inventory API enabled; the API itself is free of charge.

These are **checks, not metering**. Live inventory sees resource metadata, not
usage; pair it with Cloud Billing budgets for a hard financial guardrail.

## Adding a provider policy

```python
from python_tofu.core.limits import Limit, LimitPolicy, Usage

MY_LIMITS = LimitPolicy(limits=(Limit("acme.vcpu_hours", "compute", "hours", 100),))

def measure_usage(stack: MyStack) -> Usage:
    return Usage({"acme.vcpu_hours": stack.vcpu_hours})

def live_measure_usage(stack: MyStack) -> Usage:
    ...  # read the provider's API; return only the keys you actually measured

MY_PROVIDER = Provider(
    ...,
    limit_policy=MY_LIMITS,
    measure_usage=measure_usage,
    live_measure_usage=live_measure_usage,
)
```

Core's `Throttler` and CLI enforcement then work unchanged; see
`STRUCTURE.md#adding-a-provider`.
