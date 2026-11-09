# CI Reference

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
