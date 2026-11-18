# Project Structure

```
.
├── src/python_tofu/
│   ├── __init__.py               # Public facade: core + GCP exports, __version__
│   ├── __main__.py               # python -m python_tofu
│   ├── py.typed                  # PEP 561 marker
│   │
│   ├── core/                     # Provider-agnostic engine
│   │   ├── __init__.py
│   │   ├── doctor.py             # CheckResult/DoctorReport for the doctor command
│   │   ├── exceptions.py         # TofuError hierarchy
│   │   ├── hcl.py                # Dependency-free HCL writer (Attr/Block/Raw)
│   │   ├── limits.py             # Limit/LimitPolicy/Usage/Throttler + reports
│   │   ├── models.py             # TofuModel, BackendConfig, BaseStack
│   │   ├── results.py            # RenderResult, PlanSummary, CommandResult
│   │   ├── toolchain.py          # tofu version/provider mirror/workdir checks
│   │   ├── loader.py             # load_stack(path, stack_type)
│   │   ├── provider.py           # Provider contract + registry
│   │   ├── prune.py              # PrunableResource/PrunePlan + scratch-module Reaper
│   │   ├── renderer.py           # BaseRenderer: file contract + terraform block
│   │   ├── runner.py             # TofuRunner subprocess wrapper
│   │   └── cli/
│   │       ├── app.py            # build_app(provider) → Typer app
│   │       ├── base.py           # BaseCommand: load, prepare, execute, report
│   │       ├── context.py        # AppContext bound to a provider
│   │       ├── options.py        # Shared option types, path resolution
│   │       ├── registry.py       # Command registry + entry-point discovery
│   │       └── commands/         # create_app(provider) factories
│   │           ├── render.py
│   │           ├── init.py
│   │           ├── validate.py
│   │           ├── doctor.py     # Read-only preflight checklist
│   │           ├── plan.py
│   │           ├── prune.py
│   │           ├── apply.py
│   │           ├── destroy.py
│   │           ├── output.py
│   │           ├── limits.py
│   │           └── plugins.py
│   │
│   ├── providers/
│   │   ├── __init__.py           # Registry re-exports
│   │   └── gcp/                  # Google Cloud Platform branch
│   │       ├── __init__.py       # Exports; importing registers GCP
│   │       ├── models.py         # GcpProvider, GcpProject, ..., GcpBackendConfig
│   │       ├── stack.py          # GcpStack(BaseStack) + cross-reference checks
│   │       ├── quirks.py         # GCP regexes, role rules, slug, uniqueness
│   │       ├── limits.py         # GCP_FREE_TIER policy + usage measurement
│   │       ├── live.py           # Cloud Asset Inventory live measurement
│   │       ├── apis.py           # APIs per resource + depends_on ordering
│   │       ├── services.py       # Service Usage catalog + name resolution
│   │       ├── prune.py          # Live discovery of undeclared resources
│   │       ├── renderer.py       # GcpRenderer(BaseRenderer[GcpStack])
│   │       ├── parts.py          # StackPart + compose() for multi-file stacks
│   │       ├── provider.py       # GCP Provider instance
│   │       └── cli/
│   │           ├── apis.py       # GCP-specific `apis` command
│   │           └── doctor.py     # GCP preflight checks
│   │
│   ├── exceptions.py             # Shim → core.exceptions
│   ├── hcl.py                    # Shim → core.hcl
│   ├── loader.py                 # Default-GCP loader shim
│   ├── models/                   # Historical import path (re-exports)
│   │   ├── __init__.py
│   │   ├── gcp.py                # Shim → providers.gcp.models
│   │   ├── results.py            # Shim → core.results
│   │   └── stack.py              # Shim → providers.gcp.stack
│   ├── services/                 # Historical import path (re-exports)
│   │   ├── __init__.py
│   │   ├── renderer.py           # Renderer = GcpRenderer
│   │   └── runner.py             # Shim → core.runner
│   └── cli/
│       ├── __init__.py
│       └── main.py               # app = build_app(GCP, version=...)
│
├── examples/
│   ├── gcp_bootstrap/
│   │   ├── infra.py              # Single-file end-to-end example
│   │   └── README.md
│   ├── gcp_biglake/
│   │   ├── stack.py              # BigLake catalog/database/table via extra_files
│   │   └── README.md
│   ├── gcp_cloud_run/
│   │   ├── stack.py              # Image-based service + source-based function
│   │   ├── hello/                # Function source zipped by the config
│   │   └── README.md
│   ├── gcp_apis/
│   │   ├── stack.py              # Service Usage-validated API enablement
│   │   └── README.md
│   ├── gcp_clean/
│   │   ├── stack.py              # Wires the parts together
│   │   └── parts/                # foundation / storage / iam
│   ├── gcp_pubsub/
│   │   ├── stack.py              # Topic/subscription, push + dead letter
│   │   └── README.md
│   ├── org_projects/
│   │   ├── models.py             # Dataclass project/identity specs
│   │   ├── platform.py           # Phase 1: project, accounts, delegation grants
│   │   ├── acme_data.py          # Phase 2: impersonated project resources
│   │   └── README.md
│   └── gcp_test_infra/
│       ├── stack.py              # Free-tier bucket, topic, subscription, account
│       └── README.md
│
├── tests/
│   ├── conftest.py               # src on sys.path, sample stack, fake tofu
│   ├── unit/
│   │   ├── test_hcl.py
│   │   ├── test_models.py
│   │   ├── test_provider_plugin.py  # core registry + non-GCP provider
│   │   ├── test_renderer.py
│   │   ├── test_runner.py
│   │   ├── test_loader.py
│   │   ├── test_limits.py          # core Limit/Usage/Throttler arithmetic
│   │   ├── test_cli.py
│   │   ├── test_cli_registry.py    # Registry, custom commands, plugin discovery
│   │   ├── test_gcp_apis.py        # Derived APIs and depends_on ordering
│   │   ├── test_gcp_budget.py      # BillingBudget validation and HCL
│   │   ├── test_gcp_cloud_run.py   # Services, functions, jobs, worker pools
│   │   ├── test_gcp_limits.py      # Free-tier catalog, measurement, aggregates
│   │   ├── test_gcp_live.py        # Cloud Asset Inventory parsing and rules
│   │   ├── test_gcp_objects.py     # BucketObject validation and HCL
│   │   ├── test_gcp_pubsub.py      # Topics, subscriptions, push, dead letters
│   │   ├── test_gcp_services.py    # Service Usage catalog and resolution
│   │   ├── test_prune.py           # Live discovery and scratch-module reaper
│   │   ├── test_stack_profile.py   # preview profile + stack limits_mode
│   │   ├── test_compose.py         # StackPart/compose merging and duplicates
│   │   ├── test_outputs.py         # Output model, ref(), output block rendering
│   │   ├── test_stack_isolation.py # Per-stack workdir and state prefix
│   │   ├── test_doctor.py          # Preflight checks with a fake Google API
│   │   ├── test_provider_version.py # Provider constraint from Nix/env
│   │   └── test_toolchain.py       # tofu version, provider mirror, workdir checks
│   ├── integration/
│   │   └── test_cli_invocation.py
│   └── nix_eval/
│       └── test_module_eval.py
│
├── nix/
│   ├── default.nix               # mkApplication + completions + version env
│   ├── gen-completions.py        # Typer templates → bash/zsh/fish
│   ├── provider-versions.nix     # Single source for mirrored provider versions
│   ├── module.nix                # NixOS oneshot service + timer
│   └── home-module.nix           # home.packages
│
├── scripts/
│   └── bootstrap-org-admin.sh      # One-time org admin SA seed (temp gcloud login)
│
├── docs/
│   ├── guides/
│   │   ├── quickstart.md
│   │   └── nixos-integration.md
│   └── reference/
│       ├── cli.md
│       ├── dsl.md
│       ├── limits.md
│       ├── module.md
│       ├── plugins.md
│       └── ci.md
│
├── flake.nix                     # Flake outputs: packages, formatter, devShells, checks
├── flake.lock
├── pyproject.toml
├── uv.lock
├── Justfile
├── .pre-commit-config.yaml
├── .envrc
├── .gitignore
├── README.md
├── STRUCTURE.md
├── AGENTS.md
├── GOTCHAS.md
├── HEATMAP.md
├── TESTS.md
├── CONTRIBUTING.md
├── RELEASE.md
└── CHANGELOG.md
```

