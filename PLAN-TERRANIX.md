# Plan: Nix-authored stacks (Terranix-shaped) for python-tofu

Status: **partially implemented** — T1, T3 and T4 landed in `c9c344d` and
`2ade7ac`; see `docs/reference/nix-stacks.md` and the Unreleased changelog.
T0, the remaining T2 prune gate and part of T5 are still open (see §9).
Scope: `core/loader`, `core/hcl`, `providers/gcp/{models,quirks,renderer}`,
`nix/`, `docs/`, `tests/`
Reference implementation studied: **terranix @ `163b787`** (2026-11-14), cloned
to `/tmp/opencode/terranix`. All Terranix citations below are line numbers in
that checkout.

Goal: let a Nix expression author a `GcpStack`, so the repo's guardrails
(typed validation, free-tier limits, `prune`, `doctor`) survive when the
authoring language is Nix instead of Python — and without inventing a third
configuration format.

---

## 1. What Terranix actually does (evidence)

| Mechanism | Where | Consequence for us |
|---|---|---|
| `lib.evalModules` over `terraform-options.nix` + `modules/` | `core/default.nix:50-58` | NixOS module system *is* the composition layer (`imports`, `mkMerge`, `assertions`) |
| Freeform recursive type `mkMagicMergeOption` (bool/int/float/str/reference/attrs/list) | `core/terraform-options.nix:26-56` | No per-resource typing at all; the provider schema is never modelled |
| Blocks carry `__functor` (`.attr` → ref) and `__toString` (block → ref) | `core/terraform-options.nix:11-16` | `config.resource.x.y.name` yields a *string* |
| `reference` option type coerced to `str` via `__toString` | `core/terraform-options.nix:21-24, 49` | A block used as a value becomes `"${addr}"` |
| `sanitize` strips `_module`/`_ref`/`__functor`/`__toString` + nulls | `core/default.nix:16-42` | Emitted JSON contains **only** Terraform data |
| Whitelisted top-level keys: `ephemeral, data, import, locals, module, moved, output, provider, removed, resource, terraform, variable` | `core/default.nix:80-92` | Output is Terraform's own `.tf.json` dialect |
| Assertions/warnings checked at eval time (`checkAssertWarn`) | `core/default.nix:80` | Terranix has a validation channel — Nix-side only |
| Emitted references are plain strings | `tests/terranix-tests/12.nix.output` | `"${data.another-resource.id}"` — **not** a structured node |
| `tf.ref` / `tf.file` / `tf.template` helpers | `core/helpers.nix:4-20` | Users hand-write `${...}` because Nix and HCL share the syntax |
| Entry points `lib.evalTerranixConfiguration` / `lib.terranixConfiguration` | `flake/lib.nix:30-59` | Established flake-API shape to mirror |

The load-bearing fact: **Terranix never emits HCL, only Terraform JSON, and
references survive as `${...}` strings.** That is what makes it provider-
agnostic, and it is also what makes it untyped.

## 2. Current state in this repo (evidence)

| Observation | Where |
|---|---|
| `extra_files` accepts `.tf.json` verbatim and writes it into the workdir | `core/renderer.py:107-122` |
| `load_stack` already validates a plain `dict` via `model_validate` | `core/loader.py:52-63` |
| `load_stack` hard-rejects any config that is not `.py` | `core/loader.py:76-77` |
| `extra="forbid"`, `frozen=True` on every model — schema drift fails loudly | `core/models.py:18-21` |
| `model_dump(mode="json")` → `model_validate` round-trips **exactly** (verified, incl. nested `Volume`) | this plan, §5 |
| `Volume`/`Probe` are key-tagged (`gcs`, `http_get`, …), not `Union` — JSON-friendly | `providers/gcp/models.py:459-473, 526-543` |
| `ref()` returns `hcl.Raw`; JSON dumps it as `{"text": "…"}` and it does **not** round-trip | `core/hcl.py:31` (verified) |
| The HCL writer quotes strings with `json.dumps`, leaving `${…}` intact → renders as a real interpolation | `core/hcl.py:92-94` (verified) |
| Resource **local HCL labels** are derived from identity fields: `bucket_{slug(bucket.name)}`, `topic_{slug(topic.name)}`, … | `providers/gcp/renderer.py:203, 445, 491, 555` |
| Subscription/topic cross-refs resolve against declared topics, else fall back to a literal path | `providers/gcp/renderer.py:467-475` |
| Identity validators (e.g. `BUCKET_NAME_RE`) reject `${…}` | `providers/gcp/models.py:273-276`, `quirks.py:18` |
| Limits/prune read the typed stack only | `core/provider.py:33-37` |
| `compose()` gives merge + duplicate detection, no conditionals/defaults | `providers/gcp/parts.py:95-135` |

