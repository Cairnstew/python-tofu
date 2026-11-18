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

## Provider layout

### Core must not import providers
`python_tofu.core` is deliberately provider-blind. If core imports
`python_tofu.providers.*`, adding or swapping a provider creates an import cycle
and breaks the plugin seam. Provider-specific rules belong in
`providers/<name>/`; core only uses the `Provider` dataclass.

### Top-level modules are shims
`python_tofu/models/`, `python_tofu/services/`, `python_tofu/hcl.py`,
`python_tofu/loader.py` and `python_tofu/exceptions.py` re-export core/GCP
symbols for compatibility. Add real code to `core/` or `providers/gcp/`, not to
a shim, or the two layouts drift.

### CLI commands are provider factories
Each command exposes `create_app(provider)`; there is no module-level command
`app` anymore. The GCP binding lives in `python_tofu/cli/main.py`
(`build_app(GCP, version=__version__)`). Keep command implementations free of
GCP imports.

## Limits

### Free-tier figures change
Limits are copied from https://cloud.google.com/free/docs/free-cloud-features
into `providers/gcp/limits.py`. Google changes them with 30 days' notice; re-read
the page before relying on a number, and update the policy and its test together.

### Free tier is per billing account
Most GCP free-tier limits apply per billing account, not per project. A stack
usually describes one project, so `usage_estimates` must cover the whole billing
account for an accurate check. Firestore and Logging are per project.

### Limits are estimates, not metering
The policy checks what the stack declares (`estimated_size_gb`, `usage_estimates`)
and, with `--usage live`, what Cloud Asset Inventory reports. Neither sees data
growth, object traffic or per-request usage. It is a pre-flight guardrail; use
Cloud Billing budgets for a financial backstop.

### Cloud Asset Inventory: POST 404s, use GET
`searchAllResources` returns an HTML 404 on `POST` against this API version even
though the API is enabled; the same call as `GET` with query parameters returns
200. `assets.list` (`contentType=RESOURCE`) is also GET and is what
`providers/gcp/live.py` uses for resource fields.

### Inventory has no byte sizes
Cloud Asset Inventory returns bucket/disk metadata but no bucket size, object
count, BigQuery bytes or egress. Those limits stay `unknown` under
`--usage live`; they need Cloud Monitoring or a Billing BigQuery export. Never
map "not in inventory" to `0` — that is the silent-pass bug `unknown` prevents.

### Live checks are project-scoped; free tier is billing-account-scoped
`live_measure_usage` lists assets in the stack's project. Other projects under
the same billing account are invisible, so live numbers are a lower bound. Free
tier is per billing account (Firestore and Logging excepted).

### Bucket objects and binary/URL limits
`BucketObject.content` is `str` or `bytes`. Text becomes a `content = "..."`
attribute; bytes are written to `<workdir>/.objects/<sha>.bin` and referenced by
`source`, because HCL string literals cannot carry arbitrary bytes. `source_url`
uses `data "http"`, whose `response_body` is text — download binary URLs first.
Relative `source` paths resolve against the process working directory at render
time, not the config file's directory.

### Object idempotency comes from Terraform state
Applying an unchanged `BucketObject` is a no-op because OpenTofu compares
`content`/the file hash with state. It is not content-addressed by the wrapper;
deleting the workdir or state will cause a re-upload.

### Objects must depend on the bucket they target
A declared bucket is rendered as `bucket = google_storage_bucket.bucket_<name>.name`
so the object waits for creation. Emitting a literal bucket name lets OpenTofu
start the object in parallel, which was observed live as
`404: The specified bucket does not exist`. Literal names are only correct for
`external_buckets`.


### Aggregates are normalised, not summed units
An `AggregateLimit` adds `used / amount` ratios, not raw GB or requests. Two
limits at 60% each produce `1.2`, which exceeds the default `amount=1.0`.

## Service Usage

### Listing available APIs is quota-capped
`services.list` with `state:DISABLED` (what `gcloud services list --available`
uses) is limited to roughly one request per minute per project. A second call
inside that window returns `429` for the "List available/disabled services
requests" metric. `state:ENABLED` and `services.get` are not affected. The
catalog reports a 429 with a hint; do not retry in a tight loop, and do not
assume pagination is free — a second page can hit the same quota.

