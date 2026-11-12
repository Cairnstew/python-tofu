# Plan: seamless `plan` / `apply`

Status: proposed · Scope: `python-tofu` core + GCP provider · No breaking changes to
existing stack files.

Goal: make the common loop — `plan`, review, `apply`, read results — work on a
fresh project, from any directory, with no unexplained 403s and no chance of
touching another stack's state. Keep every default explicit in the rendered HCL
so the plan stays auditable.

Principles:

1. **Defaults must be visible.** Anything implicit (API enablement, labels,
   state prefix) must still appear in the generated `.tf`.
2. **Never default a destructive or public action.** Approval, deletion
   protection and ingress stay opt-in.
3. **Fail before Tofu starts.** A preflight error costs seconds; an apply error
   costs minutes and can leave partial state.
4. **Free tier first.** Every live verification step must fit the always-free
   allowance, and be destroyed afterwards.

## Current state

Already seamless:

- `--config` defaults to `infra.py`, `--workdir` to `.tofu`
- `plan --json`, `apply --plan-file`, `plan --no-init`
- provider `default_labels`, pinned `required_version` / provider version
- free-tier `limits` enforcement before render
- pruning of undeclared resources
- derived API enablement with `depends_on` ordering (recent)

Known gaps, with evidence:

| Observation | Where |
|---|---|
| No typed outputs; the DSL cannot declare `output` blocks | `core/models.py`, `providers/gcp/stack.py` |
| `backend.prefix` defaults to the shared `python-tofu/state` | `providers/gcp/models.py` (`GcpBackendConfig`) |
| `workdir` defaults to the shared `.tofu` for every config | `core/cli/context.py` |
| No preflight command (`doctor`), no billing/API readiness check | `core/cli/commands/` |
| `plan` always exits 0 when Tofu succeeds, even with changes | `core/cli/commands/plan.py` |
| No billing budget resource; `billingbudgets` is only protected from prune | `providers/gcp/prune.py` |
| Secrets can be referenced (`SecretEnv`/`SecretVolume`) but not declared | `providers/gcp/models.py` |
| Images must be built outside; no Cloud Build trigger model | `providers/gcp/models.py` |
| Stack parts are merged by hand in examples | `examples/gcp_clean/parts/` |

## Workstream 1 — Outputs (P0)

**Problem.** `python-tofu output` reads Tofu outputs, but no stack can declare
one. Results such as a service URL, bucket name or topic ID can only be found in
the console.

**Design.**

```python
from python_tofu import Output, ref

stack = GcpStack(
    provider=provider,
    cloud_run_services=[...],
    outputs=[
        Output("service_url", ref("google_cloud_run_v2_service.run_api.uri")),
        Output("bucket", ref("google_storage_bucket.bucket_assets.name")),
        Output("topic", ref("google_pubsub_topic.topic_jobs.id")),
    ],
)
```

- `ref("...")` is a thin public wrapper around the existing `Raw` expression
  type; no new evaluation model.
- `Output` fields: `name`, `value`, `description=None`, `sensitive=False`.
- Renderer emits `output "name" { value = <raw> … }` after resources.
- `python-tofu output` already works; add `--format json|shell|python` if cheap.

**Files.** `core/models.py` (or a small `core/outputs.py`), `core/renderer.py`,
`providers/gcp/stack.py`, `providers/gcp/renderer.py`, exports, docs, example.

**Acceptance.**

- Unit: outputs render deterministically after resources; duplicate names
  rejected; `sensitive` renders.
- Live: apply the Pub/Sub example with two outputs; `python-tofu output --json`
  returns the topic ID and push URL.
- Existing stacks without `outputs` render byte-identically.

**Effort.** S · **Risk.** Low.

## Workstream 2 — Per-stack state isolation (P0)

**Problem.** Every stack shares workdir `.tofu` and backend prefix
`python-tofu/state`. Running `plan` for a dev stack after a prod stack silently
reads prod state in the same directory.

**Design.**

- Add `--stack-name` (default: config file stem, e.g. `infra`, `gcp_pubsub`).
- Default workdir becomes `.tofu/<stack-name>` **when `--workdir` is omitted**.
  Explicit `--workdir` keeps current behaviour.
