# CI Reference

## Repository

| Fact | Value |
|------|-------|
| Remote | `https://github.com/Cairnstew/python-tofu` (public) |
| Default branch | `main` |
| Entry point | `ci.yml` — the only workflow with a `push`/`pull_request` trigger |
| Reusable workflows | `lint`, `typecheck`, `test-unit`, `test-integration`, `nix`, `audit` (`workflow_call` only) |
| Required secrets | none — `GITHUB_TOKEN` and OIDC only |

`ci.yml` filters on `push` to `main` and on every pull request. A push to any
other branch does not start CI; open a pull request instead. `dorny/paths-filter`
gates every job: `lint`, `typecheck`, `test-unit`, `test-integration` and
`audit` on Python changes, and `nix` on Nix, package or example changes. A
docs-only change therefore runs only the `changes` job.

The `nix` job is gated on `**.nix`, `flake.lock`, `src/**`, `examples/**`,
`pyproject.toml` and `uv.lock`. It builds the package and renders every example,
so a Python-only change can break it; before `src/**` was added it ran only on
`.nix` changes and a renderer regression passed CI unnoticed.

Both filters also match `.github/workflows/**`, so a workflow edit runs the
jobs it changes instead of passing with only the `changes` job.

`nix.yml` runs the full `nix flake check` (which builds the `checks.*`
derivations, including `format`, `render-example`, `render-clean-example`,
`module-eval` and `home-module-eval`) followed by `nix build .#default` — it is
the slowest job and the one that catches a renderer or module regression.

Before tagging the first release, configure a PyPI trusted publisher for this
repository (workflow `release.yml`, environment `release`); otherwise the
publish step fails. GitHub releases do not depend on it.

## Pipeline overview

CI uses `dorny/paths-filter@v3` to detect which areas changed, then conditionally
calls reusable workflows.

## Workflows

### `ci.yml` (orchestrator)

| Job | Trigger | Runs on |
|-----|---------|---------|
| `lint` | Python changes | `ruff format --check` + `ruff check` |
| `typecheck` | Python changes | `mypy src/` |
| `test-unit` | Python changes | `pytest tests/unit --cov` |
| `test-integration` | Python changes | `pytest tests/integration` (gating) |
| `nix` | Nix/package/example changes | `nix flake check` + `nix build` |
| `audit` | Python changes | `pip-audit` + `bandit` |

Python jobs use `astral-sh/setup-uv@v5` and `uv run` on the GitHub runner.

### `release.yml` (tag push `v*`, or manual dispatch)

1. Detect whether the project exposes `[project.scripts]`
2. Build via Nix and smoke-test the wrapper
3. Build the wheel and sdist
4. Publish to PyPI via OIDC trusted publishing (tag pushes only)
5. Create a GitHub release with the wheel and sdist (tag pushes only)

`workflow_dispatch` is a dry run: it runs steps 1–3 and uploads the `dist`
artifact, but skips both publish steps.

### `update-flake-lock.yml` (weekly)

Runs the update action and opens a PR labelled `automated`.