### Resolve names with services.get, not the listing
`ServiceCatalog.resolve`/`enable` call `GET /v1/projects/{p}/services/{name}`
first. That endpoint returns both enabled and disabled services and costs no
listing quota, so `enable("run")` works even when `available()` is throttled.
Only partial/fuzzy names and `available()`/`all()` fall back to the listing.

### User credentials need x-goog-user-project
With ADC (a human account) Service Usage can reject a project-scoped call
without `x-goog-user-project`. Pass `--quota-project` on `python-tofu apis`, or
`ServiceCatalog(..., quota_project=...)`. Service-account keys normally do not
need it.

### `services.get` returns 404 for unknown APIs
`get_service` treats HTTP 404 as "not found" and returns `None`; other statuses
(403, 429, 5xx) propagate as `GoogleApiError`. Do not turn 403 into "unknown" —
that hides a permissions problem.

## API enablement

### Cloud Billing and Billing Budgets are different services
`google_billing_budget` calls `billingbudgets.googleapis.com`, not
`cloudbilling.googleapis.com`. Cloud Billing is the billing-account metadata API
used by `google_project` when `billing_account` is set and by `python-tofu
doctor`; enabling one does not enable the other. A budget is billing-account
scoped, but the Budgets API is enabled per project, so `apis_for` derives it on
the provider project.

### Derived APIs follow typed fields, not raw HCL
`apis.py` only sees the typed models. A field that reaches another service (a
`SecretEnv`, a Cloud SQL or GCS volume, a Pub/Sub IAM member that resolves the
project number) needs a matching branch in `apis_for`; otherwise the first apply
fails with a 403 even though the resource is declared. Raw resources added with
`extra_files` never derive APIs — add `depends_on` by hand (see the BigLake
example).

## IAM and identities

### Provider credentials are fixed before resources exist
OpenTofu configures `provider "google"` before it creates anything, and the
renderer emits one static provider block. A service account (or key) created
during an `apply` cannot be the identity for other resources in that same
`apply`. Split it: phase 1 creates projects/accounts/delegation grants as the
provisioning identity; phase 2 runs as the new project identity through
`impersonate_service_account`. See `examples/org_projects/`.

### Service-account local names omit the project
The HCL labels are `sa_<account_id>` and `iam_<role>_<member>`, so two projects
in one stack cannot both declare an account called `runtime` (or grant the same
role to the same principal in two projects): the renderer raises
`duplicate resource address`. One project per stack, or project-qualified
`account_id` values. Do not add the project to the default label: that rewrites
existing state addresses.

### Impersonation applies to read-only calls too
`GcpProvider.impersonate_service_account` is used by the provider block and by
the wrapper's `doctor`, `limits --usage live`, `prune` and `ServiceCatalog`
calls (`live.access_token_for`). The source identity therefore needs
`roles/iam.serviceAccountTokenCreator` **on the target account** before phase 2
runs — grant it with `ServiceAccountIamMember`, not a project-level role.

### Keys created by tofu live in state
There is no key model on purpose. If you add `google_service_account_key` via
`extra_files`, its `private_key` is stored in OpenTofu state (cleartext unless
state encryption or a restricted GCS backend is in place). Prefer
impersonation; encrypt any key you do materialise into the gitignored
`.cache/gcp-keys/`.

### Prune cannot see extra_files
Discovery only compares the typed stack, so a bucket/topic/API declared only in
`extra_files` looks undeclared and would be deleted. `GcpStack` rejects
`prune.enabled` with `extra_files`, and `discover` refuses the CLI `--prune`
path too. Set `PruneConfig(allow_raw_hcl=True)` only when you accept that raw
HCL resources are not protected.

### project_iam is managed-principal-only and never automatic
`project_iam` prunes only `google_project_iam_member` bindings whose member is a
`serviceAccount:` declared in the stack. It reports and skips `user:`, `group:`,
`domain:`, `allUsers`, `allAuthenticatedUsers`, conditional bindings,
`roles/owner`, the active credential and any service account the stack does not
declare. It is never implied by `all`; name it explicitly. `apply --prune`
always drops the section (IAM is eventually consistent); use the standalone
`python-tofu prune` command.

### The active credential is always protected
`prune` reads `client_email` from `provider.credentials` /
`GOOGLE_APPLICATION_CREDENTIALS` and adds the `impersonate_service_account`
target, then skips those identities regardless of `include_service_accounts`
and `--allow-service-accounts`. `protected_service_accounts` adds ids/emails.
Do not remove this guard: the admin key is the identity running the prune.

