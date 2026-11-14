# CI Reference

## Repository

| Fact | Value |
|------|-------|
| Remote | `https://github.com/Cairnstew/python-tofu` (public) |
| Default branch | `main` |
| Entry point | `ci.yml` — the only workflow triggered by branch pushes and pull requests |
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
derivations: `lint`, `typecheck`, `unit-tests`, `integration-tests`, `format`,
`render-example`, `render-clean-example`, `render-test-example`,
`validate-examples`, `provider-version`, `provider-version-default`,
`with-tofu-wired`, `module-eval`, `home-module-eval` and `module-vm`) followed
by `nix build .#default` — it is the slowest
job, but `nix flake check` locally is now the same gate, using the locked dev
venv rather than `uv run`.

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
| `ci-success` | always | aggregate gate — fails if any job above did not pass or skip |

Python jobs use `astral-sh/setup-uv@v5` and `uv run` on the GitHub runner.

## Branch protection (`main`)

`main` is guarded by a repository ruleset (`main protection`), not by the older
legacy branch-protection API:

| Rule | Setting |
|------|---------|
| Force pushes | blocked (`non_fast_forward`) |
| Branch deletion | blocked (`deletion`) |
| Merge commits | blocked (`required_linear_history`) — squash or rebase only |
| Pull request | required; 0 approvals (solo repo), stale reviews dismissed, all review threads resolved |
| Status checks | `ci-success` required, and the branch must be up to date with `main` before merging |

The single required context is `ci-success`, not the individual jobs. Those
jobs are path-filtered, so requiring `lint`/`nix` directly would leave a
required check unreported (and the PR unmergeable) on any change that skips
them. `ci-success` always runs and treats `skipped` as a pass, while `failure`
and `cancelled` fail it — adding a job to `ci.yml` only needs it listed under
`ci-success.needs`.

Repository admins hold an `always` bypass on the ruleset, so a direct push or an
emergency merge is still possible. The weekly `update-flake-lock.yml` PR is
opened with `GITHUB_TOKEN`, whose pushes do not trigger workflows, so that PR
reports no `ci-success` and needs an admin bypass merge (or a PAT/App token in
that workflow).

The matching repository settings are `allow_merge_commit=false`,
`allow_squash_merge=true`, `allow_rebase_merge=true` and
`delete_branch_on_merge=true`, so the UI never offers a merge method the ruleset
would reject.

Tag ruleset `release tags` blocks deleting or force-moving `v*` tags, which is
what `release.yml` publishes from. It carries the same admin bypass. Commits are
not signed, so no `required_signatures` rule is set.

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
