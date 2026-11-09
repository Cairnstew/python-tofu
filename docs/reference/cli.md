# CLI Reference

## Usage

```bash
python-tofu COMMAND [OPTIONS]
```

## Shared options

Every command accepts:

| Option | Default | Description |
|--------|---------|-------------|
| `--config`, `-c` | `infra.py` | Python module exposing a module-level `stack` |
| `--workdir`, `-w` | `.tofu` | Directory where HCL and state are written |
| `--binary` | `tofu` | OpenTofu binary to invoke |
| `--verbose`, `-v` | false | Print every `tofu` command before running it |

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
