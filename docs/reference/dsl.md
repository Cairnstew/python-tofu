# DSL Reference

The GCP DSL lives in `src/python_tofu/providers/gcp/models.py` and
`src/python_tofu/providers/gcp/stack.py`; `python_tofu.models` re-exports it for
backwards compatibility. Every model is a frozen Pydantic model with
`extra="forbid"`; unknown fields and invalid GCP identifiers fail at import
time. Provider-agnostic primitives (`TofuModel`, `BaseStack`) live in
`python_tofu.core.models`.

## Credentials

The Google provider uses Application Default Credentials by default. The
repository's `.envrc` exports `GOOGLE_APPLICATION_CREDENTIALS` from the agenix
`gcloud-auth` service-account key when it is readable. You can also set
`GcpProvider.credentials` to an explicit key path; prefer the environment/agenix
route so credentials never enter the Python config.

## `GcpStack`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `GcpProvider` | required | Google provider settings |
| `projects` | `list[GcpProject]` | `[]` | Projects to create |
| `apis` | `list[ProjectApi]` | `[]` | APIs to enable |
| `billing_budgets` | `list[BillingBudget]` | `[]` | Billing-account budget alerts (see below) |
| `service_accounts` | `list[ServiceAccount]` | `[]` | Service accounts and role bindings |
| `buckets` | `list[StorageBucket]` | `[]` | GCS buckets |
| `bucket_objects` | `list[BucketObject]` | `[]` | Objects (content) inside buckets |
| `iam_members` | `list[ProjectIamMember]` | `[]` | Standalone project IAM bindings |
| `cloud_run_services` | `list[CloudRunService]` | `[]` | Container image services |
| `cloud_run_functions` | `list[CloudRunFunction]` | `[]` | 2nd-gen functions from a source zip |
| `cloud_run_jobs` | `list[CloudRunJob]` | `[]` | Batch jobs (runners) |
| `cloud_run_worker_pools` | `list[CloudRunWorkerPool]` | `[]` | Pull-based background workers |
| `artifact_registry_repositories` | `list[ArtifactRegistryRepository]` | `[]` | Docker image repositories |
| `pubsub_topics` | `list[PubSubTopic]` | `[]` | Pub/Sub topics |
| `pubsub_subscriptions` | `list[PubSubSubscription]` | `[]` | Pull and push subscriptions |
| `name` | `str \| None` | `None` | Stack name for the default workdir and GCS prefix (CLI default: config stem) |
| `backend` | `BackendConfig \| None` | `None` | State backend (omit for local default) |
| `outputs` | `list[Output]` | `[]` | Values exposed after apply (see [`Output` and `ref`](#output-and-ref)) |
| `external_projects` | `list[str]` | `[]` | Existing projects resources may reference |
| `external_buckets` | `list[str]` | `[]` | Existing buckets objects may target |
| `external_topics` | `list[str]` | `[]` | Existing Pub/Sub topics subscriptions may target |
| `required_version` | `str` | `">= 1.6.0"` | OpenTofu version constraint |
| `google_provider_version` | `str` | `"~> 6.0"` | Google provider constraint |
| `usage_estimates` | `dict[str, float]` | `{}` | Monthly usage per limit key for free-tier checks (see [limits](limits.md)) |
| `prune` | `PruneConfig` | off | Delete live resources the stack does not declare (see below) |
| `limits_mode` | `"error" \| "warn" \| "off" \| None` | `None` | Stack-level limit enforcement, used when neither `--limits` nor the policy chooses |
| `profile` | `"default" \| "preview"` | `"default"` | Named default bundle (see [stack profiles](#stack-profiles)) |
| `extra_files` | `dict[str, str]` | `{}` | Raw `.tf` files for resources the DSL does not model (see below) |

Cross-resource references are validated: every `project` must be declared in
`projects`, equal to `provider.project`, or listed in `external_projects`.

## `PruneConfig`

Opt-in authoritative mode. It is off unless `enabled=True`, and it never runs
implicitly: `plan --prune` only previews, `apply --prune` prunes after a
successful apply, and `python-tofu prune` is a dry run unless `--apply` is
passed.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Turn pruning on for the selected sections |
| `sections` | `tuple[str, ...]` | `("all",)` | `all`, or any of `buckets`, `subscriptions`, `topics`, `service_accounts`, `apis` |

```python
from python_tofu import GcpStack, PruneConfig

stack = GcpStack(
    provider=provider,
    prune=PruneConfig(enabled=True, sections=("buckets", "apis")),
    ...
)
```

Discovery reads the service APIs (Storage for buckets, IAM for service accounts,
Service Usage for enabled APIs) and compares them with the declared stack. The
service APIs are used instead of Cloud Asset Inventory because CAI is eventually
consistent: a just-deleted bucket can linger and make the next prune try to
import a 404.
`external_buckets` are treated as declared (they are never pruned). Deletion is
performed by adopting each leftover into a scratch OpenTofu module and running
`tofu destroy`, so the provider's own delete logic runs and the real state
backend is never touched.

Supported sections and safety rules:

- `buckets` — `google_storage_bucket`; rendered with `force_destroy=True`, so a
  pruned bucket deletes its objects.
- `subscriptions` — `google_pubsub_subscription`; pruned before topics because a
  topic cannot be deleted while subscriptions reference it.
- `topics` — `google_pubsub_topic`.
- `service_accounts` — `google_service_account`; Google-managed accounts
  (compute/appspot/agent defaults) are skipped.
- `apis` — `google_project_service`; essential APIs (Cloud Asset Inventory,
  IAM, Cloud Resource Manager, Service Usage, Storage, logging, monitoring,
  billing budgets) are never disabled.

Bucket objects cannot be imported by the Google provider, and project IAM
bindings are excluded on purpose: an authoritative IAM sweep can remove human
access. Both stay outside the supported section list.

## Stack profiles

`profile` is a named bundle of defaults, resolved when the stack is built and
then rendered explicitly. `default` changes nothing.

| Field | `default` | `preview` |
|-------|-----------|-----------|
| `deletion_protection` on services, jobs and worker pools | `true` | `false` |
| `prune.enabled` | `false` | `true` |
| `backend.kind` | as declared (local when omitted) | `local` |
| `limits_mode` | policy default (`error`) | `warn` |
| `provider.default_labels` | unchanged | `ephemeral=true` added |

Rules:

- explicit values always win: a resource with `deletion_protection=True` stays
  protected, and an explicit `prune`, `limits_mode`, `backend.kind` or label set
  is kept;
- a profile only flips booleans and labels. Names, references and import IDs are
  never rewritten;
- Cloud Run functions are excluded: `google_cloudfunctions2_function` has no
  `deletion_protection` attribute;
- the resolved values are rendered, so `preview` shows up as
  `deletion_protection = false` and the `ephemeral` label rather than being
  hidden behaviour.

```python
stack = GcpStack(provider=provider, profile="preview", cloud_run_services=[...])
```

## `BillingBudget`

Renders `google_billing_budget`: an alert-only guardrail on a billing account.
Budgets never disable billing by themselves; this model only sets thresholds and
notification settings. Notifications go to the billing administrators by
default.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `billing_account` | `str` | required | Account id, with or without `billingAccounts/` |
| `display_name` | `str` | required | Budget name; also names the HCL resource |
| `amount` | `float` | required | Budget in `currency_code` units |
| `currency_code` | `str` | `"USD"` | ISO currency code |
| `thresholds` | `tuple[float, ...]` | `(0.5, 0.9, 1.0)` | Fractions of the budget (`0 < t <= 1`) |
| `spend_basis` | `"CURRENT_SPEND" \| "FORECASTED_SPEND"` | `"CURRENT_SPEND"` | What each threshold measures |
| `project_filter` | `str \| None` | `None` | Project number (or `projects/<number>`) to narrow the budget to |
| `pubsub_topic` | `str \| None` | `None` | Topic notified on updates |
| `notification_channels` | `tuple[str, ...]` | `()` | Monitoring channels (resource names) |
| `disable_default_recipients` | `bool` | `false` | Stop the default billing-admin emails |

```python
from python_tofu import BillingBudget

budget = BillingBudget(
    billing_account="01ABCD-EFGH23-456789",
    display_name="python-tofu guardrail",
    amount=5,
    thresholds=[0.5, 0.9, 1.0],
    project_filter="123456789",
)
```

## API enablement

`google_project_service` resources are derived from the declared resources, and
every consumer is ordered after them with `depends_on`, so a single apply works
into a project whose APIs are still disabled:

```python
stack = GcpStack(
    provider=GcpProvider(project="my-project"),
    pubsub_topics=[PubSubTopic(project="my-project", name="jobs")],
)
# renders google_project_service for pubsub + service usage,
# and the topic depends_on them
```

| Resource | APIs enabled |
|---|---|
| bucket / object | `storage` |
| service account, IAM binding | `iam` (+ `cloudresourcemanager` for role bindings) |
| Artifact Registry repo | `artifactregistry` |
| Cloud Run service / job / worker pool | `run` (+ `iam` when an invoker is granted) |
| Cloud Run function | `cloudfunctions`, `cloudbuild`, `run`, `eventarc`, `artifactregistry`, `storage` |
| Pub/Sub topic / subscription | `pubsub` (+ `iam`/`run` for dead letters and push) |

Only projects the stack owns are touched: the provider project and anything in
`projects`. Resources pointing at `external_projects` never enable APIs there.
`serviceusage` is always added alongside any derived API.

Turn it off when enablement belongs to another pipeline:

```python
GcpProvider(project="my-project", auto_enable_apis=False)
```

`ServiceCatalog.enable(...)` remains available when you want to pin the list
explicitly (see `examples/gcp_apis`); it resolves names against Service Usage but
only *declares* them — nothing is enabled until apply.

## `GcpProvider`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `project` | `str` | required | Default project |
| `region` | `str` | `"us-central1"` | Default region |
| `zone` | `str \| None` | `None` | Default zone |
| `credentials` | `str \| None` | `None` | Path to a service-account key |
| `impersonate_service_account` | `str \| None` | `None` | Impersonation target |
| `default_labels` | `dict[str, str]` | `{}` | Provider-wide labels |
| `auto_enable_apis` | `bool` | `true` | Enable and order the APIs declared resources need |

## `GcpProject`

`project_id` must be 6–30 characters, start with a letter, contain only lowercase
letters, digits and hyphens, and not end with a hyphen. `org_id` and `folder_id`
are mutually exclusive.

## `ProjectApi`

Enables a `google_project_service`. `service` is a full API name such as
`storage.googleapis.com`.

To declare APIs by short name and validate them against the project, use the
Service Usage catalog in `python_tofu.providers.gcp.services`:

```python
from python_tofu import GcpProvider, GcpStack
from python_tofu.providers.gcp.services import ServiceCatalog

PROJECT = "my-project"
provider = GcpProvider(project=PROJECT)
catalog = ServiceCatalog(PROJECT, credentials=provider.credentials)

stack = GcpStack(
    provider=provider,
    apis=catalog.enable("compute", "run", "storage"),   # -> list[ProjectApi]
)
```

`ServiceCatalog` fetches on demand and caches per process:

| Method | Description |
|--------|-------------|
| `enabled(filter=None)` | Services already enabled (`state:ENABLED`, unrestricted) |
| `available(filter=None)` | Services that can still be enabled (`state:DISABLED`) |
| `all(filter=None)` | Every service known to the project |
| `lookup(name)` | One service via `services.get`, or `None` (no listing) |
| `resolve(name)` | Exactly one service; raises `UnknownService`/`AmbiguousService` |
| `enable(*names, disable_on_destroy=False)` | Resolve names and return deduplicated `ProjectApi` entries |
| `refresh()` | Drop the cache and re-read on the next call |

`enable_apis(project, *names)` is a one-shot wrapper. `canonical_service("run")`
returns `run.googleapis.com`.

Service Usage throttles the available/disabled listing (often one request per
minute); `services.get`, the enabled listing and `resolve()` of a canonical
name are not affected. A 429 surfaces as `ServiceUsageError` with a hint.

## `ServiceAccount`

`account_id` follows the same 6–30 character rules as project IDs. Each entry in
`roles` becomes a `google_project_iam_member` bound to the service account's
generated email.

## `StorageBucket`

Bucket names are validated against GCS rules. `versioning=True` emits a nested
`versioning { enabled = true }` block. `public_access_prevention` defaults to
`"enforced"`. `estimated_size_gb` is used only by the free-tier check and is
never rendered as HCL.

## `BucketObject`

A `google_storage_bucket_object`. Exactly one content source is required:

```python
from python_tofu import BucketObject

objects = [
    # inline text (any format — JSON, YAML, HTML, CSV, ...)
    BucketObject(
        bucket="my-project-artifacts",
        name="config/release.json",
        content='{"release": "v1"}',
        cache_control="no-store",
    ),
    # raw bytes; written to <workdir>/.objects/ and referenced by `source`
    BucketObject(bucket="my-project-artifacts", name="blob.bin", content=b"\x00\x01"),
    # a local file
    BucketObject(bucket="my-project-artifacts", name="dist/app.js", source="dist/app.js"),
    # an HTTP(S) URL fetched at plan/apply time
    BucketObject(
        bucket="my-project-artifacts",
        name="upstream/index.html",
        source_url="https://example.com/index.html",
    ),
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `bucket` | `str` | required | Declared bucket name or one in `external_buckets` |
| `name` | `str` | required | Object key; no leading slash |
| `content` | `str \| bytes \| None` | `None` | Inline payload |
| `source` | `str \| None` | `None` | Local file path (resolved to absolute at render) |
| `source_url` | `str \| None` | `None` | HTTP(S) URL; adds the `hashicorp/http` provider |
| `content_type` | `str \| None` | guessed from `name` | e.g. `.json` → `application/json` |
| `content_encoding` | `str \| None` | `None` | e.g. `gzip` |
| `content_language` | `str \| None` | `None` | BCP-47 language tag |
| `cache_control` | `str \| None` | `None` | `Cache-Control` metadata |
| `metadata` | `dict[str, str]` | `{}` | Custom object metadata |
| `storage_class` | `StorageClass \| None` | `None` | Object-level storage class |

Terraform compares the declared `content`/file hash with state, so applying an
unchanged object is a no-op — it is not uploaded again. Set
`StorageBucket.versioning=True` when previous generations must be retained.

Limits of the representation:

- HCL cannot carry arbitrary bytes, so `content=bytes` is materialised as a file
  under `<workdir>/.objects/` and referenced with `source`.
- `source_url` uses `data "http"`, whose body is text; for binary URLs download
  the file first and use `source`.
- Relative `source` paths are resolved against the process working directory at
  render time, not the config file's directory.
- Objects that target a declared bucket are rendered with
  `bucket = google_storage_bucket.bucket_<name>.name`, which gives OpenTofu the
  dependency so the object waits for the bucket. Buckets listed in
  `external_buckets` are rendered as string literals (they must already exist).

## `ProjectIamMember`

A standalone `google_project_iam_member` binding. `member` must include its
principal prefix, e.g. `user:alice@example.com` or
`serviceAccount:sa@project.iam.gserviceaccount.com`.

## `BackendConfig` (`GcpBackendConfig`)

The GCP backend model is also exported as `GcpBackendConfig`; `BackendConfig`
remains the compatibility alias.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `kind` | `"local" \| "gcs"` | `"gcs"` | Backend type |
| `bucket` | `str \| None` | `None` | GCS bucket (required for `gcs`) |
| `prefix` | `str \| None` | `python-tofu/<stack-name>` | GCS object prefix |
| `path` | `str \| None` | `None` | Local state path (required for `local`) |

The default prefix falls back to `python-tofu/state` only when the stack has no
name at all (direct API use); the CLI always names the stack. An explicit
`prefix` is never rewritten.

## Raw HCL escape hatch (`extra_files`)

The typed DSL only renders the resources it models. For anything else, add flat
`.tf`/`.tf.json` files through `extra_files`; they are written verbatim into the
workdir beside `main.tf`:

```python
stack = GcpStack(
    provider=provider,
    extra_files={
        "biglake.tf": """
resource "google_biglake_catalog" "default" {
  name     = "lake_catalog"
  location = "US"
}
""",
    },
)
```

Rules:

- names must be flat and end in `.tf` or `.tf.json`; paths and other suffixes
  are rejected;
- `versions.tf`, `providers.tf`, `main.tf` and `.gitignore` are managed and
  cannot be overridden (`RenderError`);
- extra files are not validated by the Python models — run
  `python-tofu validate` (or `tofu validate`) after rendering;
- `RenderResult.resources` counts typed resources only.

See [`examples/gcp_biglake/`](../../examples/gcp_biglake/) for a complete
BigLake catalog/database/table wired alongside typed buckets.

## `Output` and `ref`

`GcpStack.outputs` declares `output` blocks. They render after every resource in
`main.tf`, so `python-tofu output` can read results — a service URL, a bucket
name, a topic ID — without opening the console.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Output name; a unique HCL identifier |
| `value` | `Any` | required | A literal value or a `ref(...)` expression |
| `description` | `str \| None` | `None` | Single-line description |
| `sensitive` | `bool` | `false` | Mark the output as sensitive in `tofu output` |

```python
from python_tofu import GcpProvider, GcpStack, Output, ref

stack = GcpStack(
    provider=GcpProvider(project="my-project"),
    cloud_run_services=[...],
    outputs=[
        Output("service_url", ref("google_cloud_run_v2_service.run_api.uri")),
        Output("bucket", ref("google_storage_bucket.bucket_assets.name")),
        Output("topic_id", ref("google_pubsub_topic.topic_jobs.id")),
    ],
)
```

`ref("...")` wraps a bare HCL expression verbatim (`core.hcl.Raw`); every other
value renders as a literal. Resource addresses are not validated — a typo
surfaces in `tofu plan`, exactly as it would in hand-written HCL. Duplicate
output names and names that are not HCL identifiers fail when the stack is
built.

Read them back with `python-tofu output`:

```bash
python-tofu output --workdir .tofu/pubsub --no-json
```

## Cloud Run

### `CloudRunService`

Renders `google_cloud_run_v2_service`. Defaults are hardened: **internal-only
ingress**, **no unauthenticated invoker**, deletion protection on, scale-to-zero
with a bounded maximum, and 1 vCPU / 512 MiB.

```python
from python_tofu import CloudRunService

services = [
    CloudRunService(
        project="my-project",
        name="api",
        image="us-docker.pkg.dev/my-project/repo/api@sha256:...",
        service_account="api-runtime",          # declared ServiceAccount account_id
        env={"LOG_LEVEL": "info"},
        secret_env={"TOKEN": SecretEnv(secret="api-token", version="3")},
    )
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | `str` | required | Image URI; use a digest for reproducibility |
| `location` | `str \| None` | provider region | Cloud Run region |
| `allow_unauthenticated` | `bool` | `false` | Adds `allUsers` / `roles/run.invoker` when true |
| `ingress` | `all \| internal \| internal-and-load-balancer` | `internal` | Traffic ingress |
| `deletion_protection` | `bool` | `true` | Blocks destroy until set false |
| `min_instances` / `max_instances` | `int` | `0` / `10` | Scale-to-zero, capped |
| `cpu` / `memory` | `str` | `"1"` / `"512Mi"` | Container limits |
| `concurrency` | `int \| None` | Cloud Run default | Max concurrent requests per instance |
| `timeout` | `str \| None` | Cloud Run default | e.g. `"300s"` |
| `port` | `int` | `8080` | Container port |
| `service_account` | `str \| None` | provider default | Runtime email or declared account_id |
| `env` / `secret_env` | `dict` | `{}` | Literal and Secret Manager env vars |
| `vpc_connector` / `vpc_egress` | `str \| None` | `None` | Serverless VPC connector and egress |
| `volumes` | `list[Volume]` | `[]` | Mounts (GCS, NFS, emptyDir, Cloud SQL, Secret) |
| `startup_probe` / `liveness_probe` | `Probe \| None` | `None` | Health probes |

OpenTofu does not build images. Build and push in CI, then reference the digest
(or use the `google_cloudbuild_trigger` pattern).

### `CloudRunFunction`

Renders `google_cloudfunctions2_function`. The source is a zip uploaded through
a `BucketObject`; the renderer references the object's bucket/name/generation so
the function waits for the upload and rebuilds when the zip changes. Defaults
are the same hardened shape: internal ingress, private invoker, scale-to-zero,
bounded maximum, 256 MB.

```python
from python_tofu import BucketObject, CloudRunFunction, StorageBucket

buckets = [StorageBucket(project="my-project", name="functions-src", location="US")]
bucket_objects = [
    BucketObject(
        bucket="functions-src",
        name="hello.zip",
        content=zip_dir("hello"),   # deterministic bytes
    )
]
functions = [
    CloudRunFunction(
        project="my-project",
        name="hello",
        runtime="python312",
        entry_point="hello_http",
        source_bucket="functions-src",
        source_object="hello.zip",
    )
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `runtime` / `entry_point` | `str` | required | e.g. `python312` / `hello_http` |
| `source_bucket` / `source_object` | `str` | required | Zip object; must be declared or in `external_buckets` |
| `source_generation` | `str \| None` | object generation | Pin a specific zip generation |
| `allow_unauthenticated` | `bool` | `false` | Adds `allUsers` / `roles/cloudfunctions.invoker` |
| `ingress` | `all \| internal \| internal-and-gclb` | `internal` | Ingress settings |
| `service_account` | `str \| None` | provider default | Runtime service account |
| `build_service_account` | `str \| None` | Cloud Build default | Build service account |
| `available_memory` / `available_cpu` | `str \| None` | `256M` / calculated | Function resources |
| `timeout_seconds` | `int` | `60` | 1–540 seconds |
| `min_instances` / `max_instances` | `int` | `0` / `10` | Scale-to-zero, capped |
| `env` / `secret_env` | `dict` | `{}` | Literal and Secret Manager env vars |

`SecretEnv(secret="name", version="latest")` is shared by both models. For
2nd-gen functions the renderer adds the required `project_id` automatically.

> `deletion_protection=True` means `python-tofu destroy` fails until the service
> is updated with `deletion_protection=False`. This is intentional.

### `CloudRunJob`

Renders `google_cloud_run_v2_job`: a batch runner that starts tasks, exits, and
scales to zero. Defaults cap retries, CPU/memory and deletion.

```python
from python_tofu import CloudRunJob

jobs = [
    CloudRunJob(
        project="my-project",
        name="nightly-runner",
        image="us-central1-docker.pkg.dev/my-project/repo/app@sha256:...",
        command=["python", "-m", "job"],
        args=["--mode", "nightly"],
        env={"MODE": "batch"},
        task_count=1,
        parallelism=1,
        max_retries=0,
    )
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | `str` | required | Container image |
| `command` / `args` | `list[str]` | `[]` | Override image entrypoint/CMD |
| `task_count` / `parallelism` | `int` | `1` / `1` | Tasks and concurrent tasks |
| `max_retries` | `int` | `1` | Per-task retries (0–10) |
| `timeout` | `str` | `"600s"` | Per-task timeout |
| `cpu` / `memory` | `str` | `"1"` / `"512Mi"` | Task resources |
| `service_account` | `str \| None` | provider default | Task identity |
| `deletion_protection` | `bool` | `true` | Blocks destroy until false |
| `env` / `secret_env` | `dict` | `{}` | Environment variables |

Jobs are executed out of band (`jobs:run` or the console); declaring the job in
Tofu does not run it.

### `ArtifactRegistryRepository`

Renders `google_artifact_registry_repository` for custom container images.

```python
from python_tofu import ArtifactRegistryRepository

repositories = [
    ArtifactRegistryRepository(
        project="my-project",
        repository_id="apps",
        location="us-central1",
    )
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `repository_id` | `str` | required | 2–63 chars, lowercase, starts with a letter |
| `location` | `str \| None` | provider region | Repository location |
| `format` | `"DOCKER"` | `DOCKER` | Image format |
| `description` / `labels` | `str` / `dict` | none / `{}` | Metadata |

Push with Docker using `oauth2accesstoken` and an access token:

```bash
echo "$TOKEN" | docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev
docker tag app:local us-central1-docker.pkg.dev/PROJECT/apps/app:tag
docker push us-central1-docker.pkg.dev/PROJECT/apps/app:tag
```

### `CloudRunWorkerPool`

Renders `google_cloud_run_v2_worker_pool`: pull-based background workers. There
is no ingress, no URL and no request traffic — the container starts with the
instance and runs until it is replaced or stopped. Defaults are one 1 vCPU /
512 MiB instance with manual scaling and deletion protection.

```python
from python_tofu import CloudRunWorkerPool, EmptyDirVolume, Volume

worker_pools = [
    CloudRunWorkerPool(
        project="my-project",
        name="queue-worker",
        image="us-central1-docker.pkg.dev/my-project/repo/worker@sha256:...",
        command=["python", "-m", "worker"],
        env={"QUEUE": "jobs"},
        manual_instance_count=1,
        volumes=[
            Volume(name="scratch", mount_path="/tmp/scratch", empty_dir=EmptyDirVolume())
        ],
    )
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | `str` | required | Container image |
| `command` / `args` | `list[str]` | `[]` | Override image entrypoint/CMD |
| `scaling_mode` | `manual \| automatic` | `manual` | Worker pool scaling model |
| `manual_instance_count` | `int` | `1` | Instances when `scaling_mode="manual"` |
| `min_instances` / `max_instances` | `int` | `0` / `1` | Bounds when `scaling_mode="automatic"` |
| `cpu` / `memory` | `str` | `"1"` / `"512Mi"` | Instance resources |
| `service_account` | `str \| None` | provider default | Worker identity |
| `env` / `secret_env` | `dict` | `{}` | Literal and Secret Manager env vars |
| `volumes` | `list[Volume]` | `[]` | Mounts available to the container |
| `vpc_connector` / `vpc_egress` | `str \| None` | `None` | VPC connector and egress |
| `deletion_protection` | `bool` | `true` | Blocks destroy until set false |
| `launch_stage` | `GA \| BETA \| ALPHA \| None` | `None` | Set `BETA` while the feature is in preview |

Worker pools bill per instance-second with a one-minute minimum, so an idle pool
costs money. Worker pools have a separate free tier (384,204 vCPU-seconds and
728,744 GiB-seconds per month in `us-central1`), but a pool left running all
month at 1 vCPU / 512 MiB exceeds it — set `manual_instance_count=0` to park a
pool between uses.

### `Volume` and probes

`Volume` binds one source to one mount path; the renderer emits the matching
`volumes` and `volume_mounts` blocks so they cannot drift apart.

```python
from python_tofu import (
    CloudSqlVolume,
    EmptyDirVolume,
    GcsVolume,
    NfsVolume,
    SecretVolume,
    Volume,
)

volumes = [
    Volume(name="scratch", mount_path="/tmp/scratch", empty_dir=EmptyDirVolume(size_limit="512Mi")),
    Volume(name="assets", mount_path="/mnt/assets", gcs=GcsVolume(bucket="my-assets")),
    Volume(name="share", mount_path="/mnt/share", nfs=NfsVolume(server="10.0.0.2", path="/exports")),
    Volume(name="db", mount_path="/cloudsql", cloud_sql=CloudSqlVolume(instances=["p:us-central1:pg"])),
    Volume(name="creds", mount_path="/etc/creds", secret=SecretVolume(secret="db-password")),
]
```

| Source | Fields | Notes |
|--------|--------|-------|
| `gcs` | `bucket`, `read_only` (true), `mount_options` | GCS FUSE; gen2 execution only |
| `nfs` | `server`, `path`, `read_only` (true) | Requires a VPC connection |
| `empty_dir` | `medium` (`MEMORY`), `size_limit` | Ephemeral scratch |
| `cloud_sql` | `instances` | Must mount at `/cloudsql` |
| `secret` | `secret`, `default_mode`, `items` | Files from Secret Manager |

Probes use one check kind each (`http_get`, `tcp_socket`, or `grpc`) plus
timing fields:

```python
from python_tofu import HttpProbe, Probe, TcpProbe

service = CloudRunService(
    project="my-project",
    name="api",
    image="...",
    startup_probe=Probe(http_get=HttpProbe(path="/health"), period_seconds=5),
    liveness_probe=Probe(tcp_socket=TcpProbe(port=8080), period_seconds=30),
)
```

`timeout_seconds` must stay below `period_seconds`; startup probes cap
`period_seconds` and `initial_delay_seconds` at 240. Worker pools and jobs do
not accept probes.

## Pub/Sub

### `PubSubTopic`

Renders `google_pubsub_topic`. Names are validated against the Pub/Sub rules
(3–255 chars, letter start, letters/digits/`-_.~+%`).

```python
from python_tofu import PubSubTopic

topics = [
    PubSubTopic(project="my-project", name="jobs", message_retention_duration="600s"),
    PubSubTopic(project="my-project", name="jobs-dlq"),
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Topic ID |
| `message_retention_duration` | `str \| None` | `None` | `"600s"`–`"2678400s"` (10 min–31 days) |
| `labels` | `dict` | `{}` | Metadata |

Topic retention makes messages replayable and is billed as storage after the
first day, unlike the 10 GiB/month throughput allowance.

### `PubSubSubscription`

Renders `google_pubsub_subscription` — pull by default, push when a target is
set. `topic` may be a declared topic name or a full `projects/.../topics/...`
path (declare external topics in `external_topics`).

```python
from python_tofu import DeadLetter, PubSubSubscription, RetryPolicy

subscriptions = [
    PubSubSubscription(
        project="my-project",
        name="jobs-worker",
        topic="jobs",
        ack_deadline_seconds=60,
        expiration_ttl="315360000s",          # ~10 years; never ""
        dead_letter=DeadLetter(topic="jobs-dlq", max_delivery_attempts=10),
        retry=RetryPolicy(minimum_backoff="10s", maximum_backoff="600s"),
        enable_message_ordering=True,
    ),
    PubSubSubscription(
        project="my-project",
        name="jobs-push",
        topic="jobs",
        push_service="api",                   # → google_cloud_run_v2_service.run_api.uri
        push_service_account="pubsub-push",   # OIDC identity; needs run.invoker
    ),
]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `topic` | `str` | required | Declared topic name or full path |
| `ack_deadline_seconds` | `int` | `10` | 10–600 |
| `message_retention_duration` | `str \| None` | Pub/Sub default | `"600s"`–`"604800s"` |
| `retain_acked_messages` | `bool` | `false` | Keeps acked messages (storage cost) |
| `expiration_ttl` | `str` | `"2678400s"` | Idle expiry, minimum 1 day |
| `filter` | `str \| None` | `None` | Attribute filter, ≤256 bytes, immutable |
| `dead_letter` | `DeadLetter \| None` | `None` | Topic + `max_delivery_attempts` (5–100) |
| `retry` | `RetryPolicy \| None` | `None` | Backoff 0–600s, min ≤ max |
| `enable_message_ordering` | `bool` | `false` | Ordered delivery per ordering key |
| `enable_exactly_once_delivery` | `bool` | `false` | Pull only; rejected with a push target |
| `push_endpoint` | `str \| None` | `None` | Explicit push URL (external webhooks) |
| `push_service` | `str \| None` | `None` | Declared Cloud Run service to push to |
| `push_service_account` | `str \| None` | `None` | OIDC identity, declared id or email |
| `push_audience` | `str \| None` | endpoint | OIDC audience |

Pushing to a private Cloud Run service needs both sides declared: the
subscription sets `push_service` + `push_service_account`, and the service lists
that account in `invoker_service_accounts`:

```python
CloudRunService(
    project="my-project",
    name="api",
    image="...",
    invoker_service_accounts=["pubsub-push"],
)
```

Two grants are emitted automatically, both using a `data "google_project"`
lookup of the project number:

- dead-letter topics: `roles/pubsub.publisher` for the Pub/Sub service agent;
- push subscriptions: `roles/iam.serviceAccountTokenCreator` on the push
  identity, so the service agent can mint the OIDC token (Google's documented
  requirement; a missing grant produces the same 403 as an unpropagated
  `run.invoker` binding).

> `expiration_ttl=""` is **not** expressible: the provider drops empty durations,
> so the subscription silently expires after 31 days. Use a long explicit TTL
> such as `"315360000s"` when you mean "never".

## Composing a stack

Split a stack into `StackPart` values and merge them with `compose`:

```python
# infra/stack.py
from python_tofu import GcpStack, StackPart, compose

from parts.foundation import provider
from parts.storage import part as storage

foundation = StackPart(name="foundation", projects=[...], apis=[...])

stack = GcpStack(provider=provider, **compose(foundation, storage))
```

`StackPart` mirrors every resource list on `GcpStack` plus `external_*` and
`outputs`; its `name` only labels the part in error messages. `compose`
concatenates lists in part order and raises when two parts declare the same
address (bucket name, topic, API, output, ...), naming both parts.
`external_*` values are de-duplicated silently, since the stack does not own
them. Cross-project validation still runs when the assembled `GcpStack` is
built. See [`examples/gcp_clean/`](../../examples/gcp_clean/) for the layout.