## Layers

The package has a strict dependency direction:

```
python_tofu.cli.main ──► providers.gcp ──► core
        │                                   ▲
        └──────────────► core.cli ──────────┘
```

- **`core`** may not import anything from `providers`. It defines the plugin
  contract (`Provider`), the generic stack envelope (`BaseStack`), the file
  contract (`BaseRenderer`) and the CLI factory.
- **`providers.gcp`** imports core and supplies the GCP models, validation
  quirks, HCL shapes and the registered `GCP` plugin.
- **Top-level modules** (`models/`, `services/`, `hcl.py`, `loader.py`, …) are
  thin re-exports kept for backwards compatibility.

## Execution flow

```
infra.py
   │  importlib
   ▼
core.loader.load_stack(path, GCP.stack_type) ──► GcpStack (Pydantic)
   │
   ▼
core.limits.Throttler(GCP.limit_policy).check(usage)
   │  usage = GCP.measure_usage(stack)            # --usage stack (default)
   │        + GCP.live_measure_usage(stack)       # --usage live (CAI, read-only)
   │  error (default) → abort; warn → print; off → skip; unknown → ?/fail
   ▼
GCP.renderer_type = GcpRenderer(workdir)
   │
   ├── BaseRenderer.render_text()  ── file contract, terraform block
   ├── GcpRenderer.required_providers() ── hashicorp/google constraint
   ├── GcpRenderer.backend_block()      ── gcs/local backend
   ├── GcpRenderer.provider_blocks()    ── provider "google" { ... }
   └── GcpRenderer.resource_blocks()    ── google_* resources
   │
   ▼
core.hcl.render() → <workdir>/versions.tf, providers.tf, main.tf, .gitignore
   │
   ▼
core.runner.TofuRunner ──► tofu init / plan / apply / destroy / output
   │
   ▼
CommandResult ──► CLI output + exit code
```

