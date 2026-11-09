# Contributing

## Prerequisites

- Nix (with flakes enabled)
- `just` (optional, for recipe shortcuts)
- `tofu` on `PATH` for end-to-end checks

## Quick start

```bash
nix develop
just check
```

## Development loop

1. Make changes to `src/`, `nix/` or `examples/`
2. Run `just check` to lint, typecheck, test and evaluate the flake
3. Commit and open a PR

## Code style

- Python: ruff (format + lint) + mypy strict
- Nix: nixpkgs-fmt
- Pre-commit hooks enforce all of the above

## PR workflow

1. Create a feature branch from `main`
2. Make changes
3. Run `pre-commit run --all-files`
4. Push and open a pull request
5. CI runs lint, typecheck, tests, nix checks, and audit
6. All checks must pass before merge

## Adding a GCP resource

1. Add a frozen model in `src/python_tofu/models/gcp.py`
2. Wire it into `GcpStack` in `models/stack.py` (including reference validation)
3. Add a block builder in `services/renderer.py`
4. Add the resource to `examples/gcp_bootstrap/infra.py` if it fits the example
5. Add unit tests for the model and rendered HCL
6. Document the fields in `docs/reference/dsl.md`

## Adding a CLI command

1. Create `src/python_tofu/cli/commands/<name>.py` with a Typer sub-app
2. Use the shared options from `cli/options.py`
3. Register it in `cli/main.py`
4. Add tests in `tests/unit/test_cli.py`
5. Document it in `docs/reference/cli.md`

## Adding a NixOS module option

1. Add the option in `nix/module.nix`
2. Update the `module-eval` check in `flake.nix` if the shape changes
3. Document it in `docs/reference/module.md`
