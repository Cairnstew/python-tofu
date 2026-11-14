# Agent Instructions

## About this project

`python-tofu` is a typed Python DSL and CLI wrapper for managing infrastructure
with OpenTofu. A Python module builds a validated provider stack (GCP today);
the renderer writes deterministic HCL; the CLI drives `tofu`.

The package is split into a provider-agnostic `core/` and provider branches
under `providers/`. GCP-specific models, validation quirks and HCL shapes live
in `providers/gcp/`; core must never import from `providers`.

It is a Python project managed with **uv2nix** — uv's `uv.lock` drives Nix
derivations via pure Nix code and the repo builds with `nix build .#default`.

## Repository and CI

| Fact | Value |
|------|-------|
| Remote | `origin` → `github.com/Cairnstew/python-tofu` (public) |
| Default branch | `main` |
| CI entry point | `.github/workflows/ci.yml` — the only `push`/`pull_request` workflow |
| Local equivalent | `just check` (lint + typecheck + unit/integration tests + `nix flake check --no-build`) |

Every other workflow is `workflow_call` only and is invoked by `ci.yml`. CI
triggers on pushes to `main` and on pull requests, so work on a branch needs a
pull request to be tested. No repository secrets are used; workflows rely on
`GITHUB_TOKEN` and OIDC. See `docs/reference/ci.md` for the job table.

## Reference files

| File | Role |
|------|------|
| `STRUCTURE.md` | Project structure, execution flow, model/renderer/service layout |
| `UV2NIX.md` | Full uv2nix reference & lookup table |
| `GOTCHAS.md` | Pitfalls — read before debugging build, HCL or GCP issues |
| `HEATMAP.md` | Complexity/fragility heatmap of every project file |
| `TESTS.md` | Test tier layout and conventions |
| `CONTRIBUTING.md` | Contribution guide |
| `AGENTS.md` | This file |

## Key files

| File | Role |
|------|------|
| `flake.nix` | Nix flake — thin orchestrator, delegates to `nix/` |
| `nix/default.nix` | Package derivation (`mkApplication`) |
| `nix/module.nix` | NixOS module — oneshot systemd service |
| `nix/home-module.nix` | Home Manager module — user env package |
| `pyproject.toml` | Python metadata, dependencies, CLI entry point |
| `uv.lock` | uv lock file — drives the uv2nix overlay |
| `src/python_tofu/` | Application package |
| `src/python_tofu/core/` | Provider-agnostic engine: HCL, loader, runner, renderer base, CLI factory |
| `src/python_tofu/core/provider.py` | `Provider` plugin contract and registry |
| `src/python_tofu/core/limits.py` | `Limit`/`LimitPolicy`/`Usage`/`Throttler`, reports |
| `src/python_tofu/core/prune.py` | `PrunableResource`/`PrunePlan` + scratch-module `Reaper` |
| `src/python_tofu/providers/gcp/` | GCP branch: models, `GcpStack`, quirks, renderer, limits, live inventory, parts, plugin |
| `src/python_tofu/providers/gcp/renderer.py` | GCP stack → files in a workdir |
| `src/python_tofu/providers/gcp/limits.py` | GCP free-tier policy + usage measurement |
| `src/python_tofu/providers/gcp/live.py` | Cloud Asset Inventory live measurement |
| `src/python_tofu/providers/gcp/prune.py` | Live discovery of undeclared resources |
| `src/python_tofu/providers/gcp/services.py` | Service Usage catalog + API name resolution |
| `src/python_tofu/models/`, `services/`, `hcl.py`, `loader.py` | Backwards-compatible re-export shims |
| `src/python_tofu/cli/main.py` | Default GCP Typer app (`build_app(GCP, ...)`) |
| `examples/gcp_bootstrap/` | End-to-end project/service-account/bucket example |
| `tests/` | Unit, integration and Nix-eval suites |
| `.github/workflows/` | CI/CD workflows |

## Workflows

### Add a dependency

```bash
nix develop .#bootstrap
uv add <package>
uv lock
```

### Enter dev environment

