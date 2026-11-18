# Quickstart Guide

## Prerequisites

- Nix with flakes enabled
- GCP credentials (`gcloud auth application-default login` or
  `GOOGLE_APPLICATION_CREDENTIALS`)

OpenTofu is included in the dev shell. Outside it, install `tofu` or point
`--binary` at an OpenTofu binary.

On this machine `.envrc` exports the agenix `gcloud-auth` service-account key as
`GOOGLE_APPLICATION_CREDENTIALS` (plus the derived project variables) when the
secret is readable. Run `direnv allow` once after changing `.envrc`.

## Bootstrap an organization admin account

A fresh organization has no credential that can create projects. Create the
one-time "seed" service account before rendering any stack:

```bash
nix develop .#cloud
just bootstrap-admin my-project-id --impersonator you@example.com
```

The script signs in with a throwaway `gcloud auth login` (its own
`CLOUDSDK_CONFIG`, discarded on exit, so your normal session is untouched),
creates `org-admin@my-project-id.iam.gserviceaccount.com`, grants it the
org-level `projectCreator`, `folderAdmin`, `securityAdmin` and related roles,
grants `billing.user` on the billing account, and writes a JSON key to the
gitignored `.cache/gcp-keys/`.

Prefer `--no-key --impersonator you@example.com` when you can impersonate
instead of holding a long-lived key. When `gcloud` is not on `PATH` the script
re-executes itself in `nix develop .#cloud`; run
`./scripts/bootstrap-org-admin.sh --help` for every option.

## 1. Enter the development environment

```bash
nix develop
```

This builds a Nix-managed venv from `uv.lock` with all dependencies including
the dev tools (`pytest`, `ruff`, `mypy`), plus `tofu`, `just`, `pre-commit` and
`nixpkgs-fmt`. The `python-tofu` command is available directly. `direnv` does
the same on `cd` when it is installed.

For dependency edits use the smaller `nix develop .#bootstrap` shell; for live
`gcloud` inspection use `nix develop .#cloud`.

## 2. Inspect the CLI

```bash
python-tofu --help
python-tofu plan --help
```

## 3. Render the example stack

```bash
python-tofu render \
  --config examples/gcp_bootstrap/infra.py \
  --workdir .tofu/example
```

This writes `versions.tf`, `providers.tf`, `main.tf` and `.gitignore`. The HCL is
deterministic and `tofu fmt` clean.

## 4. Plan and apply

```bash
python-tofu plan \
  --config examples/gcp_bootstrap/infra.py \
  --workdir .tofu/example

python-tofu apply \
  --config examples/gcp_bootstrap/infra.py \
  --workdir .tofu/example
```

`plan` prints a summary such as:

```
Plan: 8 to create, 0 to update, 0 to delete.
```

Pass `--json` for a machine-readable summary.

## 5. Write your own stack

Create `infra.py` with a module-level `stack`:

```python
from python_tofu import GcpProvider, GcpStack, ServiceAccount

stack = GcpStack(
    provider=GcpProvider(project="my-project"),
    external_projects=["my-project"],
    service_accounts=[
        ServiceAccount(
            project="my-project",
            account_id="ci-runner",
            roles=["roles/storage.admin"],
        )
    ],
)
```

Run `python-tofu render --config infra.py`.

### Split a stack across files

The config directory is importable while the module loads, so a stack can be
organised one module per resource family:

```
infra/
├── stack.py           # exposes `stack`; only wires the parts together
└── parts/
    ├── __init__.py
    ├── foundation.py  # provider, project, APIs
    ├── storage.py     # buckets
    └── iam.py         # service accounts and bindings
```

`stack.py` imports each part and passes the lists to one `GcpStack`. Sibling
imports (`from parts.storage import buckets`) and relative imports
(`from .parts.storage import buckets`) both work. See
[`examples/gcp_clean/stack.py`](../../examples/gcp_clean/stack.py) for a complete
version.

## 6. Run the checks

```bash
just check          # lint + typecheck + unit/integration tests + flake eval
pytest tests/unit -q
ruff check src tests
mypy src
nix flake check     # builds lint, typecheck, tests, render and module checks
```

## Next steps

- [CLI reference](../reference/cli.md)
- [DSL reference](../reference/dsl.md)
- [Module reference](../reference/module.md)
- [CI reference](../reference/ci.md)
