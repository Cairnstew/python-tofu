# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `scripts/live-module-vm.sh` (`just test-live-module`): a live end-to-end test
  of the NixOS module. It builds the system in `nix/live-vm.nix`, boots it under
  QEMU and lets the real `python-tofu.service` `apply` the stack in
  `nix/live-vm-stack.nix` at activation, then verifies the bucket, service
  account and IAM binding through the GCP APIs. `just clean-live-module`
  destroys them. Not a flake check: it needs `/dev/kvm`, network and a
  credential, and changes cloud state.
- `ServiceAccountIamMember` (and its `StackPart`/Nix section): a
  `google_service_account_iam_member` binding for delegation —
  `roles/iam.serviceAccountTokenCreator` (impersonation) or
  `roles/iam.serviceAccountUser` (actAs) on one specific account.
- `PruneConfig.protected_iam_roles` (default `("roles/owner",)`, owner always
  included): roles prune must never remove. `roles/editor` is not protected by
  default. `prune --explain` lists every skipped IAM binding with its reason.
- `PruneConfig.protected_service_accounts` and automatic protection of the
  active credential's service-account identity (the key's `client_email` plus
  any `impersonate_service_account` target). The guard applies regardless of
  `include_service_accounts` / `--allow-service-accounts`.
- `project_iam` prune section: managed-principal-only project IAM bindings.
  It skips human/group/domain/allUsers members, conditional bindings,
  `roles/owner`, the active identity and service accounts the stack does not
  declare. `apply --prune` always skips it (IAM is eventually consistent); use
  `python-tofu prune` explicitly.
- `PruneConfig.allow_raw_hcl`: explicit opt-in for pruning a stack that also
  uses `extra_files`. Without it, prune refuses to run because raw HCL
  resources are invisible to discovery.
- `ProjectIamMember.service_account`: set a declared account id or email instead
  of a prefixed `member`; it renders as
  `serviceAccount:${google_service_account.sa_x.email}` so the grant waits for
  the account. `member` and `service_account` are mutually exclusive.
- `GcpProvider.impersonate_service_account` now also applies to the wrapper's
  read-only calls (`doctor`, `limits --usage live`, `prune`, `ServiceCatalog`),
  not just the rendered provider block.
- `examples/org_projects/`: a two-phase, keyless per-project layout (dataclass
  specs in `models.py`, an org-admin `platform.py`, and an impersonated
  `acme_data.py`).
- `scripts/bootstrap-org-admin.sh` (also `just bootstrap-admin`): creates the
  one-time org-level seed admin service account, grants org roles and
  `billing.user`, and optionally writes a JSON key. It uses a throwaway
  `gcloud auth login` in its own `CLOUDSDK_CONFIG`, re-executes itself in
  `nix develop .#cloud` when `gcloud` is missing, and writes keys under the
  gitignored `.cache/gcp-keys/` unless `--force` says otherwise.
- Nix-authored stacks. `nix/stack.nix` mirrors the `GcpStack` fields as a Nix
  module option tree, with sections keyed by a local name whose key fills the
  resource identity field (`buckets.artifacts` → `name = "artifacts"`). The
  evaluated JSON goes through the same Pydantic models, so limits, `prune`,
  `doctor` and rendering are unchanged. Exposed through the flake as
  `lib.stackModule`, `lib.evalStack`, `lib.mkStackJson` and `lib.mkStackFile`.
- `--config` accepts `.json` and `.nix` as well as `.py`. A `.nix` config is
  evaluated with `nix eval --json` (with `--impure` only when it uses
  `<nixpkgs>`/`builtins.getFlake`), and the result is validated exactly like a
  Python stack. `packages.<system>.with-tofu-nix` carries the `nix` binary for
  the standalone form.
- `services.python-tofu.stack` and `stackFile`: declare the cloud stack in
  Nix. The module evaluates it at build time and writes JSON to the store, so
  no `nix` binary is needed at activation. `settings.autoApprove` exposes
  `--auto-approve` for `apply`/`destroy`, and `restartTriggers` make a rebuild
  restart the boot-time oneshot so the declaration is re-applied.
- The flake exposes `nixosModules.python-tofu` and
  `homeManagerModules.python-tofu` aliases alongside `default`, so a flake
  input can be imported by its own name.
- Reference strings (`"${resource.type.name.attr}"`) are accepted in
  free-form and cross-reference fields (`BucketObject.bucket`,
  `PubSubSubscription.topic`, IAM principals, service accounts, secrets).
  Identity fields that become HCL labels reject them with a targeted error.
- Nix bucket objects accept inline `content` (text generated with
  `builtins.toJSON`/`readFile`) and `source` as a derivation or Nix path
  literal, serialised to its store path. Documented the data-vs-derivation and
  bucket-versioning trade-offs in `docs/reference/nix-stacks.md`.
- Flake checks: `stack-eval` and `render-nix-example` (a Nix-authored stack
  must render byte-for-byte like the Python example), plus the Nix stack in
  `validate-examples`.

- `--var NAME=VALUE` and repeatable `--var-file` on `plan`, `apply` and
  `destroy`, matching OpenTofu's own flags. Relative files are resolved against
  the caller's directory like `--plan-file`. `apply --plan-file` rejects
  variables with a clear error instead of letting `tofu` fail.
