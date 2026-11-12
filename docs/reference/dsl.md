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
| `service_accounts` | `list[ServiceAccount]` | `[]` | Service accounts and role bindings |
| `buckets` | `list[StorageBucket]` | `[]` | GCS buckets |
| `bucket_objects` | `list[BucketObject]` | `[]` | Objects (content) inside buckets |
| `iam_members` | `list[ProjectIamMember]` | `[]` | Standalone project IAM bindings |
| `backend` | `BackendConfig \| None` | `None` | State backend (omit for local default) |
| `external_projects` | `list[str]` | `[]` | Existing projects resources may reference |
| `external_buckets` | `list[str]` | `[]` | Existing buckets objects may target |
| `required_version` | `str` | `">= 1.6.0"` | OpenTofu version constraint |
| `google_provider_version` | `str` | `"~> 6.0"` | Google provider constraint |
| `usage_estimates` | `dict[str, float]` | `{}` | Monthly usage per limit key for free-tier checks (see [limits](limits.md)) |

Cross-resource references are validated: every `project` must be declared in
`projects`, equal to `provider.project`, or listed in `external_projects`.

## `GcpProvider`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `project` | `str` | required | Default project |
| `region` | `str` | `"us-central1"` | Default region |
| `zone` | `str \| None` | `None` | Default zone |
| `credentials` | `str \| None` | `None` | Path to a service-account key |
| `impersonate_service_account` | `str \| None` | `None` | Impersonation target |
| `default_labels` | `dict[str, str]` | `{}` | Provider-wide labels |

## `GcpProject`

`project_id` must be 6–30 characters, start with a letter, contain only lowercase
letters, digits and hyphens, and not end with a hyphen. `org_id` and `folder_id`
are mutually exclusive.

## `ProjectApi`

Enables a `google_project_service`. `service` is a full API name such as
`storage.googleapis.com`.

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
| `prefix` | `str` | `"python-tofu/state"` | GCS object prefix |
| `path` | `str \| None` | `None` | Local state path (required for `local`) |

## Composing a stack

A stack is a plain Python object, so it can be built from typed fragments in
separate modules. The config directory is importable while the module loads:

```python
# infra/stack.py
from python_tofu import GcpStack

from parts.foundation import apis, projects, provider
from parts.iam import iam_members, service_accounts
from parts.storage import buckets

stack = GcpStack(
    provider=provider,
    projects=projects,
    apis=apis,
    service_accounts=service_accounts,
    iam_members=iam_members,
    buckets=buckets,
)
```

Each part returns the list for one resource family; cross-project validation
still happens when the assembled `GcpStack` is constructed. See
[`examples/gcp_clean/`](../../examples/gcp_clean/) for the full layout.
