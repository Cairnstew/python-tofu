# python-tofu

[![CI](https://github.com/Cairnstew/python-tofu/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Cairnstew/python-tofu/actions/workflows/ci.yml)

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
python-tofu plan --config infra.py        # state + HCL in .tofu/infra
```

### Bucket contents

Objects are declared alongside the bucket and can carry any text, raw bytes, a
local file, or an HTTP(S) URL:

```python
from python_tofu import BucketObject

stack = GcpStack(
    provider=GcpProvider(project="my-project"),
    buckets=[StorageBucket(project="my-project", name="my-project-artifacts")],
    bucket_objects=[
        BucketObject(
            bucket="my-project-artifacts",
            name="config/release.json",
            content='{"release": "v1"}',
        ),
    ],
)
```

OpenTofu only re-uploads an object when its content or source file changes.
`StorageBucket(versioning=True)` keeps previous generations. See the
[DSL reference](docs/reference/dsl.md#bucketobject). Resources the DSL does not
model can be added as raw `.tf` files through `GcpStack.extra_files` — see the
[BigLake example](examples/gcp_biglake/) and the
[Cloud Run example](examples/gcp_cloud_run/) (prebuilt image vs. function
source zip).

### Enabling APIs

Declare APIs by short name and validate them against the project's Service
Usage catalog:

```python
from python_tofu import GcpProvider, GcpStack
from python_tofu.providers.gcp.services import ServiceCatalog

PROJECT = "my-project"
provider = GcpProvider(project=PROJECT)
catalog = ServiceCatalog(PROJECT, credentials=provider.credentials)

stack = GcpStack(
    provider=provider,
    apis=catalog.enable("compute", "run", "storage", "iam"),
)
```

`catalog.enable(...)` resolves each name with `services.get` (no rate-limited
listing), deduplicates, and fails with suggestions on a typo. Inspect the live
catalog with `python-tofu apis --project my-project --state available --filter
compute`. See [`examples/gcp_apis/`](examples/gcp_apis/) for the full pattern.

### Cloud Run

Both Cloud Run deployment paths are typed, with hardened defaults (internal
ingress, private invoker, deletion protection, capped scaling):

```python
from python_tofu import CloudRunFunction, CloudRunService

services = [
    CloudRunService(
        project="my-project",
        name="api",
        image="us-docker.pkg.dev/my-project/repo/api@sha256:...",
        service_account="api-runtime",
    )
]
functions = [
    CloudRunFunction(
        project="my-project",
        name="hello",
        runtime="python312",
        entry_point="hello_http",
        source_bucket="functions-src",   # declared bucket
        source_object="hello.zip",       # uploaded via BucketObject
    )
]
```

Cloud Run services take an image reference; build and push in CI. 2nd-gen
functions take a source zip, which `BucketObject` uploads (see
[the example](examples/gcp_cloud_run/)). Set
`allow_unauthenticated=True, ingress="all"` explicitly to expose a service.
`CloudRunJob` covers batch runners, `CloudRunWorkerPool` covers pull-based
background workers, `PubSubTopic`/`PubSubSubscription` wire queues and push
targets, and `ArtifactRegistryRepository` hosts the custom images. The APIs
those resources need are enabled and ordered automatically.

## CLI

| Command | Description |
|---------|-------------|
| `render` | Write `versions.tf`, `providers.tf`, `main.tf` and `.gitignore` |
| `init` | Render, then `tofu init` |
| `validate` | Render, init and `tofu validate` |
| `doctor` | Read-only preflight: credentials, project, billing, APIs, backend |
| `plan` | Render, init, `tofu plan`, print a JSON-friendly summary |
| `apply` | Render, init and apply (or apply a saved plan) |
| `destroy` | Render, init and destroy |
| `prune` | Delete live resources the stack does not declare (dry run by default) |
| `output` | Read `tofu output -json` |
| `limits` | Show provider limits and measured usage |
| `apis` | List/resolve Google APIs via Service Usage |
| `plugins` | Show commands, providers and discovered plugins |

Every command that loads a stack accepts `--config/-c`, `--stack-name`,
`--workdir/-w`, `--binary` and `--verbose/-v`; `output` reads an existing
workdir and derives the same default directory from `--config`/`--stack-name`. Run `python-tofu --version` to print the
installed version. See the [CLI reference](docs/reference/cli.md).

## Free-tier guardrails

Every command that loads a stack checks the provider's limit policy before
rendering or running `tofu`:

```bash
python-tofu render --config infra.py            # blocks on a violation (default)
python-tofu plan   --config infra.py --limits warn
python-tofu apply  --config infra.py --limits off
python-tofu limits --config infra.py            # usage report
python-tofu limits --config infra.py --usage live   # include existing infra
```

The GCP policy encodes the Google Cloud always-free tier (per billing account).
`measure_usage` covers declared stack resources plus explicit
`GcpStack.usage_estimates`; `--usage live` adds read-only Cloud Asset Inventory
so manually created and pre-existing resources count too. Unmeasured limits are
reported as `unknown` (never as zero); `--fail-on-unknown` makes them fatal.
Per-area limits and a normalised `gcp.free_tier.total` aggregate are supported.
See the [limits reference](docs/reference/limits.md).

## Pruning undeclared infrastructure

Pruning is **off by default**. Enable it per stack to make selected sections
authoritative — anything that exists in the cloud but is not declared is deleted:

```python
from python_tofu import GcpStack, PruneConfig

stack = GcpStack(
    ...,
    prune=PruneConfig(enabled=True, sections=("buckets", "subscriptions", "topics",
                                       "service_accounts", "apis")),
)
```

Then preview and run:

```bash
python-tofu prune --config infra.py            # dry run: list what would be deleted
python-tofu prune --config infra.py --apply    # delete it
python-tofu apply --config infra.py --prune    # apply, then prune leftovers
```

`prune` discovers live resources with the service read APIs (Storage, IAM,
Service Usage) and deletes them
through a throw-away OpenTofu root module, so deletes use the provider's own
logic and never touch the stack's state backend. Supported sections are
`buckets`, `subscriptions`, `topics`, `service_accounts` and `apis`; bucket deletion force-destroys
objects. Google-managed service accounts and essential APIs are never pruned.
Bucket objects cannot be imported by the provider, and project IAM bindings are
excluded because an authoritative IAM sweep can remove human access.

## Providers

The package is split into a provider-agnostic engine and per-provider branches:

| Layer | Contents |
|-------|----------|
| `python_tofu.core` | HCL writer, loader, runner, `BaseStack`, `BaseRenderer`, `Provider` contract, CLI factory |
| `python_tofu.providers.gcp` | GCP models, `GcpStack`, identifier quirks, `GcpRenderer`, registered `GCP` plugin |

GCP is the default: the top-level names (`GcpStack`, `BackendConfig`,
`Renderer`, `load_stack`) are aliases for the GCP branch. To add a provider,
subclass `BaseStack` and `BaseRenderer`, register a `Provider`, and bind a CLI
with `core.cli.app.build_app(PROVIDER, version=...)`. See
[STRUCTURE.md](STRUCTURE.md#adding-a-provider).

## Repository

Source: [github.com/Cairnstew/python-tofu](https://github.com/Cairnstew/python-tofu)
— public, default branch `main`.

- Pushes to `main` and every pull request run `ci.yml`, which fans out to the
  reusable `lint`, `typecheck`, `test-unit`, `test-integration`, `nix` and
  `audit` workflows through `dorny/paths-filter@v3`.
- Tags matching `v*` run `release.yml`: Nix build, PyPI publish via OIDC
  trusted publishing, and a GitHub release.
- `update-flake-lock.yml` runs weekly and opens an `automated` PR.
- No repository secrets are required — every workflow uses `GITHUB_TOKEN` or
  OIDC. The PyPI publish step needs a trusted publisher configured for this
  repository before the first `v*` tag.

See the [CI reference](docs/reference/ci.md) for the per-workflow job table.

## Development

```bash
just check      # lint + typecheck + unit tests + flake evaluation
just test       # all tests
just nix-build  # build the application
```

## Docs

- [Quickstart](docs/guides/quickstart.md)
- [CLI reference](docs/reference/cli.md)
- [Commands and plugins](docs/reference/plugins.md)
- [Limits reference](docs/reference/limits.md)
- [DSL reference](docs/reference/dsl.md)
- [Module reference](docs/reference/module.md)
- [CI reference](docs/reference/ci.md)
- [NixOS integration](docs/guides/nixos-integration.md)
- [GCP bootstrap example](examples/gcp_bootstrap/README.md)
