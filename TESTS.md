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
│   ├── test_gcp_limits.py #   Free-tier catalog, measurement, aggregates
│   ├── test_gcp_live.py   #   Cloud Asset Inventory parsing and free-tier rules
│   ├── test_provider_plugin.py # Registry + core renderer with a non-GCP provider
│   ├── test_renderer.py   #   Golden-style HCL assertions, duplicates, backends
│   ├── test_runner.py     #   Command construction, JSON parsing, errors
│   ├── test_loader.py     #   Config module import and error wrapping
│   └── test_cli.py        #   Typer CliRunner + fake tofu binary
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
| `core/renderer.py` | `unit/` | Managed-file contract via a minimal non-GCP renderer |
| `providers/gcp/models.py` | `unit/` | Instantiate Pydantic models; assert validation errors |
| `providers/gcp/renderer.py` | `unit/` | Render a sample stack and assert HCL fragments; duplicate errors |
| `core/runner.py` | `unit/` | Monkeypatch `subprocess.run`; assert argv and parsing |
| `core/loader.py` | `unit/` | Write temporary config modules; assert errors |
| `core/cli/` | `unit/` + `integration/` | `CliRunner` with fake tofu; subprocess `python -m python_tofu` |
| `nix/module.nix` | `nix_eval/` | Evaluate `nixosModules.default` and option defaults |

## What not to do

- Do not call real GCP APIs in tests.
- Do not require a real `tofu` binary for unit tests; use `fake_tofu`.
- Do not assert on exact whitespace unless testing the writer itself; prefer
  values and block headers so alignment changes don't break every test.