## 3. Relationship to PLAN-NIX.md

`PLAN-NIX.md:13-14` states: *"Nix owns the toolchain; Python owns the stack.
Nix pins `tofu` and provider binaries; it never generates HCL."*

This plan **keeps** that but amends it in one respect: Nix may supply stack
**data**, which Python validates and renders. Nix still never emits HCL text —
the one exception is the existing, explicit `.tf.json` escape hatch, which is a
*stack input*, not generator output.

## 4. Decision log

**D1 — Reference encoding: Terranix-compatible `${…}` strings, not `hcl.Raw`.**
Terranix's output proves the string form is what the ecosystem emits, and
`core/hcl.py:92-94` already renders it correctly. `hcl.Raw` stays the
Python-side API. Consequence: no schema extension, no `$ref` sentinel, and
Terranix configs are readable as-is.

**D2 — Two modes, not one converter.**

```
mode A  typed      .nix --(nix eval)--> JSON --(model_validate)--> GcpStack --> HCL
                   guardrails ON  · ~20 modelled resource types · python-tofu option tree

mode B  passthrough  nix eval --> .tf.json --(extra_files)--> workdir --> tofu
                   guardrails OFF · any resource the provider supports · Terranix modules
```
A lossy `tf.json → GcpStack` converter (mapping `resource.google_storage_bucket.x`
→ `StorageBucket`) is explicitly rejected: Terranix permits arbitrary provider
attributes while our models `extra="forbid"` (`core/models.py:21`), so the
converter would reject most real Terranix configs *and* silently drop what it
could not map. Mode B already serves those configs, minus guardrails.

**D3 — JSON shape is the `GcpStack` schema.** `extra="forbid"` guarantees that
a Nix option tree which drifts from the Pydantic models fails immediately
rather than silently rendering something else. No translation layer, so no
second schema to keep in sync.

**D4 — References are classified per field, not by "looks like a ref".**
Three classes, because the renderer treats them differently:

| Class | Examples | Reference policy |
|---|---|---|
| **A — label-bearing identity** | `StorageBucket.name`, `PubSubTopic.name`, `ServiceAccount.account_id`, `ArtifactRegistryRepository.repository_id` | **Reject.** The value becomes an HCL label via `slug()` (`renderer.py:203, 491`), so a non-literal mangles the address silently. `doctor`/validation must say why. |
| **B — free-form attribute** | `Output.value`, `CloudRunService.image`, env values, `BucketObject.content` | **Pass through** verbatim as a quoted interpolation. |
| **C — cross-reference** | `BucketObject.bucket`, `PubSubSubscription.topic`, `ProjectIamMember.member`, `CloudRunService.service_account`, `SecretEnv.secret` | **Pass through, and skip declared-set resolution.** `renderer.py:467-475` currently rewrites a declared topic name into `google_pubsub_topic.topic_<slug>.id`; a `${…}` value must bypass that branch. |

## 5. Workstreams

### T0 — Make mode B honest (P0, ~60 lines)

**Problem.** `extra_files` already carries Terranix JSON, but nothing tells the
user that `limits` and `prune` cannot see those resources (`GOTCHAS.md:240-244`
covers validation, not the guardrail blindness).

**Design.**
- `limits` prints a one-line warning naming `extra_files` entries: resources
  there are unmeasured, so limits are `unknown`.
- `prune` **fails closed** if the stack carries any `.tf.json`/`.tf` file while
  pruning is enabled — it cannot prove the declared set, and prune deletes.
  Overridable only by an explicit `--ignore-extra-files` flag.
- Document mode B in `docs/reference/dsl.md` §"Raw HCL escape hatch"
  (line 374) with a Terranix snippet.

**Files.** `core/cli/commands/limits.py`, `core/cli/commands/prune.py`,
`core/prune.py` (if the gate belongs there), `docs/reference/dsl.md`,
`tests/unit/test_prune.py`, `tests/unit/test_cli.py`.

**Acceptance.** A stack with `extra_files` + `prune=PruneConfig(enabled=True)`
refuses to prune with a message naming the file; `limits` warns once; both
tests are offline (fake tofu, no credentials).

### T1 — `nix eval` ingest for `.nix` configs (P0, ~150 lines)

**Problem.** `core/loader.py:76-77` refuses anything but `.py`, so the seam at
`loader.py:52-63` is unreachable from the CLI.