- `render --check`/`--diff`/`--stdout FILE` render in memory so the workdir is
  never touched: `--check` exits `1` when the directory no longer matches the
  Python stack, `--diff` prints the unified diff, and `--stdout` prints one
  rendered file for review or piping.
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
- `python-tofu doctor` gains a toolchain group before the GCP checks: the
  OpenTofu version against `required_version`, required providers in the Nix
  mirror or cache, and a writable workdir. A missing `tofu` is a hard failure
  unless `--fail-on-unknown` semantics apply; an unset mirror is skipped
  because `init` downloads providers.
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
- `GcpProvider.default_apis`: a control-plane baseline enabled on every owned
  project and protected from pruning. Add workload APIs with `default_apis` or
  `apis`; undeclared APIs become prunable.
- `PruneConfig.include_service_accounts` plus `--allow-service-accounts`: a
  two-key gate for pruning service accounts. `PruneConfig(enabled=True)` now
  selects every section except service accounts, so `apply`/`prune` can clean
  up stale infrastructure without deleting the identity that runs `tofu`.
- `ProjectApi(disable_dependent_services=True)`: render the provider's
  `disable_dependent_services` so an API disable can cascade to dependents;
  `prune` uses it to remove a project's stale API graph in one pass.
- `examples/gcp_test_infra/`: a free-tier stack (bucket, object, topic,
  subscription, service account) with prune enabled, for exercising apply,
  state, prune and destroy against a real project.
- Development shell: the default shell now includes `just`, `pre-commit`,
  `nixpkgs-fmt`, `gh`, `gawk` alongside the locked venv, `uv` and `tofu`; it
  installs the pre-commit hook on first entry and sets
  `TOFU_PLUGIN_CACHE_DIR=$REPO_ROOT/.cache/tofu/plugins`. `.#dev` is an alias,
  `.#bootstrap` is the minimal `uv` shell, and `.#cloud` adds
  `google-cloud-sdk`.
- `formatter` output so `nix fmt` works, plus flake checks `lint`,
  `typecheck`, `unit-tests`, `integration-tests` and `render-test-example`, so
  `nix flake check` builds every gate CI runs separately.
- `Justfile` recipes `fmt`, `fmt-nix`, `test-nix`, `coverage`, `audit`,
  `nix-check-build`, `nix-shell` and `pre-commit`.
- `checks.validate-examples` renders three examples and runs
  `tofu init -backend=false` + `tofu validate` against the mirrored provider
  with the HTTP proxies pointed at a dead address, so provider schema drift
  fails `nix flake check` instead of a live apply. `checks.module-vm` boots the
  NixOS module with fake binaries and asserts its argv, PATH and plugin cache.
- NixOS module parity with the CLI: `settings.command` now accepts `doctor`,
  `prune` and `limits`, and new `settings.stackName`, `settings.limits`,
  `settings.usage`, `settings.varFile` and `settings.prune` map to the flags
  each subcommand actually accepts (Typer rejects unknown options, so `limits`
  no longer receives `--workdir`). `tofuPackage` puts OpenTofu on the unit's
  `PATH`, `environmentFile` supports secret files, and `schedule` creates a
  `systemd.timer`. The unit also sets `TF_PLUGIN_CACHE_DIR` under its workdir.
- The packaged app installs bash, zsh and fish completions under `share/`.
- `packages.<system>.with-tofu` (and `nix run .#with-tofu`) bundles OpenTofu
  with the mirrored `hashicorp/google` provider and sets `PYTHON_TOFU_BINARY`,
  so `init`/`plan` work with no registry access. `--binary` also reads
  `PYTHON_TOFU_BINARY` directly.

### Changed

- **The default Google provider constraint is now `~> 7.0`** (was `~> 6.0`),
  matching the provider nixpkgs mirrors. `nix/provider-versions.nix` is the
  single source: the packaged app exports it as
  `PYTHON_TOFU_GOOGLE_PROVIDER_VERSION`, `checks.provider-version` asserts the
  nixpkgs mirror satisfies it, and a stack that sets
  `google_provider_version` explicitly is unchanged.
- `services.python-tofu.settings.workdir` is a string, not a `types.path`: a
  path literal is copied into the read-only Nix store, which cannot hold state.

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

- `output` and `apply --plan-file` now resolve the default workdir from the
  stack's own `name`, matching `render`/`plan`/`apply`. They import the config
  only for that lookup (never render) and fall back to the config file stem
  when it cannot be loaded; the missing-directory error now suggests
  `--workdir` or `--stack-name`.
- A plain `plan --destroy` no longer fails on a stack that enables pruning:
  the stack's default prune setting is ignored for a destroy plan. An explicit
  `--prune`/`--prune-section` still conflicts with `--destroy`.
- Billing budgets now enable `billingbudgets.googleapis.com`, the API behind
  `google_billing_budget`, instead of `cloudbilling.googleapis.com` (which is
  the separate billing-account metadata API). Cloud Billing is still derived
  for a `GcpProject` that sets `billing_account`, and both billing APIs are on
  the prune protect list.
- API derivation covers the dependencies of the typed fields: Secret Manager
  for `secret_env` and secret volumes, Cloud SQL Admin for `cloud_sql` volumes,
  Cloud Storage for GCS volumes, Cloud Resource Manager for the
  `data.google_project` blocks behind Pub/Sub dead-letter and OIDC push IAM,
  and Pub/Sub plus Cloud Logging for Cloud Run functions. Provider
  impersonation enables `iamcredentials.googleapis.com`.
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