```bash
nix develop              # default/dev shell: locked venv + tofu + just + pre-commit
nix develop .#bootstrap  # Python + uv only, for `uv add` / `uv lock`
nix develop .#cloud      # default shell plus google-cloud-sdk
```

The shell installs the pre-commit hook on first entry, sets `TOFU_PLUGIN_CACHE_DIR`
to `.cache/tofu/plugins`, and exports `REPO_ROOT`.

### Build for production

```bash
nix build .#default
```

### Run checks

```bash
just check        # lint + typecheck + unit/integration tests + flake eval
just fmt          # ruff fixes/format + `nix fmt`
just nix-check-build  # build every flake check, same as CI's nix job
pytest -q         # all tests (unit, integration, nix eval)
```

`nix flake check` builds `lint`, `typecheck`, `unit-tests`, `integration-tests`,
`format`, the example render checks and both module evaluations, using the same
locked toolchain as the dev shell.

## Rules for agents

1. **Never edit `uv.lock` directly** — always use `uv lock` or `uv add`/`uv remove`.
2. **After editing `pyproject.toml`**, run `uv lock` to regenerate `uv.lock`.
3. **After editing `flake.nix`**, run `nix flake lock` if inputs changed.
4. **Source filtering**: avoid filtering at the workspace root level (causes IFD +
   breaks editables). Filter per-package via the overlay in `flake.nix`.
5. **Python version**: controlled by `requires-python` in `pyproject.toml` and
   `python = pkgs.python312` in `flake.nix`. Keep them in sync.
6. **Adding Nix-specific overrides** — add an extension in
   `composeManyExtensions` in `flake.nix`. See `UV2NIX.md`.
7. **Adding a GCP resource** — add a frozen Pydantic model in
   `providers/gcp/models.py`, a renderer function in
   `providers/gcp/renderer.py`, its API dependencies in
   `providers/gcp/apis.py` (drive `required_apis`/`depends_on`), and tests.
   Update the DSL reference.
8. **Keep core provider-blind** — provider-specific rules (identifiers, backend
   kinds, resource naming) belong in `providers/<name>/`; core only knows the
   `Provider` contract.
9. **HCL output must stay deterministic and `tofu fmt` clean** — use the
   in-tree writer, never string-concatenate raw HCL.
10. **Validate before `tofu` runs** — identifier and cross-reference checks belong
    in provider Pydantic models, not in CLI commands.
11. **Limits are provider data, enforcement is core** — add `LimitPolicy`
    entries in the provider's `limits.py`; never add provider-specific
    enforcement paths to commands. Update `measure_usage` when a new resource
    type becomes measurable, and `live_measure_usage` when existing
    infrastructure can be counted. Never let an unmeasured limit report zero:
    return a `Usage` without that key so it is `unknown`.
12. **Never commit credentials or state** — `.tofu/`, `*.tfstate` and
    `plan.tfplan` are ignored.
13. **Commands are registry data** — add in-tree commands through `_BUILTINS` in
    `core/cli/commands/__init__.py` (or `register_command`); out-of-tree
    extensions use the `python_tofu.commands` / `python_tofu.providers` entry
    points. Keep `build_app(provider, ...)` provider-agnostic and let a failing
    plugin warn rather than abort startup.

## Architecture notes

- `BaseStack` is frozen (`extra="forbid"`); `GcpStack` subclasses it and tests
  rely on immutability.
- `BaseRenderer` owns the managed-file contract; `GcpRenderer` overrides the
  provider hooks (`required_providers`, `backend_block`, `provider_blocks`,
  `resource_blocks`).
- The GCP renderer owns local resource names and rejects duplicates with
  `RenderError`.
- `BaseCommand.prepare()` checks `provider.limit_policy` via
  `core.limits.Throttler` before rendering; `--limits error|warn|off` controls
  it and `python-tofu limits` reports measured usage.
- `TofuRunner` returns `CommandResult`; the CLI decides the exit code.
- `core.loader.load_stack(path, stack_type)` executes the config module, then
  validates `stack`; `python_tofu.loader.load_stack(path)` is the GCP default.
- The CLI uses per-command options so `python-tofu plan --config ...` works.
  Commands are built by `create_app(provider)` factories; bind another provider
  with `core.cli.app.build_app(...)`.
