# python-tofu

A typed Python DSL and CLI wrapper for managing GCP infrastructure with
[OpenTofu](https://opentofu.org/).

Write infrastructure as validated Python objects, render deterministic HCL, and
drive `tofu init/plan/apply/destroy` through one CLI.

## Why

- **Typed by construction** — Pydantic models validate GCP identifiers, required
  fields and cross-resource references before `tofu` ever runs.
- **Cleaner than raw HCL** — reuse Python loops, helpers and constants; no
  stringly-typed `.tf` templates.
- **OpenTofu stays the engine** — the Python layer renders HCL and wraps the
  CLI; state, providers and plans remain standard OpenTofu.
- **Deterministic output** — generated files are stable and `tofu fmt` clean.
- **Hermetic builds** — the repo is a uv2nix flake; `nix build` produces a
  self-contained application.

## Credentials

On a machine with this repo's agenix secrets, `.envrc` exports the
`gcloud-auth` service-account key automatically:

- `GOOGLE_APPLICATION_CREDENTIALS=/run/agenix/gcloud-auth`
- `GOOGLE_PROJECT` / `GOOGLE_CLOUD_PROJECT` / `CLOUDSDK_CORE_PROJECT`, derived
  from the key's `project_id`
- `TF_VAR_gcp_credentials_file` and `TF_VAR_project` for Terraform-style stacks

Run `direnv allow` once after changing `.envrc`. Without the secret, the shell
still works and the standard ADC mechanisms apply.

## Quick start

The dev shell provides Python, `uv`, `pytest`, `jq` and OpenTofu:

```bash
nix develop
python-tofu --help

python-tofu render --config examples/gcp_bootstrap/infra.py --workdir .tofu/example
python-tofu plan   --config examples/gcp_bootstrap/infra.py --workdir .tofu/example
```

`plan` renders the stack, runs `tofu init`, saves `plan.tfplan`, and prints a
create/update/delete summary. `apply` does the same and applies.

## Define infrastructure

```python
# infra.py
from python_tofu import GcpProject, GcpProvider, GcpStack, StorageBucket

stack = GcpStack(
    provider=GcpProvider(project="my-project", region="europe-west1"),
    projects=[GcpProject(project_id="my-project", name="My Project")],
    buckets=[
        StorageBucket(
            project="my-project",
            name="my-project-artifacts",
            versioning=True,
        )
    ],
)
```

Then:

```bash
python-tofu plan --config infra.py --workdir .tofu
```

## CLI

| Command | Description |
|---------|-------------|
| `render` | Write `versions.tf`, `providers.tf`, `main.tf` and `.gitignore` |
| `init` | Render, then `tofu init` |
| `validate` | Render, init and `tofu validate` |
| `plan` | Render, init, `tofu plan`, print a JSON-friendly summary |
| `apply` | Render, init and apply (or apply a saved plan) |
| `destroy` | Render, init and destroy |
| `output` | Read `tofu output -json` |

Every command accepts `--config/-c`, `--workdir/-w`, `--binary` and
`--verbose/-v`. See the [CLI reference](docs/reference/cli.md).

## Development

```bash
just check      # lint + typecheck + unit tests + flake evaluation
just test       # all tests
just nix-build  # build the application
```

## Docs

- [Quickstart](docs/guides/quickstart.md)
- [CLI reference](docs/reference/cli.md)
- [DSL reference](docs/reference/dsl.md)
- [Module reference](docs/reference/module.md)
- [CI reference](docs/reference/ci.md)
- [NixOS integration](docs/guides/nixos-integration.md)
- [GCP bootstrap example](examples/gcp_bootstrap/README.md)
