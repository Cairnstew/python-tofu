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
other branch does not start CI; open a pull request instead. The
`test-integration`, `nix` and `audit` jobs are gated by `dorny/paths-filter`, so
a docs-only change runs nothing.

`nix.yml` runs the full `nix flake check` (which builds the `checks.*`
derivations, including `format`, `render-example` and `render-clean-example`)
followed by `nix build .#default` — it is the slowest job and the one that
catches a renderer regression.

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
| `test-integration` | Python changes | `pytest tests/integration` |
| `nix` | Nix changes | `nix flake check` + `nix build` |
| `audit` | Python changes | `pip-audit` + `bandit` |

Python jobs use `astral-sh/setup-uv@v5` and `uv run` on the GitHub runner.

### `release.yml` (tag push `v*`)

1. Detect whether the project exposes `[project.scripts]`
2. Build via Nix
3. Publish to PyPI via OIDC trusted publishing
4. Create a GitHub release

### `update-flake-lock.yml` (weekly)

Runs the update action and opens a PR labelled `automated`.
