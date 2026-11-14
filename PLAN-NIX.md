# Plan: Nix ↔ python-tofu integration

Status: N1–N5 implemented · Scope: `nix/`, `flake.nix`, `src/python_tofu/` boundaries ·
No changes to rendered HCL except where a workstream says so explicitly.

Goal: make the Nix layer a real part of the product, not just a build wrapper.
The package should be runnable without ambient tooling, the NixOS module should
express what the CLI actually supports, and `doctor` should be able to explain a
Nix-specific misconfiguration before OpenTofu starts.

Principles (from `PLAN.md`, applied to Nix):

1. **Nix owns the toolchain; Python owns the stack.** Nix pins `tofu` and
   provider binaries; it never generates HCL.
2. **Every implicit default stays visible.** A bundled provider version must be
   readable in `versions.tf`, not only in a Nix env var.
3. **Fail before Tofu starts.** Version and mirror mismatches belong in
   `doctor`, next to the existing GCP preflight checks.
4. **No secrets in the store.** The module supports credential *paths*
   (`environment`, `environmentFile`), never values.

## Current state (evidence)

| Observation | Where |
|---|---|
| Package contains only the Python venv; no `opentofu` | `nix/default.nix:1-9`; `result/bin/python-tofu` |
| `--binary` defaults to `tofu`, no env override | `core/cli/options.py:29`; `core/cli/context.py:55` |
| Module `command` enum omits `doctor`, `prune`, `limits` | `nix/module.nix:27` |
| Module has no `tofu` on the unit PATH, no plugin cache, no credential file, no timer | `nix/module.nix:51-79` |
| `doctor` has no toolchain checks | `providers/gcp/cli/doctor.py:263` |
| Flake checks render + `tofu fmt` only | `flake.nix:252-284` |
| DSL pins `google_provider_version = "~> 6.0"`; locked nixpkgs ships google 7.33.0 / opentofu 1.12.1 | `providers/gcp/stack.py:99` |
| `TofuRunner` merges `os.environ`, so Nix env vars reach `tofu` for free | `core/runner.py:26` |

---

## N1 — Module parity + completions (P0, implemented)

**Problem.** `services.python-tofu` can only express a subset of the CLI it
ships, and it passes flags to commands that do not accept them (e.g.
`--workdir` to `limits`).

**Design.**

- `settings.command` gains `doctor`, `prune`, `limits`.
  `apis` stays out: it is an interactive inspection command, not a
  reconciliation step.
- New typed settings, each passed **only to the commands that accept it**:
  `stackName`, `limits`, `usage`, `varFile`, `prune`.
- `settings.workdir` becomes `types.str` (a runtime writable directory, not a
  store path).
- New top-level options:
  - `tofuPackage` (default `pkgs.opentofu`) → the unit's `path`.
  - `environmentFile` (null) → `EnvironmentFile=`, for root-readable files such
    as agenix-managed ones.
  - `schedule` (null) → `systemd.timers.python-tofu` with `OnCalendar`;
    `RemainAfterExit` follows it, since a timer cannot retrigger an active unit.
- The unit always gets `TF_PLUGIN_CACHE_DIR=<workdir>/.tofu-plugins` and
  `CHECKPOINT_DISABLE=1`; an `ExecStartPre` creates the cache directory.
- Careful: `--prune` is a kill switch, so the option is tri-state
  (`null` = leave to the stack, `true` = `--prune`, `false` = `--no-prune`).

**Files.** `nix/module.nix`, `nix/default.nix` (completions), `flake.nix`
(if a check is needed), `docs/reference/module.md`, `docs/guides/nixos-integration.md`,
`tests/nix_eval/test_module_eval.py`.

**Acceptance.**

- `nix flake check --no-build` passes; `module-eval` and `home-module-eval`
  still evaluate.
- A new nix-eval test asserts: `doctor` is accepted, `--stack-name` reaches
  `ExecStart`, `limits` does **not** receive `--workdir`, and a `schedule` adds
  a timer while clearing `RemainAfterExit`.
- `nix build .#default` still produces `bin/python-tofu`, now with
  `share/{bash-completion,zsh,fish}` completions.

## N2 — One owner for the provider/toolchain version (P0, implemented)

**Problem.** The provider constraint existed in three places that already
disagreed: the Python default (`~> 6.0`), `required_providers` output, and the
provider nixpkgs bundles (7.33.0 in the locked input). Any offline mirror (N3)
would pin the *nixpkgs* version while the DSL asked for 6.x.

**Decision (resolved).** Bump the default to `~> 7.0` to match the locked
nixpkgs. This changes `versions.tf` for stacks that relied on the default; a
stack that sets `google_provider_version` explicitly is unchanged.

**Design (implemented).**

- `nix/provider-versions.nix` is the single source (`google = "~> 7.0"`).
- The packaged app wraps `bin/python-tofu` and exports the value as
  `PYTHON_TOFU_GOOGLE_PROVIDER_VERSION`.
- `GcpStack.google_provider_version` uses a `default_factory` that reads that
  variable, falling back to the same literal for non-Nix installs.
- `checks.provider-version` asserts the nixpkgs `hashicorp_google` version
  satisfies the constraint, so the weekly `update-flake-lock.yml` fails loudly.
- `checks.provider-version-default` asserts the Python fallback equals the Nix
  value, so `pip install` and Nix render the same constraint.