**Design.**
- New `core/nix.py`: `eval_nix_json(path) -> dict`, running
  `nix eval --json --file <path>` with `--impure` only when the config uses
  `<nixpkgs>`; surface stderr as `ConfigError`.
- `load_stack` gains a `.nix` branch: evaluate → `_coerce` (existing path).
  Requires the result to be `{ "stack": {…} }` or the bare stack mapping, so
  the `stack` convention is identical across languages.
- Optional input cache: write the evaluated JSON to
  `<workdir>/stack.json` keyed by the config's mtime + a hash of its imports,
  so `plan`/`apply` do not shell out to Nix twice per invocation. Cache off by
  default in v1; measured before it is added.
- Error text must name the Nix attribute path (Pydantic gives the field path;
  prepend it with the file).

**Files.** `core/nix.py` (new), `core/loader.py`, `core/cli/options.py`
(help text: "Python module or Nix file exposing `stack`"),
`core/exceptions.py`, `tests/unit/test_loader.py`, `tests/unit/test_nix.py`.

**Acceptance.** `python-tofu render --config examples/gcp_nix/stack.nix`
works; a bad bucket name in Nix raises `ConfigError` naming the field; a
missing `nix` binary produces one actionable error, not a traceback.

### T2 — Reference support in typed fields (P0, the crux)

**Problem.** Today a computed name/reference is inexpressible: identity
validators reject `${…}` (`models.py:273`), and free-form slots would render a
`Raw` as a dict.

**Design.**
- `core/hcl.py`: `is_reference_template(value: str)` (true when it contains a
  `${…}` template) — the single predicate every validator consults.
