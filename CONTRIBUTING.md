# Contributing

## Prerequisites

- Nix with flakes enabled — everything else comes from the dev shell.
- [`direnv`](https://direnv.net/) with `nix-direnv` is optional but recommended;
  `.envrc` runs `use flake` and exports the agenix GCP credentials when present.

## Quick start

```bash
nix develop     # Python 3.12, locked venv, tofu, just, pre-commit, ruff, mypy
just check      # lint + typecheck + tests + nix flake check
```

Entering the shell installs the pre-commit hook on first use and sets
`TOFU_PLUGIN_CACHE_DIR` to `.cache/tofu/plugins`.

| Shell | Contents | Use for |
|---|---|---|
| `nix develop` (default / `.#dev`) | Locked dev venv, `uv`, `tofu`, `just`, `pre-commit`, `nixpkgs-fmt`, `gh`, `jq` | Day-to-day work and every `just` recipe |
| `nix develop .#bootstrap` | Python 3.12 + `uv` only | `uv add`, `uv lock`, `uv lock --upgrade` |
| `nix develop .#cloud` | Dev shell plus `google-cloud-sdk` | Inspecting live GCP resources with `gcloud` |

## Development loop

1. `nix develop` (direnv does this automatically)
2. Make changes to `src/`, `nix/` or `examples/`
3. `just fmt` to apply ruff and `nix fmt`
4. `just check` to lint, typecheck, test and evaluate the flake
5. `just pre-commit` for the full hook set, then commit and open a PR

`nix flake check` builds every gate CI runs separately (`lint`, `typecheck`,
`unit-tests`, `integration-tests`, `format`, the render checks and both module
evaluations). `just nix-check` evaluates without building; `just
nix-check-build` builds them all.

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