**Files.** `nix/provider-versions.nix`, `nix/default.nix`, `flake.nix`,
`providers/gcp/stack.py`, `tests/unit/test_provider_version.py`,
`docs/reference/dsl.md`, `docs/reference/cli.md`, `CHANGELOG.md`.

**Acceptance.** Both `provider-version*` checks pass; an explicit stack value
wins over the environment; `versions.tf` still renders with no environment in a
plain `pip` install.

**Effort.** S · **Risk.** Medium (default change) — documented in the changelog.

## N3 — Self-contained package with a provider mirror (P1)

**Problem.** `nix run .#` and the NixOS service need `tofu` on `PATH`, and the
first `init` downloads the google provider from the registry.

**Design.**

- `packages.<system>.with-tofu`: the app's `bin` plus
  `pkgs.opentofu.withPlugins (p: [ p.hashicorp_google ])`, which sets
  `NIX_TERRAFORM_PLUGIN_DIR` and makes `tofu init` work offline (nixpkgs'
  `opentofu_plugins_test` proves this with the proxy pointed at a dead address).
- `--binary` honours `PYTHON_TOFU_BINARY` (`typer.Option(..., envvar=...)`), so
  the wrapper selects the bundled binary without touching every call site.
- `nixosModules.default` defaults `services.python-tofu.package` to the
  self-contained variant; `tofuPackage` becomes unnecessary and is deprecated
  or dropped in favour of the package carrying its own `tofu`.
- Blocked on N2: without a matching version the mirror is useless.

**Acceptance.** In a network-namespace sandbox (`unshare -n`), the packaged app
completes `init` + `validate` for `examples/gcp_test_infra` and fails only for
API/credentials reasons, not registry access.

**Effort.** S–M · **Risk.** Low after N2.

## N4 — `doctor` toolchain checks (P1)

**Design.** Add to the existing `CheckResult` list, before the GCP checks:

- `tofu` resolves and its version satisfies `stack.required_version`.
- The expected `hashicorp/google` version is available to the provider (mirror
  dir, cache, or a note that a download will be required).
- `NIX_TERRAFORM_PLUGIN_DIR` / `TF_CLI_CONFIG_FILE` are set but unreadable →
  `FAIL` with the fixing path.
- The workdir (and the plugin cache inside it) is writable.

Keep it provider-agnostic in `core` (a `toolchain` check group), with the GCP
provider only contributing the expected provider version.

**Files.** `core/doctor.py` or a new `core/toolchain.py`,
`core/cli/commands/doctor.py`, `providers/gcp/cli/doctor.py`, tests.

**Acceptance.** Unit tests cover each failing branch with a fake `tofu` on
`PATH`; `doctor` still exits 0 with `--json` on a healthy setup.

**Effort.** S · **Risk.** Low (read-only).

## N5 — Hermetic `validate` checks and a VM test (P2, implemented)

**Design (implemented).**

- `checks.validate-examples` renders three examples and runs
  `tofu init -backend=false` + `tofu validate` with `with-tofu`; the HTTP
  proxies point at a dead address, so a registry lookup fails the check.
  This catches provider schema drift (renamed arguments, bad enum values) at
  `nix flake check` time instead of during a live apply.
- `checks.module-vm` is a `testers.nixosTest` that boots the module with a fake
  `python-tofu` and `tofu`, then asserts the argv it received
  (`--workdir`, `--stack-name`, `--prune`), that `tofu` resolves from the unit
  PATH, and that the plugin cache directory exists. It covers the runtime shape
  the eval-only tests cannot.

**Acceptance.** `nix flake check` builds the validate checks and runs the VM
test; both pass offline.

**Effort.** M · **Risk.** Low (no live cloud).

---

## Non-goals

- **Nix generating stack definitions or HCL.** The DSL is the authoring layer;
  generating `main.tf` from Nix duplicates the model and breaks `tofu fmt`
  determinism.
- **`uv2nix` IFD or root-level source filtering.** `GOTCHAS.md` already rules
  this out.
- **Secrets as `settings` values.** Only paths (`environment`,
  `environmentFile`) are supported.
- **Bundling `google-cloud-sdk` into the runtime package.** It stays in the
  `cloud` dev shell.
- **`services.python-tofu.settings.command = "apis"`.** Inspection command, not
  a service.

## Sequencing

| Milestone | Contents | Exit criterion |
|---|---|---|
| N1 | Module parity + completions | `nix flake check` passes; module covers the reconciling CLI |
| N2 | Version single-source + satisfies check | Flake update cannot silently break the mirror |
| N3 | `with-tofu` package + `PYTHON_TOFU_BINARY` | Offline `init`/`validate` under `unshare -n` |
| N4 | `doctor` toolchain group | A version/mirror mismatch is one command away |
| N5 | Validate checks + VM test | Schema drift fails `nix flake check` |

Each milestone ships with: the relevant tests, a docs update
(`module.md` / `nixos-integration.md` / `ci.md`), and a `CHANGELOG.md` entry.

## Open questions

1. **Provider bump (N2).** Move the DSL default to `~> 7.0` to match the locked
   nixpkgs, or keep 6.x and pin an older provider derivation? Recommendation:
   bump, with a changelog note and a tested upgrade path.
2. **Timer semantics (N1).** A scheduled unit currently also runs at boot
   (`wantedBy=multi-user.target` plus the timer). Keep both, or make `schedule`
   imply timer-only? Implemented as timer-only when `schedule` is set.
3. **`--auto-approve` in the module.** Still not exposed; it stays a manual
   action even in a service. Revisit only with a confirmed unattended use case.
