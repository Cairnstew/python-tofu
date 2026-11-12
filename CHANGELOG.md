# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `python-tofu --version`.
- Declared outputs: `Output` and `ref()` (`GcpStack.outputs`) render `output`
  blocks after every resource, so `python-tofu output` can read service URLs,
  bucket names and topic IDs. Output names are validated as unique HCL
  identifiers.
- `plan --exit-code` exits `2` when the plan has changes, `0` when it is empty
  and `1` when the summary cannot be read, so CI can gate without parsing text.
- `BillingBudget` (`google_billing_budget`): alert-only thresholds on a billing
  account, with an optional project filter, Pub/Sub topic or notification
  channels. Budgets never disable billing.
- `GcpStack(profile="preview")`: a documented bundle that turns deletion
  protection off, enables pruning, uses local state, sets `limits_mode=warn`
  and adds the `ephemeral=true` label. Explicit per-resource values win, and
  the resolved values are rendered.
- `GcpStack.limits_mode` for stack-level limit enforcement, used when neither
  `--limits` nor the provider policy chooses a mode.
- `StackPart` and `compose()` for multi-file stacks: parts merge in order and
  duplicate addresses fail at build time with both part names. The
  `examples/gcp_clean/` stack now uses them and renders identical HCL.
- `python-tofu doctor`: a read-only preflight that checks credentials, project
  lifecycle, billing, required APIs, backend reachability, the GCS state lock
  and the limits summary. Each failure prints the command that fixes it;
  `--usage live`, `--fail-on-unknown` and `--json` match the other commands.
  Providers supply checks through `Provider.doctor_checks`.
- Provider-agnostic limits/throttler in `python_tofu.core.limits`: per-area
  `Limit`s, normalised `AggregateLimit`s, `Usage`, `LimitReport` and
  `LimitExceeded`.
- GCP always-free-tier policy (`providers/gcp/limits.py`) enforced before
  `render`/`init`/`validate`/`plan`/`apply`/`destroy`, with `--limits
  error|warn|off` and a `python-tofu limits` report command.
- `GcpStack.usage_estimates` and `StorageBucket.estimated_size_gb` for declaring
  usage the stack cannot derive.
- `--usage stack|live` and `--fail-on-unknown`. Live mode reads Cloud Asset
  Inventory (free, read-only) so manually created and pre-existing instances,
  disks and GKE clusters count against the free tier.
- `LimitCheck.status` (`ok`/`exceeded`/`unknown`): unmeasured limits are
  reported as `unknown` instead of silently passing as `0%`.
- Config modules may import sibling modules and subpackages, so a stack can be
  split one module per resource family. `examples/gcp_clean/` demonstrates the
  layout.
- Command registry (`core/cli/registry.py`): `CommandSpec`/`CommandRegistry`,
  `register_command`, ordered commands and aliases.
- Entry-point plugin discovery for `python_tofu.providers` and
  `python_tofu.commands`; broken plugins warn instead of aborting. Disable with
  `PYTHON_TOFU_NO_PLUGINS=1`.
- `python-tofu plugins` reports the active provider, registered commands and
  discovered plugins (`--json`).
- `BucketObject` (`google_storage_bucket_object`): inline text or bytes, a local
  file, or an HTTP(S) URL. Content types are guessed from the key; bytes are
  materialised under the workdir. Objects are compared by Terraform state, so
  unchanged content is not re-uploaded; `StorageBucket.versioning` retains
  generations.
- `GcpStack.external_buckets` for objects that target pre-existing buckets.
- Opt-in pruning of undeclared live infrastructure. `PruneConfig` (default off)
  selects `buckets`, `service_accounts` and/or `apis`; `python-tofu prune`
  previews by default and `--apply` deletes, while `plan --prune` previews and
  `apply --prune` prunes after applying. Live discovery uses the Storage, IAM and
  Service Usage read APIs and deletion runs through a throw-away OpenTofu module
  (`<workdir>/.python-tofu-prune/`), so the provider deletes the resources and
  the real state backend is never touched. Google-managed service accounts and
  essential APIs are skipped by design.
- Service Usage catalog (`providers/gcp/services.py`): `ServiceCatalog` lists
  enabled/available/all services, resolves short names via `services.get`, and
  `enable(*names)` returns deduplicated `ProjectApi` entries. `enable_apis(...)`
  is a one-shot wrapper. Unknown and ambiguous names raise with suggestions.
- `python-tofu apis` inspects the catalog (`--state`, `--filter`, `--resolve`,
  `--json`, `--quota-project`) without invoking OpenTofu.
- `examples/gcp_apis/` documents validated short-name API enablement and the
  Service Usage listing quota.
- `GcpStack.extra_files`: write flat `.tf`/`.tf.json` files verbatim beside the
  generated HCL, for provider resources the typed DSL does not model. Managed
  files cannot be overridden.
- `examples/gcp_biglake/` enables BigLake (`biglake.googleapis.com`) and declares
  a Hive catalog, database and table through `extra_files`.
- `examples/gcp_cloud_run/` shows both Cloud Run deployment paths: a service
  from a prebuilt image reference, and a 2nd-gen function whose source zip is
  built deterministically and uploaded as a typed `BucketObject`.