## Type flow

```
BaseStack (core)                    ← required_version, backend
 └── GcpStack (providers.gcp)       ← provider + GCP resources
      ├── GcpProvider
      ├── GcpProject      → google_project
      ├── ProjectApi      → google_project_service
      ├── ServiceAccount  → google_service_account + role bindings
      ├── StorageBucket   → google_storage_bucket
      ├── BucketObject    → google_storage_bucket_object (+ data "http" for URLs)
      ├── ProjectIamMember→ google_project_iam_member
      ├── CloudRunService → google_cloud_run_v2_service
      ├── CloudRunFunction → google_cloudfunctions2_function (+ source object)
      ├── CloudRunJob      → google_cloud_run_v2_job
      ├── CloudRunWorkerPool → google_cloud_run_v2_worker_pool
      ├── ArtifactRegistryRepository → google_artifact_registry_repository
      ├── apis.py         → required APIs per resource + depends_on ordering
      ├── PubSubTopic      → google_pubsub_topic
      ├── PubSubSubscription → google_pubsub_subscription (+ push OIDC, DLQ IAM)
      ├── GcpBackendConfig→ terraform { backend "..." { ... } }
      └── usage_estimates  → LimitPolicy usage (free-tier checks)
```

## Adding a provider

1. Create `src/python_tofu/providers/<name>/` with `models.py`, `stack.py`
   (subclass `BaseStack`), `renderer.py` (subclass `BaseRenderer[YourStack]`)
   and `provider.py` (`register_provider(Provider(...))`).
2. Optionally supply a `LimitPolicy` and `measure_usage` so
   `--limits`/`python-tofu limits` work for the provider.
3. Export the plugin from the provider's `__init__.py`.
4. Bind a CLI with `core.cli.app.build_app(YOUR_PROVIDER, version=...)` — no
   core command code needs to change.

Provider quirks (identifier rules, resource naming, provider-specific blocks)
belong in the provider package, not in core.

## Design decisions

- **Python is the authoring layer, OpenTofu is the engine.** No reimplementation
  of planning/state; the wrapper renders HCL and shells out.
- **Core is provider-blind.** GCP-specific rules live in `providers/gcp`; the
  core only knows the `Provider` contract.
- **Validation belongs in provider models.** Invalid GCP IDs and unknown project
  references fail before any `tofu` process starts.
- **Limits are a core contract.** Providers declare a `LimitPolicy` and a
  `measure_usage` function; core enforces `error`/`warn`/`off` uniformly and
  supports both per-area limits and an aggregate (summarised) ceiling.
- **The HCL writer is in-tree.** It is small, deterministic, testable and keeps
  the dependency surface at Typer + Pydantic + Rich.
- **Commands are sub-apps with per-command options.** This lets
  `python-tofu plan --config ...` work without Click's group-option ordering
  restriction, and each command is built by a `create_app(provider)` factory.
- **The example is the integration test.** `examples/gcp_bootstrap/infra.py` is
  loaded by unit, integration and flake checks.