- `GcpBackendConfig.prefix` default becomes `python-tofu/<stack-name>`; a prefix
  set explicitly in the stack is never rewritten.
- `GcpStack.name` (optional) overrides the derived name.

**Files.** `core/cli/options.py`, `core/cli/context.py`, `providers/gcp/models.py`,
`providers/gcp/renderer.py`, docs, tests.

**Acceptance.**

- Two configs in one directory produce distinct workdirs and prefixes.
- Explicit `--workdir` / explicit `prefix` are honoured unchanged.
- Migration note in `CHANGELOG.md` for users relying on `.tofu`.

**Effort.** S · **Risk.** Medium (default change) — mitigate with the explicit
override path and a changelog note.

## Workstream 3 — `plan --exit-code` (P0)

**Problem.** CI cannot tell "no changes" from "changes" without parsing text.

**Design.** Add `--exit-code` to `plan`: exit `2` when the plan has changes,
`0` when empty, `1` on error. Mirrors `tofu plan -detailed-exitcode` without
leaking the raw flag.

**Files.** `core/cli/commands/plan.py`, `core/results.py` if the summary needs a
flag, docs, tests.

**Acceptance.** Unit test drives the CLI with a fake runner for all three exit
codes; `plan --json` still prints the summary.

**Effort.** XS · **Risk.** Low.

## Workstream 4 — `python-tofu doctor` (P1)

**Problem.** The most expensive failures are discovered late: missing
credentials, a project not ACTIVE, billing disabled, an API still disabled, an
unreachable state bucket, or a concurrent apply. The fresh-enable lag observed
live (job creation polled for four minutes) is exactly what a preflight should
surface as "API enabled 3s ago — backend may still be warming".

**Design.** A read-only command that prints a checklist and exits non-zero on
failures:

```
python-tofu doctor --config infra.py [--usage live]
✓ credentials      project-main-owner@… (expires in 52m)
✓ project          demo-project (ACTIVE)
✓ billing          enabled
✓ APIs             6 required, all ENABLED
✗ state lock       another apply may be running (gs://…/default.tflock)
```

Checks, in order:

1. credentials resolve and can mint a token (`live.access_token`)
2. provider project exists and lifecycle state is `ACTIVE`
3. billing enabled (Cloud Billing API, read-only)
4. `required_apis(stack)` vs `ServiceCatalog.enabled()` — list missing, do not enable
5. backend bucket reachable (Storage API) and prefix writable; local backend
   directory creatable
6. optional: state lock object present for the configured backend
7. `limits` summary preview (reuse `--fail-on-unknown` semantics)

Each failure prints the fix, e.g. `python-tofu apis enable run`.

**Files.** `core/cli/commands/doctor.py`, `core/cli/registry.py`,
`providers/gcp/cli/doctor.py` (provider checks), `providers/gcp/live.py`
(token/project helpers), tests with mocked HTTP.

**Acceptance.** Unit tests cover each failing branch with a fake client; a live
run passes on the test project; missing-API branch is exercised by temporarily
disabling a fast API (Artifact Registry) and re-enabling it.

**Effort.** M · **Risk.** Low (read-only).

## Workstream 5 — Billing budget (P1)

**Problem.** An IaC tool's worst failure mode is an unbounded bill. The repo
already protects `billingbudgets.googleapis.com` from prune but cannot create a
budget.

**Design.**

```python
BillingBudget(
    billing_account="01ABCD-EFGH23",
    display_name="python-tofu guardrail",
    amount=5,                    # account currency
    thresholds=[0.5, 0.9, 1.0],  # alert-only
)
```

- Renders `google_billing_budget` with `all_updates_rule` email alerts.
- Default: alert-only, never disable billing.
- Optional `project_filter` so per-stack budgets are possible.
- Not owned by a project: skip project reference validation.

**Files.** `providers/gcp/models.py`, `providers/gcp/renderer.py`,
`providers/gcp/stack.py`, exports, docs, example, tests.

**Acceptance.** Unit: alert thresholds and amount render; budget without
`billing_account` rejected. Live: create a $1 budget with a 100% alert, read it
back through the Cloud Billing API, delete it.

**Effort.** S · **Risk.** Low.

## Workstream 6 — Stack profiles (P2)

**Problem.** Preview environments need four flips (deletion protection, prune,
state kind, limits mode) repeated per stack.

