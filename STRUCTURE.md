# Project Structure

```
.
├── src/python_tofu/
│   ├── __init__.py               # Public DSL exports + __version__
│   ├── __main__.py               # python -m python_tofu
│   ├── py.typed                  # PEP 561 marker
│   ├── exceptions.py             # TofuError hierarchy
│   ├── hcl.py                    # Dependency-free HCL writer (Attr/Block/Raw)
│   ├── loader.py                 # Import infra.py → validated GcpStack
│   ├── models/
│   │   ├── __init__.py
│   │   ├── gcp.py                # GcpProvider, GcpProject, ServiceAccount, ...
│   │   ├── stack.py              # GcpStack, BackendConfig
│   │   └── results.py            # RenderResult, PlanSummary, CommandResult
│   ├── services/
│   │   ├── __init__.py
│   │   ├── renderer.py           # GcpStack → versions.tf/providers.tf/main.tf
│   │   └── runner.py             # tofu subprocess wrapper + show -json parsing
│   └── cli/
│       ├── __init__.py
│       ├── main.py               # Typer app and command registration
│       ├── context.py            # AppContext (config/workdir/binary/verbose)
│       ├── options.py            # Shared Annotated option types
│       └── commands/
│           ├── base.py           # BaseCommand: load, prepare, execute, report
│           ├── render.py
│           ├── init.py
│           ├── validate.py
│           ├── plan.py
│           ├── apply.py
│           ├── destroy.py
│           └── output.py
│
├── examples/gcp_bootstrap/
│   ├── infra.py                  # End-to-end example stack
│   └── README.md
│
├── tests/
│   ├── conftest.py               # src on sys.path, sample stack, fake tofu
│   ├── unit/
│   │   ├── test_hcl.py
│   │   ├── test_models.py
│   │   ├── test_renderer.py
│   │   ├── test_runner.py
│   │   ├── test_loader.py
│   │   └── test_cli.py
│   ├── integration/
│   │   └── test_cli_invocation.py
│   └── nix_eval/
│       └── test_module_eval.py
│
├── nix/
│   ├── default.nix               # mkApplication
│   ├── module.nix                # NixOS oneshot service
│   └── home-module.nix           # home.packages
│
├── docs/
│   ├── guides/
│   │   ├── quickstart.md
│   │   └── nixos-integration.md
│   └── reference/
│       ├── cli.md
│       ├── dsl.md
│       ├── module.md
│       └── ci.md
│
├── flake.nix                     # Flake outputs, devShells, checks
├── flake.lock
├── pyproject.toml
├── uv.lock
├── uv.lock.example
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

## Execution flow

```
infra.py
   │  importlib
   ▼
load_stack() ──► GcpStack (Pydantic validation)
   │
   ▼
Renderer.render()
   ├── resource_blocks()  ── local names + duplicate checks
   ├── _terraform_block() ── required_version, provider constraint, backend
   ├── _provider_block()
   └── hcl.render()
   │
   ▼
<workdir>/versions.tf, providers.tf, main.tf, .gitignore
   │
   ▼
TofuRunner ──► subprocess: tofu init / plan / apply / destroy / output
   │
   ▼
CommandResult ──► CLI output + exit code
```

## Type flow

```
GcpStack
 ├── GcpProvider
 ├── GcpProject      → google_project
 ├── ProjectApi      → google_project_service
 ├── ServiceAccount  → google_service_account + google_project_iam_member (roles)
 ├── StorageBucket   → google_storage_bucket
 ├── ProjectIamMember→ google_project_iam_member
 └── BackendConfig   → terraform { backend "..." { ... } }
```

## Design decisions

- **Python is the authoring layer, OpenTofu is the engine.** No reimplementation
  of planning/state; the wrapper renders HCL and shells out.
- **Validation belongs in models.** Invalid GCP IDs and unknown project
  references fail before any `tofu` process starts.
- **The HCL writer is in-tree.** It is small, deterministic, testable and keeps
  the dependency surface at Typer + Pydantic + Rich.
- **Commands are sub-apps with per-command options.** This lets
  `python-tofu plan --config ...` work without Click's group-option ordering
  restriction.
- **The example is the integration test.** `examples/gcp_bootstrap/infra.py` is
  loaded by unit, integration and flake checks.