- Class A fields: validator raises with a targeted message
  ("`name` becomes the HCL label for this resource and must be a literal;
  move the computed part into an attribute or an `output`").
- Class B/C fields: accept the string unchanged. Class C additionally
  short-circuits the declared-set lookup at `renderer.py:467-475`.
- `prune` **fails closed** for any prunable section containing a reference in
  its identity field: the declared set is not statically knowable, and prune
  deletes.
- `compose()` duplicate keys keep using the literal string — references are
  still unique literals, so `parts.py:95-135` needs no change.

**Files.** `core/hcl.py`, `providers/gcp/quirks.py`,
`providers/gcp/models.py`, `providers/gcp/renderer.py`,
`providers/gcp/prune.py`, `docs/reference/dsl.md`,
`tests/unit/test_gcp_objects.py`, `tests/unit/test_gcp_pubsub.py`,
`tests/unit/test_prune.py`.

**Acceptance.** `Output(value="${google_storage_bucket.b.self_link}")` renders
as `value = "${…}"`; `PubSubSubscription(topic="${google_pubsub_topic.t.id}")`
is emitted verbatim rather than path-rewritten; `StorageBucket(name="${…}")`
fails with the class-A message; prune refuses a reference-bearing section.

### T3 — A python-tofu Nix option tree (P0 for mode A)

**Problem.** Mode A needs a Nix surface whose output matches the Pydantic
schema exactly (D3).

**Design.**
- `nix/stack.nix`: `lib.evalModules` with sections named **exactly** after the
  `GcpStack` fields (`provider`, `projects`, `apis`, `service_accounts`,
  `buckets`, `bucket_objects`, `iam_members`, `cloud_run_services`,
  `pubsub_topics`, `pubsub_subscriptions`, `outputs`, `prune`, `extra_files`),
  each `attrsOf`/`listOf` a recursive freeform type modelled on
  `mkMagicMergeOption` (`core/terraform-options.nix:26-56`) so `mkMerge`
  composes sections. Reuse Terranix's idea, not its code.
- Emit `{ stack = …; }` and nothing else — no Terraform keys, no sanitising
  magic; there are no `__functor` hooks to strip because references are
  authored as plain strings (D1).
- Expose on the flake: `lib.evalStack`, `lib.stackType`, mirroring
  `flake/lib.nix:17-55`. No `packages.<stack>` derivation in v1.
- Example `examples/gcp_nix/stack.nix` reproducing
  `examples/gcp_bootstrap/infra.py`.

**Files.** `nix/stack.nix` (new), `flake.nix`, `examples/gcp_nix/`,
`docs/reference/dsl.md` (a "Nix front-end" section), `tests/nix_eval/`.

**Acceptance (the strong one).** A golden test renders
`examples/gcp_nix/stack.nix` via `nix eval` + `python-tofu render` and compares
**byte-for-byte** with the same stack authored in Python. Any schema drift in
either direction breaks it.

### T4 — Packaging and hermeticity (P1)

**Problem.** A `.nix` config makes `nix` a runtime dependency of a command
that is currently pure Python.

**Design.** `nix/module.nix` gains `nixPackage`; the unit's `path` includes it
only when `settings.config` ends in `.nix`. `packages.<system>.with-tofu`
gains an optional `with-nix` variant for offline runs (alongside the existing
mirrored provider — `docs/guides/nixos-integration.md:111-127`). `doctor`
reports "config is `.nix` but no `nix` on PATH" before tofu starts.

**Files.** `nix/module.nix`, `nix/default.nix`, `flake.nix`,
`providers/gcp/cli/doctor.py`, `tests/nix_eval/test_module_eval.py`.

**Acceptance.** Module eval test asserts the unit gains `nix` in `path` only
for `.nix` configs; `nix build .#with-tofu-nix` succeeds.

### T5 — Checks and CI (P2)

Add to `nix flake check`: (a) the T3 golden comparison, sandboxed, no cloud
credentials; (b) a mode-B check that a Terranix-style `.tf.json` renders and
`tofu validate`s offline (reuse the existing `validate-examples` pattern).
`just nix-stack` for local use.

## 6. Non-goals

- **Schema codegen** from `terraform providers schema -json`. That is what
  would lift the ~20-type ceiling, but it contradicts the repo's stated
  "curated DSL, not a schema mirror" stance (`STRUCTURE.md:261-278`) — a
  separate product decision, not a workstream here.
- **Reimplementing Terranix's `__functor`/`__toString` block magic.** Strings
  only (D1). Blocks-as-references is the one Terranix feature we deliberately
  do not copy.
- **A lossy `tf.json → GcpStack` converter** (D2).
- **Growing `compose()` into a module system.** If you want conditionals,
  defaults and option declarations, Nix owns that layer (`PLAN-NIX.md` split).
- **Nix generating HCL text** (beyond the `extra_files` input path).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Every command shells out to `nix`; `--config` is no longer pure | T1 optional cache; measure before enabling; `render` output is the only thing tofu needs |
| Two authoring surfaces drift (Python models vs Nix options) | T3 golden byte-comparison test; `extra="forbid"` turns silent drift into failures |
| References weaken static identity checks | Class-based policy (D4), loud class-A errors, prune fails closed |
| `docs/reference/dsl.md` becomes two documents in one | One section per language, one shared schema table; the DSL reference stays authoritative for field meaning |
| Terranix users expect block references | Document the difference explicitly; mode B is the answer for full Terranix parity |

## 8. Sequencing

```
T0 (honest mode B)  ──►  T2 (references)  ──►  T3 (option tree)  ──►  T5 (checks)
   T1 (nix ingest)  ──┘                          └──►  T4 (packaging)
```
T0 and T1 are independent and each shippable alone. T2 must land before T3
produces anything with a computed value. T4 last, because it is only a
concern once people run `.nix` configs from a systemd unit.

## 9. Implementation status

Landed:

- T1 — `.json` and `.nix` ingest in `core/loader.py`, with
  `core/nix.py` (`nix eval --json`, `--impure` only for `<nixpkgs>` /
  `builtins.getFlake`).
- T2 (most) — `${...}` strings pass through free-form/cross-reference fields;
  identity fields that become HCL labels reject them with a targeted error;
  renderer rewrites (`_topic_ref`, `_iam_member_value`, service-account and
  bucket references) bypass references. The declared-set validators skip
  reference values, so the identity set stays static.
- T3 — `nix/stack.nix` option tree mirroring `GcpStack`, `lib.evalStack`,
  `lib.mkStackJson`, `lib.mkStackFile`, module aliases, examples and the
  byte-for-byte `render-nix-example` check.
- T4 — `services.python-tofu.stack`/`stackFile` evaluated at build time to a
  store JSON, `settings.autoApprove`, `nixPackage` only for `.nix` configs,
  `restartTriggers` so a rebuild re-applies, and `with-tofu-nix`.
- T5 (part) — `stack-eval`, `render-nix-example`, Nix stack in
  `validate-examples`, and the VM test asserting the JSON config.

Still open:

- T0 — `limits` warning and `prune` fail-closed for `extra_files` mode B.
- T2 — the explicit prune fail-closed gate for reference-bearing sections
  (class A rejects identity references today, so this is defence in depth).
- T5 — a local `just nix-stack` recipe and a Terranix `.tf.json` validate
  check.
