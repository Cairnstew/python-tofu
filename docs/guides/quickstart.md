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

## 1. Enter the development environment

```bash
nix develop
```

This builds a Nix-managed venv with all dependencies. The `python-tofu` command
is available directly.

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
pytest tests/unit -q
ruff check src tests
mypy src
nix flake check --no-build
```

## Next steps

- [CLI reference](../reference/cli.md)
- [DSL reference](../reference/dsl.md)
- [Module reference](../reference/module.md)
- [CI reference](../reference/ci.md)