**Design.** `GcpStack(profile="preview")` expands to a small, documented set:

| Field | `default` | `preview` |
|---|---|---|
| `deletion_protection` on services/jobs/pools | `True` | `False` |
| `prune.enabled` | `False` | `True` for owned sections |
| `backend.kind` | `gcs` if set, else local | `local` |
| limits mode | `error` | `warn` |
| default labels | unchanged | `{"ephemeral": "true"}` added |

Rules: a profile only flips booleans/labels. It never rewrites resource names or
references; those stay explicit so `push_service="api"` and import IDs remain
predictable. Explicit per-resource values always win.

**Files.** `providers/gcp/stack.py` (`_apply_profile` validator), docs, tests.

**Acceptance.** A stack with `profile="preview"` renders
`deletion_protection = false` on every supported resource; explicit `True`
survives; default profile renders unchanged output.

**Effort.** S · **Risk.** Medium (implicit defaults) — mitigated by rendering
the resolved values, never hiding them.

## Workstream 7 — `compose()` for parts (P2)

**Problem.** `examples/gcp_clean/parts/` merges resource lists by hand; duplicate
addresses across parts surface only at render.

**Design.**

```python
from python_tofu import StackPart, compose

foundation = StackPart(buckets=[...], apis=[...])
storage = StackPart(service_accounts=[...], buckets=[...])

stack = GcpStack(provider=provider, **compose(foundation, storage))
```

`StackPart` holds any `GcpStack` resource list; `compose` merges lists and
rejects duplicate addresses early with the part name in the message.

**Files.** `providers/gcp/parts.py`, `providers/gcp/stack.py`, example rewrite,
docs, tests.

**Acceptance.** Duplicate bucket/name across parts raises with both part names;
existing `gcp_clean` example produces identical HCL after the rewrite.

**Effort.** S · **Risk.** Low.

## Workstream 8 — Deferred (P3)

- **Secret Manager** (`google_secret_manager_secret` + version): value supplied
  from env/file, never the model. State exposure documented.
- **Cloud Build trigger**: closes the "images are built elsewhere" gap.
- **Provider quota project**: `billing_project` / `user_project_override` for
  orgs with centralised API quota.
- **Skip redundant `tofu init`** when the lock file and `.terraform` are current.
- **`graph` / `why`**: explain dependency edges, including API ordering.

## Non-goals

- Defaulting `--auto-approve`, public ingress, or `deletion_protection=False`.
- Auto-enabling APIs in `external_projects` (the stack has no mandate there).
- Auto-creating the state bucket inside the stack that stores its state; that is
  a one-time bootstrap (`examples/gcp_bootstrap`).
- Rewriting resource names from a profile or environment string.

## Sequencing

| Milestone | Contents | Exit criterion |
|---|---|---|
| M1 | Workstreams 1, 3 | Outputs readable from CI; `plan --exit-code` gates a PR |
| M2 | Workstream 2 | Two configs in one directory use separate state |
| M3 | Workstream 4 | `doctor` catches missing credentials, disabled APIs, unreachable backend |
| M4 | Workstreams 5, 6 | Budget guardrail live; preview profile proven on a throwaway stack |
| M5 | Workstream 7 | `gcp_clean` composes parts with duplicate detection |

Each milestone ships with: unit tests, a live check where it touches GCP, docs
(`dsl.md` / `cli.md`), and a `CHANGELOG.md` entry.

## Live verification policy

- One apply at a time; `free -h` is not relevant here but build memory is — keep
  images under ~200 MB.
- Prefer fast services for enablement tests (Artifact Registry ~25s) over slow
  ones (Cloud Run jobs can need a retry after a fresh enable).
- Destroy everything at the end; leave APIs in the state they were found in.
- Record observed quirks in `GOTCHAS.md` before closing the workstream.

## Open questions

1. Should `doctor` be able to *fix* (enable APIs, create backend bucket), or stay
   read-only with printed commands? Proposal: read-only in M3, revisit later.
2. Should outputs be usable as inputs to another stack automatically (a
   `remote_state` data source), or remain copy-paste via `external_*`?
3. Is a stack-level `name_prefix` wanted at all, given the reference-resolution
   risks? Proposal: no for now.
