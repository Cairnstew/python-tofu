# Tests

Three-tier test suite with scoped fixtures and Nix integration tests.

## Layout

```
tests/
├── conftest.py            # src on sys.path, sample_stack, config_file, fake_tofu
│
├── unit/                  # Fast — no network, no real tofu, no GCP
│   ├── test_hcl.py        #   Writer: escaping, collections, Raw, alignment
│   ├── test_models.py     #   Pydantic validation and cross-references
│   ├── test_limits.py     #   Core Limit/Usage/Throttler arithmetic and reports
│   ├── test_gcp_apis.py   #   Derived API sets and depends_on ordering
│   ├── test_gcp_budget.py #   BillingBudget validation and rendering
│   ├── test_gcp_cloud_run.py # Services, functions, jobs, worker pools
│   ├── test_gcp_limits.py #   Free-tier catalog, measurement, aggregates
│   ├── test_gcp_live.py   #   Cloud Asset Inventory parsing and free-tier rules
│   ├── test_gcp_objects.py #  BucketObject validation and HCL shapes
│   ├── test_gcp_pubsub.py #   Topics, subscriptions, push and dead letters
│   ├── test_gcp_services.py # Service Usage catalog, resolution and throttling
│   ├── test_prune.py      #   Live discovery and scratch-module reaper
│   ├── test_provider_plugin.py # Registry + core renderer with a non-GCP provider
│   ├── test_renderer.py   #   Golden-style HCL assertions, duplicates, backends
│   ├── test_runner.py     #   Command construction, JSON parsing, errors
│   ├── test_loader.py     #   Config module import and error wrapping
│   ├── test_cli.py        #   Typer CliRunner + fake tofu binary
│   ├── test_cli_registry.py # Command registry, aliases, plugin discovery
│   ├── test_outputs.py    #   Output/ref rendering and validation
│   ├── test_stack_profile.py # preview profile and stack limits_mode
│   ├── test_compose.py    #   StackPart/compose merging and duplicates
│   ├── test_stack_isolation.py # Default workdir and GCS prefix per stack
│   └── test_doctor.py     #   Doctor checks with a fake Google API
│
├── integration/           # CLI subprocess invocation
│   └── test_cli_invocation.py
│
└── nix_eval/              # Requires nix in PATH
    └── test_module_eval.py
```

## Running subsets

```bash
pytest tests/unit/            # fast, no I/O
pytest tests/integration/     # CLI subprocess
pytest -m "not nix"           # skip Nix-dependent tests
pytest tests/nix_eval/ -m nix # only Nix eval tests
pytest tests/                 # everything
```

## Markers

| Marker | Scope | Skippable |
|--------|-------|-----------|
| `nix` | Tests requiring `nix` in PATH | `-m 'not nix'` |
| `integration` | CLI subprocess tests | `-m 'not integration'` |

## Fixtures

- `sample_stack` — a complete `GcpStack` with every GCP resource type.
- `test_provider_plugin.py` also defines a dummy stack/renderer to prove the
  core is provider-agnostic.
- `config_file` — writes a temporary `infra.py` exposing `stack`.
- `fake_tofu` — an executable shell script that emulates `tofu plan/show/output`
  without touching GCP.

## Testing by package layer

| Package layer | Test tier | Approach |
|---------------|-----------|----------|
| `core/hcl.py` | `unit/` | Direct assertions on rendered text |
| `core/provider.py` | `unit/` | Registry lookup, unknown-provider error, custom provider rendering |
| `core/limits.py` | `unit/` | Usage arithmetic, exceeded/warn/unknown actions, aggregates, enforcement |
| `providers/gcp/limits.py` | `unit/` | Free-tier amounts, region filtering, estimate merging |
| `providers/gcp/live.py` | `unit/` | CAI pagination, region/type rules, live-over-stack override |
| `providers/gcp/apis.py` | `unit/` | Derived API sets, `depends_on` ordering, external projects |
| `providers/gcp/services.py` | `unit/` | Service Usage parsing, 429/404 handling, name resolution |
| `providers/gcp/prune.py`, `core/prune.py` | `unit/` | Discovery rules, protected resources, scratch-module plan |
| `providers/gcp/models.py` (`BucketObject`) | `unit/` | Source exclusivity, key rules, bucket references |
| `providers/gcp/models.py` (Pub/Sub, Cloud Run, budget) | `unit/` | Validation and import-time errors |
| `providers/gcp/renderer.py` (`BucketObject`) | `unit/` | Inline/source/URL blocks, bytes materialisation, http provider |
| `providers/gcp/renderer.py` (Pub/Sub, Cloud Run, budget) | `unit/` | HCL shapes, ordering and API dependencies |
| `core/renderer.py` | `unit/` | Managed-file contract via a minimal non-GCP renderer |
| `providers/gcp/models.py` | `unit/` | Instantiate Pydantic models; assert validation errors |
| `providers/gcp/renderer.py` | `unit/` | Render a sample stack and assert HCL fragments; duplicate errors |
| `core/runner.py` | `unit/` | Monkeypatch `subprocess.run`; assert argv and parsing |
| `core/loader.py` | `unit/` | Write temporary config modules; assert errors |
| `core/cli/registry.py` | `unit/` | Registration conflicts, ordering, aliases, fake entry points |
| `core/cli/` | `unit/` + `integration/` | `CliRunner` with fake tofu; subprocess `python -m python_tofu` |
| `nix/module.nix` | `nix_eval/` | Evaluate `nixosModules.default` and option defaults |

## What not to do

- Do not call real GCP APIs in tests.
- Do not require a real `tofu` binary for unit tests; use `fake_tofu`.
- Do not assert on exact whitespace unless testing the writer itself; prefer
  values and block headers so alignment changes don't break every test.
