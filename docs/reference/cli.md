# CLI Reference

## Usage

```bash
python-tofu COMMAND [OPTIONS]
python-tofu --version
```

## Shared options

Every command that loads a stack (`render`, `init`, `validate`, `plan`, `apply`,
`destroy`) accepts:

| Option | Default | Description |
|--------|---------|-------------|
| `--config`, `-c` | `infra.py` | Python module exposing a module-level `stack` |
| `--workdir`, `-w` | `.tofu` | Directory where HCL and state are written |
| `--binary` | `tofu` | OpenTofu binary to invoke |
| `--verbose`, `-v` | false | Print every `tofu` command before running it |
| `--limits` | policy default (`error` for GCP) | Enforce limits: `error`, `warn` or `off` |
| `--usage` | `stack` | `stack` uses declared resources; `live` also reads existing infrastructure |
| `--fail-on-unknown` | false | Fail when a limit could not be measured (ignored with `--limits off`) |

`output` reads an existing workdir and accepts only `--workdir`, `--binary`,
`--verbose` and `--json/--no-json` (there is no `--config`, because it does not
render).

`--workdir` is resolved against the current directory. `--plan-file` and
`--var-file` are also resolved against the current directory before `tofu` runs
from inside the workdir, so relative paths mean what the shell says.

## Commands

### `render`

Render the Python stack to `versions.tf`, `providers.tf`, `main.tf` and a
`.gitignore`. Does not invoke `tofu`.

```bash
python-tofu render -c infra.py -w .tofu
```

### `init`

Render, then run `tofu init -input=false`.

| Option | Description |
|--------|-------------|
| `--upgrade` | Add `-upgrade` to reinstall providers |

### `validate`

Render, run `tofu init`, then `tofu validate -no-color`.

### `plan`

Render, run `tofu init` (unless `--no-init`), save `plan.tfplan`, and print a
summary derived from `tofu show -json`.

| Option | Description |
|--------|-------------|
| `--destroy` | Plan a destroy |
| `--no-init` | Skip `tofu init` |
| `--var-file PATH` | Pass an extra tfvars file |
| `--json` | Print the summary as JSON |

```bash
python-tofu plan -c infra.py -w .tofu --json
# {"create": 8, "update": 0, "delete": 0, "replace": 0, "no_op": 0, "other": 0, "has_changes": true}
```

### `apply`

Render, run `tofu init`, then `tofu apply`.

| Option | Description |
|--------|-------------|
| `--auto-approve` | Skip interactive approval |
| `--plan-file PATH` | Apply a previously saved plan instead of re-rendering |
| `--var-file PATH` | Pass an extra tfvars file |

### `destroy`

Render, run `tofu init`, then `tofu destroy`.

| Option | Description |
|--------|-------------|
| `--auto-approve` | Skip interactive approval |
| `--var-file PATH` | Pass an extra tfvars file |

### `output`

Run `tofu output -json` (or `--no-json` for plain output). Requires an existing
working directory.

| Option | Description |
|--------|-------------|
| `--json` / `--no-json` | Emit machine-readable JSON (default) or plain output |

### `limits`

Load the stack and print the provider's limit policy with measured usage. No
`tofu` process runs.

| Option | Description |
|--------|-------------|
| `--usage` | `stack` (default) or `live` (measure existing infrastructure) |
| `--fail-on-unknown` | Exit 1 if any limit could not be measured |
| `--all` | Include unused and unknown limits |
| `--json` | Emit the full report as JSON |

```bash
python-tofu limits --config infra.py --all
# GCP limits: 54 limits checked; 1 exceeded, 1 warning, 50 unknown
# ! gcp.storage.standard_gb: 9/5 GB (180.0%)
# ? gcp.bigquery.query_tib: unknown/1 TiB
```

`unknown` means "not measured", not zero — see the
[limits reference](limits.md#unknown-is-not-zero). `--usage live` uses Cloud
Asset Inventory to include manually created and pre-existing resources.

### `plugins`

List the active provider, every registered command and any plugins discovered
through entry points. No `tofu` process runs and no config is loaded.

| Option | Description |
|--------|-------------|
| `--json` | Emit the report as JSON |

See the [commands and plugins reference](plugins.md).

## Exit codes

Commands exit with OpenTofu's exit code. Configuration and rendering errors exit
with `1` and print a red `Error:` line to stderr.

## Environment

The wrapper inherits the full environment. GCP authentication is therefore the
standard one:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
# or
gcloud auth application-default login
```

In this repo, `.envrc` points `GOOGLE_APPLICATION_CREDENTIALS` at the agenix
`gcloud-auth` secret (`/run/agenix/gcloud-auth`) when it is readable, and derives
`GOOGLE_PROJECT` / `GOOGLE_CLOUD_PROJECT` / `CLOUDSDK_CORE_PROJECT` plus the
`TF_VAR_*` equivalents from the key. Run `direnv allow` after editing `.envrc`.

Set `PYTHON_TOFU_NO_PLUGINS=1` to skip entry-point discovery at startup (useful
for a deterministic environment or when plugins are not trusted).