## Pruning

### Pruning is opt-in and irreversible
`PruneConfig` defaults to `enabled=False`. When enabled, `sections` defaults to
`("all",)`, so anything the stack does not declare is deleted. Buckets are
adopted with `force_destroy=True`, so pruning a bucket deletes every object in
it. Do not enable a section you cannot recreate.

### Service accounts are a two-key gate
Deleting the identity that runs `tofu` is irreversible, so `service_accounts`
is excluded from `--all` and from the stack's `enabled=True` unless **both**
`PruneConfig.include_service_accounts=True` and the CLI's
`--allow-service-accounts` are set. `--section service_accounts` without both
aborts instead of silently skipping. Do not collapse this into one flag.

### APIs use a default baseline
`GcpProvider.default_apis` (from `providers/gcp/service_names.py`) is enabled
on every owned project and never pruned. Undeclared workload APIs are pruned;
add `compute`, `run` or similar to `default_apis`/`apis` if other infrastructure
still needs them. Do not protect every API: the point is to make the stack the
source of truth for the project's API state.

### Project pruning is explicit-only and always protects the credential project
`projects` is never implied by `all`, exactly like `project_iam`: deleting a
project takes every resource in it with it. The sweep resolves the organization
from the provider project's ancestry and walks folders downward, so projects in
another organization are never listed. The organization itself is not a
candidate; the provider project, declared and `external_projects` projects,
`protected_projects`, and the project that owns the active credential (from the
key's `client_email` or the impersonation target) are always exempt. Do not
relax these: the credential project is where the seed account lives, and
deleting it locks the tool out mid-run.

Deleting needs `resourcemanager.projects.delete` (`roles/resourcemanager.projectDeleter`);
listing needs `projects.list`/`get`, which `folderAdmin` already provides.
A project **lien** makes the delete fail until it is removed
(`roles/resourcemanager.lienModifier`). Deleted projects stay in a 30-day
soft-delete; `gcloud projects undelete` needs `resourcemanager.projects.undelete`,
which only the basic `roles/owner` (or a custom role) carries.

### Imported projects default to `deletion_policy = "PREVENT"`
The Google provider stores `PREVENT` for a project it did not create, so the
scratch module renders `deletion_policy = "DELETE"` and lets the adopt step
change that local attribute — otherwise `tofu destroy` refuses. The block also
ignores `billing_account`, `org_id`, `folder_id`, `labels` and
`terraform_labels`: prune cannot read the billing association cheaply and must
never edit a project it is about to delete. Keep that `ignore_changes` list
intact; removing an entry reintroduces drift writes (and `projects.update`,
which the seed account does not hold).

### Only importable resource types can be pruned
Deletion runs through `tofu import` + `tofu destroy` in a scratch module. The
Google provider cannot import `google_storage_bucket_object`, so bucket objects
are not prunable. Project IAM bindings are deliberately excluded too: an
authoritative IAM sweep can remove human access. Do not add a section unless the
provider supports import for that type.

### Pruning never touches the real state backend
`Reaper` writes a local-only module under `<workdir>/.python-tofu-prune/` and
never renders the stack's `backend` block. On success the directory is removed;
on failure it is kept for inspection. Never point that scratch module at the GCS
backend — a destroy there would delete managed state.

### Google-managed resources are skipped by name
`providers/gcp/prune.py` skips default service accounts (`*-compute`,
appspot, `service-N`) and the `GcpProvider.default_apis` baseline. Pruning those
breaks the project or the wrapper mid-run.

### Discovery uses service APIs, not Cloud Asset Inventory
Buckets, service accounts and enabled APIs are listed with the Storage, IAM and
Service Usage APIs respectively, scoped to `provider.project`. Do not switch
this back to CAI: it is eventually consistent, so a bucket deleted moments ago
can still be reported and the next prune then tries to import a 404 (observed
live). Assets the service APIs do not report are still invisible to pruning, so
a clean prune report is not proof that no stray infrastructure exists.

### Preview is read-only, apply is not
`plan --prune` and `python-tofu prune` (without `--apply`) only list resources.
`apply --prune` prunes after a successful apply and is incompatible with
`--plan-file`; `plan --prune` is incompatible with `--destroy`.

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

### `extra_files` is raw HCL, not a typed model
`extra_files` writes files verbatim and bypasses Pydantic validation. Keep names
flat and ending in `.tf`/`.tf.json`; managed files cannot be overridden. Validate
the rendered workdir with `tofu validate` before applying. `RenderResult.resources`
does not count resources declared this way.

### Raw HCL does not inherit typed dependencies
Resources in `extra_files` cannot see the typed `google_project_service` blocks
in `main.tf`. When a raw resource needs its API enabled first, add
`depends_on = [google_project_service.api_<slug>]` (for example
`api_biglake_googleapis_com`); otherwise OpenTofu may create the resource in
parallel with API enablement and fail with a 403. The BigLake example does this.

### Provider docs on `main` can be ahead of `~> 6.0`
The `google` provider docs site tracks `main`. A field shown there may not exist
in the pinned `~> 6.0` release (observed: `google_biglake_table`'s `serde_info`
block is absent in 6.50.0 and `tofu validate` rejects it). Check the docs at the
installed tag, or rely on `tofu validate`, before copying examples.

## Cloud Run

### `max_instance_count` lives in `template.scaling` on provider 6.x
`google_cloud_run_v2_service` has a top-level `scaling` block, but in 6.50 it
only accepts `min_instance_count`, `scaling_mode` and `manual_instance_count`.
Put both min and max under `template { scaling { ... } }`; a top-level
`max_instance_count` fails `tofu validate`.

### Function secret env vars need `project_id`
`service_config.secret_environment_variables` requires `project_id` in addition
to `key`, `secret` and `version`. The renderer fills it from the function's
project.

### Deletion protection defaults to true
`CloudRunService.deletion_protection=True` blocks `tofu destroy` until the
service is updated with `deletion_protection=False`. That is intentional for a
hardened default; do not flip the model default to make teardown convenient.

### Source zip determinism drives rebuilds
The function references the `BucketObject`'s `generation`. Zip with fixed
timestamps (the example does) or the bytes change on every render and the
function rebuilds each apply.

### Public access is two switches
Setting `ingress="all"` does not make a service callable; without
`allow_unauthenticated=True` there is no `allUsers` invoker binding. Both are
off by default.

### First enable of an API is not instant
Derived APIs are ordered before their consumers, but the backend can lag the
enable call. A live test enabled `run.googleapis.com` and immediately created a
Cloud Run job: the API call succeeded, yet the job never appeared within the
provider's four-minute poll and the apply failed. Re-running the same apply
created it in 14 seconds. Fast services (Artifact Registry, Pub/Sub topics)
succeed in the same pass; slow ones may need one retry after a fresh enable.

### Pub/Sub `ttl = ""` silently expires
The provider's expand function drops empty durations before the API call, so
`expiration_policy { ttl = "" }` becomes "no policy" and Pub/Sub applies its
31-day default. The field is `Computed`, so state shows `2678400s` and the plan
looks clean while the subscription is quietly expiring. Always emit an explicit
TTL; `"315360000s"` approximates "never".

### Pub/Sub filters are immutable
`filter` is `ForceNew`: changing it destroys and recreates the subscription,
dropping unacked messages. Pick the filter before creating the subscription.

### Exactly-once is pull-only
Pub/Sub rejects exactly-once delivery on push subscriptions. The DSL raises at
import time rather than letting `tofu apply` fail.

### Dead-letter topics need the service agent
The Pub/Sub service agent (`service-{project_number}@gcp-sa-pubsub.iam.gserviceaccount.com`)
needs `roles/pubsub.publisher` on the dead-letter topic. Creation succeeds
without it and failures only surface once a message exceeds
`max_delivery_attempts`, so the renderer emits the grant from a
`data "google_project"` lookup.

### Pushing to a private Cloud Run service needs three moving parts
1. `push_config.oidc_token.service_account_email` — the identity Pub/Sub signs as.
2. `roles/run.invoker` for that identity on the service — set
   `CloudRunService(invoker_service_accounts=[...])`.
3. `roles/iam.serviceAccountTokenCreator` for the Pub/Sub service agent
   (`service-{project_number}@gcp-sa-pubsub.iam.gserviceaccount.com`) on that
   identity.

All three fail the same way: Cloud Run logs "The request was not authenticated
... IAM principal lacks {run.routes.invoke}" and Pub/Sub retries in the
background, so publishing still looks successful. The DSL emits (2) and (3)
automatically.

Do not diagnose from the first 403s: a freshly created `run.invoker` binding
took about two minutes to take effect in a live test, with retries failing
until then. Wait, then read the receiver's logs — a delivery that starts
succeeding after the retries proves the wiring.

Note that Cloud Run v2 and Pub/Sub do not expose `getIamPolicy` in their REST
discovery documents (a `POST ...:getIamPolicy` returns a GFE 404), so verify
these grants through Terraform state or the service-account IAM policy rather
than the service API.

### `/healthz` is intercepted by the Google frontend
Cloud Run probes that request `/healthz` reach the container and pass, but an
external `https://*.run.app/healthz` request is answered by the frontend with
Google's HTML 404. Use `/health` (or a custom path) for a probe endpoint you also
want to curl. Observed live: service `Ready`, container serving `/` and `/beat`,
`/healthz` 404 from GFE.

### Cloud Run v2 REST flattens status onto the resource
`GET .../services/{name}` returns `conditions`, `terminalCondition`,
`latestReadyRevision`, `trafficStatuses` at the top level — not under `status` as
the proto suggests. Reading `payload["status"]` raises `KeyError`. Worker pool
GETs are the same, and may return an empty `conditions` list while the pool is
running (check `latestReadyRevision` and the logs instead).

### Worker pools have no ingress, probes or timeout
`google_cloud_run_v2_worker_pool` takes `scaling` as a **sibling** of `template`,
not inside it, and the template has no `timeout`, `ingress` or probe blocks. A
worker pool cannot be health-checked by Cloud Run; make the worker fail fast on
its own. `launch_stage` may need `BETA` while the feature is in preview.

### Job `max_retries` is on the inner template
`google_cloud_run_v2_job` nests two `template` blocks: the outer one takes
`task_count` and `parallelism`; the inner execution template takes `timeout`,
`service_account`, `containers` and `max_retries`. Putting `max_retries` on the
outer block fails `tofu validate` (observed on 6.50).

### Artifact Registry push auth
`docker login -u oauth2accesstoken --password-stdin https://REGION-docker.pkg.dev`
with an OAuth access token works for a service-account key. The repository must
exist before the first push, so create it in a separate apply from the service
that uses the image. Destroying the repository also removes its images.

### OpenTofu does not build images
`google_cloud_run_v2_service` takes an image reference. Build/push in CI or use
a `google_cloudbuild_trigger`; `gcloud run deploy --source` is not a Terraform
resource.

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
`seanc:0400`). It was rotated on 2026-11-17 to
`org-admin@nixos-infra-496517.iam.gserviceaccount.com`, the org-level seed admin
created by `scripts/bootstrap-org-admin.sh`. It holds `projectCreator`,
`folderAdmin`, `securityAdmin`, `serviceAccountAdmin`, `serviceAccountKeyAdmin`,
`orgpolicy.policyAdmin` and `serviceUsageAdmin` on organization `595961694991`
(project `nixos-infra-496517`), plus `billing.user` on the billing account.
`serviceUsageAdmin` is what allows disabling APIs (`prune` of the `apis`
section, `disable_on_destroy`); an account created before a role was added to
the script needs the binding re-applied — re-run the script with `--no-key`,
which re-grants every org role without touching an existing key.
The earlier `nixos-infra-admin@...` key was the project-scoped rotation. `.envrc` exports
`GOOGLE_APPLICATION_CREDENTIALS`, `TF_VAR_gcp_credentials_file`,
`GOOGLE_PROJECT`, `GOOGLE_CLOUD_PROJECT`, `CLOUDSDK_CORE_PROJECT` and
`TF_VAR_project` when the file is readable. Run `direnv allow` after editing
`.envrc`; without the secret the shell still evaluates.

Verify the current billing/API state before creating projects or buckets:
`nixos-infra-496517`'s billing account has been closed before, which makes
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

### Nix ignores untracked files
`nix build` and `nix flake check` evaluate the git tree, not the working
directory: new files must be `git add`-ed or the build silently uses the old
source. Symptom after adding a package: a fresh `ModuleNotFoundError` for the
new module in the packaged app while `pytest`/`nix develop` pass.

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
