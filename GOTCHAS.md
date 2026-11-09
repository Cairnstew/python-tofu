# Gotchas

## uv2nix

### uv.lock required for evaluation
The flake won't evaluate without a `uv.lock`. Use `nix develop .#bootstrap` to get Python + uv, then run `uv lock`.

### uv.lock doesn't contain build systems
uv doesn't lock build systems. uv2nix uses `pyproject-build-systems` overlay to supply them.
If a build system isn't in that repo, you must supply it via an overlay.

### Hatchling editable builds need `editables`
Hatchling's editable wheel builder imports `editables`, which nixpkgs does not
propagate. `flake.nix` adds it via `buildSystemOverrides`. If you change the build
backend, update that override.

### Don't use `uv run` inside the dev shell
`uv run` creates its own venv, defeating uv2nix's provisioning. The dev shell already makes all
scripts/entry points available directly. `uv run` is fine on GitHub runners.

### Don't filter sources at workspace root
`uv2nix.lib.workspace.loadWorkspace` reads from the workspace root at evaluation time. Filtering
there causes IFD and breaks editables. Filter per-package instead.

### Editable packages need `$REPO_ROOT`
The editable overlay uses `$REPO_ROOT` to locate the source tree. The dev shell `shellHook` sets it
via `git rev-parse --show-toplevel`. If you're not in a git repo, set it manually.

### `unset PYTHONPATH`
Nixpkgs Python builders set `PYTHONPATH`, which leaks into unrelated builds. Always unset it in the
dev shell `shellHook`.

## Python / HCL

### Hatchling build backend
This project uses `hatchling`, not `setuptools`. The `build-system.requires` must be `["hatchling"]`
and the build backend `hatchling.build`.

### HCL alignment
`hcl.py` pads attribute names so generated files pass `tofu fmt -check`. If you add
a new block shape, keep the alignment logic — do not hand-format output.

### Strings and interpolation
The writer quotes strings with `json.dumps`. `${...}` interpolation is preserved,
so service-account emails use `serviceAccount:${google_service_account.x.email}`.

### Raw expressions
Use `hcl.Raw` for bare HCL references. A plain string is always quoted.

### Frozen Pydantic models
`TofuModel` uses `extra="forbid"` and `frozen=True`. Tests build variants with
`model_copy(update=...)`; this bypasses validation intentionally.

### Config modules execute
`loader.load_stack` imports the config file, so it can run arbitrary Python.
Only load trusted infrastructure modules.

### Cross-project references
Every resource `project` must be declared, equal to `provider.project`, or listed
in `external_projects`. This catches typos before `tofu` runs.

## OpenTofu / GCP

### Local state is the default trap
`BackendConfig` defaults to `gcs`, but the example uses local state. Never commit
`*.tfstate` or `plan.tfplan`; the renderer writes a `.gitignore` in the workdir.

### `tofu show -json` needs a saved plan
`python-tofu plan` writes `plan.tfplan` before calling `tofu show -json`. Deleting
the plan file breaks summary parsing; the CLI then prints a warning and keeps the
plan output.

### agenix GCP credentials
`/run/agenix/gcloud-auth` is the agenix-managed service-account JSON (owner
`seanc:0400`, project `nixos-infra-496517`). `.envrc` exports
`GOOGLE_APPLICATION_CREDENTIALS`, `TF_VAR_gcp_credentials_file`,
`GOOGLE_PROJECT`, `GOOGLE_CLOUD_PROJECT`, `CLOUDSDK_CORE_PROJECT` and
`TF_VAR_project` when the file is readable. Run `direnv allow` after editing
`.envrc`; without the secret the shell still evaluates.

Verify the current billing/API state before creating projects or buckets: the
`nixos-infra-496517` billing account has previously been closed, which makes
reads work but project/bucket creation fail with `403`.

### GCP project creation permissions
Creating `google_project` needs organization/folder permissions and usually a
billing account. For existing projects, remove `GcpProject` and use
`external_projects` instead.

### API enablement ordering
`google_project_service` resources may need to exist before dependent resources.
OpenTofu generally infers this from references; add explicit `depends_on` only if
you see ordering errors.

## Nix

### `module-eval` is evaluated in the flake
The check uses `lib.evalModules` at evaluation time with a stub
`systemd.services` option, so it does not need a sandboxed `nix-instantiate`.
Do not switch it back to a `runCommand` with `nix-instantiate`; the sandbox
cannot create `/nix/var/nix/profiles`.

### `builtins.currentSystem` in pure eval
`builtins.currentSystem` is not available in pure evaluation contexts. Use hardcoded system strings
for VM tests or guard with explicit platform detection.

### Python version mismatch
`flake.nix` uses `pkgs.python312`. `pyproject.toml` says `requires-python = ">=3.12"`. Keep these
in sync.

### nixpkgs-fmt
`checks.format` runs `nixpkgs-fmt --check` over the repo. Run
`nix run nixpkgs#nixpkgs-fmt -- flake.nix nix/*.nix` after editing Nix files.

## CI / GitHub Actions

### Reusable workflow inputs
All reusable workflows must use `workflow_call` trigger with explicit `inputs:` and `secrets: inherit`.
Omission causes silent failures or missing permissions.

### OIDC PyPI publishing
Trusted publisher must be configured on PyPI BEFORE the first release tag.
Without it, the publish step silently skips.

### `dorny/paths-filter@v3`
Use v3, not v2. v2 has broken `changes-file` output on newer runner images.

### Flake lock drift
After changing flake inputs, run `nix flake lock` to update `flake.lock`. Otherwise you'll silently
use the old pinned versions.
