# CLI Reference

## Usage

```bash
python-tofu COMMAND [OPTIONS]
python-tofu --version
```

## Shared options

Every command that loads a stack (`render`, `init`, `validate`, `doctor`, `plan`,
`apply`, `destroy`, `prune`, `limits`) accepts:

| Option | Default | Description |
|--------|---------|-------------|
| `--config`, `-c` | `infra.py` | Stack definition: a Python module exposing `stack`, a JSON file, or a `.nix` file evaluating to the schema |
| `--workdir`, `-w` | `.tofu/<stack-name>` | Directory where HCL and state are written |
| `--stack-name` | config file stem, or the stack's `name` | State name; drives the default workdir and GCS prefix |
| `--binary` | `tofu` | OpenTofu binary to invoke |
| `--verbose`, `-v` | false | Print every `tofu` command before running it |
| `--limits` | policy default (`error` for GCP) | Enforce limits: `error`, `warn` or `off` |
| `--usage` | `stack` | `stack` uses declared resources; `live` also reads existing infrastructure |
| `--fail-on-unknown` | false | Fail when a limit could not be measured (ignored with `--limits off`) |

A `.json` config is read directly; a `.nix` config is evaluated with
`nix eval --json` and then validated by the same provider models. See
[`nix-stacks.md`](nix-stacks.md) for the Nix authoring surface.

`output` reads an existing workdir and accepts `--config`, `--stack-name`,
`--workdir`, `--binary`, `--verbose` and `--json/--no-json`. It never renders.
When neither `--workdir` nor `--stack-name` is given it imports the config only
to read the stack's `name`, so `--config` selects the same default directory as
the rendering commands. If the config cannot be loaded it falls back to the
config file stem; pass `--stack-name` to avoid the import.

When `--workdir` is omitted the directory is `.tofu/<stack-name>`, where the
name is `--stack-name`, else the stack's `name`, else the config file stem.
An explicit `--workdir` is used exactly as given. `--workdir` is resolved
against the current directory. `--plan-file` and
`--var-file` are also resolved against the current directory before `tofu` runs
from inside the workdir, so relative paths mean what the shell says.

## Commands

### `render`

Render the Python stack to `versions.tf`, `providers.tf`, `main.tf` and a
`.gitignore`. Does not invoke `tofu`.

```bash
python-tofu render -c infra.py -w .tofu
python-tofu render -c infra.py --check      # exit 1 if the workdir is stale
python-tofu render -c infra.py --diff       # show what --check would change
python-tofu render -c infra.py --stdout main.tf
```

| Option | Description |
|--------|-------------|
| `--check` | Compare the rendered HCL with the workdir and exit `1` when they differ. Writes nothing. |
| `--diff` | Like `--check`, but print a unified diff for each stale file. Writes nothing. |
| `--stdout FILE` | Print one rendered file to stdout instead of writing. Writes nothing. |

`--check` and `--diff` are the CI counterpart of a hand edit: they fail when the
workdir no longer matches the Python stack, without rewriting it. A missing
workdir counts as out of date. `--check`/`--diff` cannot be combined with
`--stdout`.

### `init`

Render, then run `tofu init -input=false`.

| Option | Description |
|--------|-------------|
| `--upgrade` | Add `-upgrade` to reinstall providers |

### `validate`

Render, run `tofu init`, then `tofu validate -no-color`.

### `doctor`

Read-only preflight. Loads the config and checks, in order:

1. `tofu` resolves and its version satisfies the stack's `required_version`
2. required providers are present in the Nix mirror (`NIX_TERRAFORM_PLUGIN_DIR`)
   or cache (`TF_PLUGIN_CACHE_DIR`) when either is set; otherwise skipped, since
   `init` will download them
3. the working directory is writable or can be created
4. credentials resolve and can mint an access token
5. the provider project exists and is `ACTIVE`
6. billing is enabled
7. every API the stack declares or derives is enabled
8. the state backend is reachable (a GCS bucket read, or a local directory that
   exists or can be created)
9. no GCS state lock object is present
10. the limits summary (same measurement `plan` uses)

