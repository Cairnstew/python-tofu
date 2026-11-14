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

1. Add a frozen model in `src/python_tofu/providers/gcp/models.py`
2. Wire it into `GcpStack` in `src/python_tofu/providers/gcp/stack.py`
   (including any cross-reference validation)
3. Add a block builder in `src/python_tofu/providers/gcp/renderer.py`
4. Declare the APIs it needs and the `depends_on` ordering in
   `src/python_tofu/providers/gcp/apis.py`
5. Put identifier/naming rules in `src/python_tofu/providers/gcp/quirks.py`
6. Add the resource to an example if it fits
7. Add unit tests for the model and rendered HCL
8. Document the fields in `docs/reference/dsl.md` and add a `CHANGELOG.md` entry

`src/python_tofu/models/`, `services/`, `hcl.py` and `loader.py` are
compatibility shims; do not add new code there (see `GOTCHAS.md`).

## Adding a CLI command

1. Create `src/python_tofu/core/cli/commands/<name>.py` exporting
   `create_app(provider) -> typer.Typer`
2. Use the shared options from `src/python_tofu/core/cli/options.py`
3. Register it in `_BUILTINS` in
   `src/python_tofu/core/cli/commands/__init__.py` (or decorate the factory with
   `register_command`)
4. Put provider-specific commands under `src/python_tofu/providers/<name>/cli/`
5. Add tests under `tests/unit/`
6. Document it in `docs/reference/cli.md`

## Adding a NixOS module option

1. Add the option in `nix/module.nix`
2. Update the `module-eval` check in `flake.nix` if the shape changes
3. Document it in `docs/reference/module.md`