- Typed `CloudRunService` (`google_cloud_run_v2_service`) and
  `CloudRunFunction` (`google_cloudfunctions2_function`) models with hardened
  defaults: internal ingress, private invoker, deletion protection, scale-to-zero
  with a bounded maximum, capped CPU/memory, optional VPC egress, env and
  `SecretEnv` variables, and declared-service-account wiring. `GcpStack` gains
  `cloud_run_services` and `cloud_run_functions`.
- `CloudRunJob` (`google_cloud_run_v2_job`) for batch runners, with task/parallelism
  caps, retry limits, resources, env/secrets and deletion protection.
- `ArtifactRegistryRepository` (`google_artifact_registry_repository`) for Docker
  image repositories.
- `CloudRunWorkerPool` (`google_cloud_run_v2_worker_pool`) for pull-based
  background workers, with manual or automatic scaling, volumes and VPC access.
- `Volume` mounts for services and worker pools: Cloud Storage (GCS FUSE), NFS,
  ephemeral `empty_dir`, Cloud SQL sockets and Secret Manager files.
- `Probe` / `HttpProbe` / `TcpProbe` / `GrpcProbe` startup and liveness probes
  for services, with timing validation.
- `PubSubTopic` (`google_pubsub_topic`) and `PubSubSubscription`
  (`google_pubsub_subscription`) with pull/push delivery, filters, ordering,
  exactly-once, retry policy, dead-letter topics (including the Pub/Sub service
  agent grant) and explicit expiration TTLs.
- `invoker_service_accounts` on `CloudRunService` so a Pub/Sub push identity
  can be granted `roles/run.invoker`.
- Prune sections for `subscriptions` and `topics`, discovered through the
  Pub/Sub API and deleted subscriptions-first.
- Automatic API enablement: `GcpProvider(auto_enable_apis=True)` derives the
  `google_project_service` resources each declared resource needs and orders
  every consumer after them with `depends_on`, so one apply works into a
  project whose APIs are still disabled. `auto_enable_apis=False` keeps the
  explicit list only.

### Changed

- **Default workdir and state prefix are per-stack.** When `--workdir` is
  omitted it is now `.tofu/<stack-name>` (stack name = `--stack-name`, else the
  stack's `name`, else the config file stem) instead of the shared `.tofu`, and
  a GCS backend's default `prefix` is `python-tofu/<stack-name>` instead of
  `python-tofu/state`. An explicit `--workdir` or `prefix` is used unchanged.
  Migration: add `--workdir .tofu` to commands that relied on the old shared
  directory and were run with a config whose stem is not `infra`; existing
  stacks keep working when they pass `--workdir` explicitly.
- Split the package into a provider-agnostic `python_tofu.core` and a
  `python_tofu.providers.gcp` branch. GCP models, validation quirks and HCL
  shapes now live under `providers/gcp/`; the core exposes a `Provider` plugin
  contract and `build_app(provider)` CLI factory.
- The historical import paths (`python_tofu.models`, `python_tofu.services`,
  `python_tofu.hcl`, `python_tofu.loader`, `python_tofu.exceptions`) remain as
  backwards-compatible re-exports.

### Fixed

- The HCL writer aligned every attribute in a block to one column, so an
  attribute that followed a nested block (for example `depends_on` after
  `versioning`) was over-padded and `tofu fmt -check` rejected the rendered
  file. Alignment now resets at each nested block, matching `tofu fmt`, and
  every bundled example renders fmt-clean.
- `bandit` findings no longer fail CI: the renderer raises `RenderError` where
  it previously used `assert` for model invariants, `get_json` rejects
  non-HTTP URLs, and the two deliberate `subprocess`/`urlopen` uses carry a
  justified `# nosec`.
- `uv.lock` picks up patched `certifi`, `filelock`, `msgpack`, `pip` and
  `urllib3` so `pip-audit` reports no known vulnerabilities.
- `plan` with a relative `--workdir` (including the documented `.tofu/example`
  quickstart) no longer writes the plan inside a nested workdir path.
- `--plan-file` and `--var-file` are resolved against the current directory
  instead of inside `--workdir`.
- `apply --plan-file` reports a missing work directory instead of a misleading
  "OpenTofu binary not found" error.

## [0.1.0] - 2026-11-09

### Added

- Typed Pydantic DSL for GCP projects, APIs, service accounts, IAM bindings and
  GCS buckets (`GcpStack`).
- Deterministic, `tofu fmt`-clean HCL writer with attribute alignment and raw
  expressions.
- Renderer with duplicate-address detection, local resource naming and local/GCS
  backend support.
- `TofuRunner` subprocess wrapper for `init`, `validate`, `plan`, `apply`,
  `destroy` and `output`, plus `tofu show -json` plan summaries.
- Typer CLI: `render`, `init`, `validate`, `plan`, `apply`, `destroy`, `output`.
- Python config loader that imports an `infra.py` and validates its `stack`.
- End-to-end GCP bootstrap example (project, APIs, service account, bucket).
- Nix flake with uv2nix builds, dev shells, overlay, NixOS and Home Manager
  modules.
- Unit, integration and Nix-eval test suites with a fake `tofu` binary.
- CI/CD with path-based change detection and reusable workflows.