```bash
python-tofu doctor --config infra.py
# ✓ tofu         1.12.1 (/nix/store/…/bin/tofu)
# - providers    no mirror or cache set; tofu downloads providers during init
# ✓ workdir      .tofu/infra (creatable)
# ✓ credentials  ci-runner@demo-project.iam.gserviceaccount.com (expires in 59m)
# ✓ project      demo-project (ACTIVE)
# ✓ billing      enabled (0123AB-456CDE-789FGH)
# ✓ APIs         4 required, all ENABLED
# ✓ backend      gs://demo-state prefix python-tofu/infra
# ✓ state lock   none
# ? limits       54 limits checked; 0 exceeded, 0 warning, 53 unknown
```

Each failure prints a `fix:` line, and the command exits `1` if anything
failed. Nothing is rendered, enabled or deleted.

| Option | Description |
|--------|-------------|
| `--usage live` | Also measure existing infrastructure for the limits section |
| `--fail-on-unknown` | Exit `1` when a check (or a limit) could not be verified |
| `--limits off` | Skip the limits section |
| `--json` | Emit the checklist as JSON |

### `plan`

Render, run `tofu init` (unless `--no-init`), save `plan.tfplan`, and print a
summary derived from `tofu show -json`.

| Option | Description |
|--------|-------------|
| `--destroy` | Plan a destroy |
| `--no-init` | Skip `tofu init` |
| `--var-file PATH` | Pass a tfvars file to tofu (repeatable) |
| `--var NAME=VALUE` | Set a variable on the command line (repeatable) |
| `--json` | Print the summary as JSON |
| `--exit-code` | Exit `2` when the plan has changes, `0` when empty, `1` on error |
| `--prune` | Also list live resources the stack does not declare (preview only) |
| `--prune-section NAME` | Limit the preview to `buckets`, `subscriptions`, `topics`, `project_iam`, `service_accounts` or `apis` (repeatable) |
| `--allow-service-accounts` | Second gate for listing service accounts (also needs `include_service_accounts=True`) |

```bash
python-tofu plan -c infra.py -w .tofu --json
# {"create": 8, "update": 0, "delete": 0, "replace": 0, "no_op": 0, "other": 0, "has_changes": true}
```

`--exit-code` turns the summary into a gate, mirroring `tofu plan
-detailed-exitcode` without exposing the raw flag:

```bash
python-tofu plan -c infra.py --exit-code    # exit 2 when there is anything to do
```

Exit `2` also means "error" to CI systems that only look at non-zero; check for
the exact code when you need to distinguish "changes" from "broken".

### `apply`

Render, run `tofu init`, then `tofu apply`.

| Option | Description |
|--------|-------------|
| `--auto-approve` | Skip interactive approval (and the prune confirmation) |
| `--plan-file PATH` | Apply a previously saved plan instead of re-rendering. The default workdir still follows the stack's `name` |
| `--var-file PATH` | Pass a tfvars file to tofu (repeatable) |
| `--var NAME=VALUE` | Set a variable on the command line (repeatable) |
| `--prune` | After applying, delete live resources the stack does not declare |
| `--prune-section NAME` | Prune only `buckets`, `subscriptions`, `topics`, `project_iam`, `service_accounts` or `apis` (repeatable, implies `--prune`) |
| `--allow-service-accounts` | Second gate for pruning service accounts (also needs `include_service_accounts=True`) |

`--var`/`--var-file` cannot be combined with `--plan-file`: OpenTofu bakes the
variables into the saved plan, so the CLI rejects the combination instead of
letting `tofu` fail. Pass variables to `plan` when the plan is created.

### `destroy`

Render, run `tofu init`, then `tofu destroy`.

| Option | Description |
|--------|-------------|
| `--auto-approve` | Skip interactive approval |
| `--var-file PATH` | Pass a tfvars file to tofu (repeatable) |
| `--var NAME=VALUE` | Set a variable on the command line (repeatable) |

### `prune`

Delete live resources that the stack does not declare. Discovery uses the
service read APIs (Storage, IAM, Service Usage); deletion adopts each resource
into a scratch OpenTofu module
and runs `tofu destroy`, so it uses the provider's delete logic and leaves the
real state backend alone.

Pruning is a **dry run by default**. It only acts when the stack has
`prune=PruneConfig(enabled=True)` or a section is selected explicitly.
`enabled=True` selects every supported section. Two exceptions:

