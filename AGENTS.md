# Agent Instructions

## About this project

`python-tofu` is a typed Python DSL and CLI wrapper for managing GCP
infrastructure with OpenTofu. A Python module builds a validated `GcpStack`;
the renderer writes deterministic HCL; the CLI drives `tofu`.

It is a Python project managed with **uv2nix** — uv's `uv.lock` drives Nix
derivations via pure Nix code and the repo builds with `nix build .#default`.

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
| `src/python_tofu/models/` | Pydantic DSL for GCP resources and `GcpStack` |
| `src/python_tofu/hcl.py` | Dependency-free HCL writer |
| `src/python_tofu/services/renderer.py` | Stack → files in a workdir |
| `src/python_tofu/services/runner.py` | `tofu` subprocess wrapper |
| `src/python_tofu/loader.py` | Import a Python `infra.py` and return its `stack` |
| `src/python_tofu/cli/` | Typer commands and shared options |
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
nix develop
```

### Build for production

```bash
nix build .#default
```

### Run checks

```bash
just check        # lint + typecheck + unit tests + flake eval
pytest -q         # all tests (unit, integration, nix eval)
```

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
7. **Adding a GCP resource** — add a frozen Pydantic model in `models/gcp.py`,
   a renderer function in `services/renderer.py`, and tests. Update the DSL
   reference.
8. **HCL output must stay deterministic and `tofu fmt` clean** — use the
   in-tree writer, never string-concatenate raw HCL.
9. **Validate before `tofu` runs** — identifier and cross-reference checks belong
   in Pydantic models, not in CLI commands.
10. **Never commit credentials or state** — `.tofu/`, `*.tfstate` and
    `plan.tfplan` are ignored.

## Architecture notes

- `GcpStack` is frozen (`extra="forbid"`); tests rely on this.
- The renderer owns local resource names and rejects duplicates with `RenderError`.
- `TofuRunner` returns `CommandResult`; the CLI decides the exit code.
- `loader.load_stack` executes the config module, then validates `stack`.
- The CLI uses per-command options so `python-tofu plan --config ...` works.
