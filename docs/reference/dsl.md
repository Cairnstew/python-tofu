# DSL Reference

The DSL lives in `src/python_tofu/models/`. Every model is a frozen Pydantic
model with `extra="forbid"`; unknown fields and invalid GCP identifiers fail at
import time.

## `GcpStack`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `GcpProvider` | required | Google provider settings |
| `projects` | `list[GcpProject]` | `[]` | Projects to create |
| `apis` | `list[ProjectApi]` | `[]` | APIs to enable |
| `service_accounts` | `list[ServiceAccount]` | `[]` | Service accounts and role bindings |
| `buckets` | `list[StorageBucket]` | `[]` | GCS buckets |
| `iam_members` | `list[ProjectIamMember]` | `[]` | Standalone project IAM bindings |
| `backend` | `BackendConfig \| None` | `None` | State backend (omit for local default) |
| `external_projects` | `list[str]` | `[]` | Existing projects resources may reference |
| `required_version` | `str` | `">= 1.6.0"` | OpenTofu version constraint |
| `google_provider_version` | `str` | `"~> 6.0"` | Google provider constraint |

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
`"enforced"`.

## `ProjectIamMember`

A standalone `google_project_iam_member` binding. `member` must include its
principal prefix, e.g. `user:alice@example.com` or
`serviceAccount:sa@project.iam.gserviceaccount.com`.

## `BackendConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `kind` | `"local" \| "gcs"` | `"gcs"` | Backend type |
| `bucket` | `str \| None` | `None` | GCS bucket (required for `gcs`) |
| `prefix` | `str` | `"python-tofu/state"` | GCS object prefix |
| `path` | `str \| None` | `None` | Local state path (required for `local`) |