- **APIs**: the `GcpProvider.default_apis` control-plane baseline is never
  pruned; undeclared workload APIs are.
- **Service accounts**: skipped from `--all` unless the stack sets
  `prune.include_service_accounts=True` **and** the run passes
  `--allow-service-accounts`. An explicit `--section service_accounts` fails
  without both gates. This prevents pruning the identity that runs `tofu`.

```bash
python-tofu prune --config infra.py                      # list leftovers
python-tofu prune --config infra.py --apply              # delete them
python-tofu prune --config infra.py --section buckets    # one section
python-tofu prune --config infra.py --section subscriptions --section topics
python-tofu prune --config infra.py --all --apply        # every section except gated SAs
python-tofu prune --config infra.py --all --apply --allow-service-accounts  # with the SA gate
python-tofu apply --config infra.py --prune --auto-approve  # apply, then prune
```

| Option | Description |
|--------|-------------|
| `--section NAME` | Prune one section (repeatable): `buckets`, `subscriptions`, `topics`, `project_iam`, `service_accounts`, `apis` |
| `--all` | Select every supported section except service accounts and project IAM |
| `--allow-service-accounts` | Second gate for service accounts; also requires `include_service_accounts=True` |
| `--apply` | Actually delete; without it the command only lists |
| `--auto-approve` | Skip the deletion confirmation |

`plan --prune` only previews. `apply --prune` prunes after a successful apply
and always skips `project_iam` (IAM is eventually consistent); use the
standalone `prune` command for IAM. An `extra_files` stack needs
`prune.allow_raw_hcl=True` before any prune will run. It cannot be combined with
`--plan-file`; an explicit `plan --prune` (or
`--prune-section`) cannot be combined with `--destroy`. A destroy plan ignores
the stack's own `prune.enabled` setting, so `plan --destroy` works on a
prune-enabled stack without `--no-prune`.

### `output`

Run `tofu output -json` (or `--no-json` for plain output). Reads the values
declared through `GcpStack.outputs`. Requires an existing working directory.

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

### `apis`

List available, enabled or all Google APIs for a project, or resolve a short
name, through the Service Usage API. No `tofu` process runs.

```bash
python-tofu apis --project my-project --state enabled --filter storage
python-tofu apis --project my-project --state available --filter compute
python-tofu apis --project my-project --state all --json
python-tofu apis --project my-project --resolve run
python-tofu apis --config infra.py --state enabled
```

| Option | Description |
|--------|-------------|
| `--project PROJECT` | Inspect this project; skips loading `--config` |
| `--state available\|enabled\|all` | Restrict by state (default `available`) |
| `--filter TEXT` | Case-insensitive substring match on name or title |
| `--resolve NAME` | Resolve a short/full name with `services.get` and print it |
| `--quota-project PROJECT` | Send `x-goog-user-project` for user (ADC) credentials |
| `--json` | Emit JSON |

Service Usage rate-limits the available/disabled listing (often one request per
minute). `--state enabled` and `--resolve` do not use it; when the quota is
exhausted the command prints a hint. See
[`examples/gcp_apis/`](../../examples/gcp_apis/) for config usage.

### `plugins`

List the active provider, every registered command and any plugins discovered
through entry points. No `tofu` process runs and no config is loaded.

| Option | Description |
|--------|-------------|
| `--json` | Emit the report as JSON |

See the [commands and plugins reference](plugins.md).

## Exit codes

Commands exit with OpenTofu's exit code. Configuration and rendering errors exit
with `1` and print a red `Error:` line to stderr. `plan --exit-code` adds
`2` for "the plan has changes".

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

The packaged Nix app sets `PYTHON_TOFU_GOOGLE_PROVIDER_VERSION` from
`nix/provider-versions.nix`, which is what a stack's default
`google_provider_version` uses. Set it yourself to pin the rendered constraint
outside Nix; an explicit `GcpStack(google_provider_version=...)` always wins.

`PYTHON_TOFU_BINARY` is the environment form of `--binary`. The Nix
`with-tofu` package sets it to the bundled OpenTofu (which carries the provider
mirror), so `nix run .#with-tofu -- plan` needs nothing else on `PATH`.
