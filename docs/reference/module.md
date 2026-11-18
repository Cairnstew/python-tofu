# NixOS Module Reference

All options live under `services.python-tofu`.

The module installs a `oneshot` systemd service that runs one `python-tofu`
subcommand against a rendered working directory. It is intended for scheduled
or boot-time reconciliation, not for storing credentials in the Nix store.

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | bool | false | Enable the service |
| `package` | package | `pkgs.python-tofu` | python-tofu package to invoke |
| `tofuPackage` | package | `pkgs.opentofu` | OpenTofu package placed on the unit's `PATH` |
| `nixPackage` | package | `pkgs.nix` | Placed on the unit's `PATH` only when `settings.config` is a `.nix` file |
| `stack` | attrs or null | `null` | Cloud stack declared in Nix (see below); evaluated at build time |
| `stackFile` | path or null | `null` | Nix module declaring the stack; evaluated at build time |
| `environment` | attrs of str | `{}` | Environment variables (store-readable: use paths, not secret values) |
| `environmentFile` | path or null | `null` | `KEY=VALUE` file read by systemd before start (secrets, agenix, sops-nix) |
| `schedule` | str or null | `null` | systemd `OnCalendar` expression; null runs once at boot |
| `settings.command` | enum | `"render"` | `render`, `init`, `validate`, `doctor`, `plan`, `apply`, `destroy`, `output`, `prune` or `limits` |
| `settings.config` | path or null | `null` | Stack definition: `.py`, `.json` or `.nix` (sets `--config`) |
| `settings.workdir` | str | `/var/lib/python-tofu` | Working directory for HCL and state |
| `settings.stackName` | str or null | `null` | State name (sets `--stack-name`) |
| `settings.limits` | `error`/`warn`/`off` or null | `null` | Limit enforcement (sets `--limits`) |
| `settings.usage` | `stack`/`live` or null | `null` | Usage measurement mode (sets `--usage`) |
| `settings.varFile` | path or null | `null` | Extra tfvars for plan/apply/destroy (sets `--var-file`) |
| `settings.prune` | bool or null | `null` | `true` → `--prune`, `false` → `--no-prune` (plan/apply only) |
| `settings.autoApprove` | bool | false | `--auto-approve` for `apply`/`destroy` (needed for unattended apply) |
| `settings.extraArgs` | list of str | `[]` | Extra CLI arguments |

`apis` is deliberately not a `settings.command`: it is an interactive
inspection command, not a reconciliation step.

Flags are routed per subcommand. For example `limits` receives `--config` but
not `--workdir`, and `render` never receives `--var-file`, because Typer
rejects unknown options. `settings.extraArgs` is the escape hatch and is
appended verbatim.

`settings.workdir` is a string, not a Nix path: a path literal would be copied
into the read-only Nix store and could not hold state. A custom workdir must be
creatable by the service; the unit makes `${settings.workdir}` writable through
`ReadWritePaths`.

## Nix-declared stacks (apply at rebuild time)

`stack` and `stackFile` let you declare the cloud stack in Nix instead of a
separate `.py`/`.json` file. The declaration is evaluated **at build time** with
the option tree from `nix/stack.nix`, written to the store as
`python-tofu-stack.json`, and passed to the service as `--config`. No `nix`
binary is needed at activation.

```nix
services.python-tofu = {
  enable = true;
  stack = {
    provider = {
      project = "my-project";
      region = "europe-west1";
    };
    buckets.artifacts = {
      project = "my-project";
      location = "EU";
    };
  };

  # Reconcile on every rebuild. `restartTriggers` restarts the boot-time
  # oneshot when the evaluated JSON (or the package) changes.
  settings = {
    command = "apply";
    autoApprove = true;
  };
};
```

The keyed sections mirror the `GcpStack` field names; the key fills the
resource identity field unless it is set explicitly (`buckets.artifacts` →
`name = "artifacts"`, `projects.demo` → `project_id = "demo"`,
`service_accounts.ci-runner` → `account_id = "ci-runner"`). For a declaration
that needs `imports`, `mkMerge` or `mkIf`, point `stackFile` at a Nix module
using the same options:

```nix
services.python-tofu.stackFile = ./infra.nix;
```

`stack`, `stackFile` and `settings.config` are mutually exclusive. See
[`docs/reference/nix-stacks.md`](nix-stacks.md) for the full authoring guide.

A computed resource reference is a plain string with an escaped Nix
interpolation:

```nix
outputs.bucket.value = "\${google_storage_bucket.bucket_artifacts.name}";
```

Resource *identity* fields (`buckets.*.name`, `projects.*.project_id`,
`pubsub_topics.*.name`, …) must be literals because they become HCL labels;
Python validation rejects an interpolation there with a targeted error.

## Rebuild semantics

The boot-time unit is `oneshot` with `RemainAfterExit=true`, so it would stay
active and never re-run on a later `nixos-rebuild switch`. The module sets
`restartTriggers` to the evaluated config and the toolchain, so systemd
restarts it when any of them changes. With `settings.command = "apply"` and
`settings.autoApprove = true`, a rebuild therefore reconciles the declared
stack.

## Systemd service

The module creates `python-tofu.service` with:

- `Type=oneshot`
- `RemainAfterExit` when `schedule = null` (boot-time shape); `false` for a
  timed unit so the timer can retrigger it
- `StateDirectory=python-tofu`
- `path = [ tofuPackage ]`, so the CLI finds `tofu` without a system-wide install
  (`nixPackage` is added only for an explicit `.nix` config)
- `restartTriggers` for the evaluated config and toolchain, so a rebuild
  re-runs the unit
- `TF_PLUGIN_CACHE_DIR=${settings.workdir}/.tofu-plugins`, created by
  `ExecStartPre`, so providers are cached instead of re-downloaded
- `CHECKPOINT_DISABLE=1`
- `ExecStart` built from the options above
- `EnvironmentFile` when `environmentFile` is set
- `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`
- `ReadWritePaths` for the working directory

## Scheduling

Setting `schedule` creates `python-tofu.timer` and drops the service from
`multi-user.target`:

```nix
services.python-tofu = {
  enable = true;
  schedule = "hourly";
  settings = {
    command = "plan";
    config = ./infra.py;
  };
};
```

Use `plan --exit-code` (via `settings.extraArgs = [ "--exit-code" ]`) when the
timer should surface drift through the unit's exit status.

## Credentials

Prefer Application Default Credentials available to the service, or pass a path
via `environment`:

```nix
services.python-tofu = {
  enable = true;
  settings = {
    command = "plan";
    config = ./infra.py;
    workdir = "/var/lib/python-tofu";
  };
  environment.GOOGLE_APPLICATION_CREDENTIALS = "/run/agenix/gcloud-auth";
};
```

For secret *values* (API tokens, imported variables), use `environmentFile`
with a root-readable file rather than `environment`, which is world-readable
Nix store data:

```nix
services.python-tofu.environmentFile = "/run/agenix/python-tofu.env";
```

Do not put secret values in `settings`; they are world-readable Nix store data.

## Live VM test

The evaluation tests and `module-vm` check (in `flake.nix`) prove the argv and
unit shape with stubbed binaries. `scripts/live-module-vm.sh` verifies the real
thing: it builds the NixOS system in `nix/live-vm.nix`, boots it under QEMU and
lets `python-tofu.service` run an actual `apply` at activation — the same code
path as `nixos-rebuild switch`.

```bash
just test-live-module      # build, boot, apply, verify against the cloud
just clean-live-module     # destroy what the run created
```

It is **not** a flake check: it needs `/dev/kvm`, outbound network and a real
credential, and it changes cloud state. It targets only the throwaway project in
`nix/live-vm-stack.nix` (`pt-live-0361f9`), never the host project.

Two host paths are shared into the guest over 9p:

| Host | Guest | Why |
|------|-------|-----|
| `$RUN_DIR/credential` | `/run/agenix` | A 0400 copy of `/run/agenix/gcloud-auth`, removed on exit. The real agenix directory is `drwxr-x--x root:keys`, which QEMU cannot open as a 9p source, and the secret must never enter the Nix store. |
| `$RUN_DIR/workdir` | `/mnt/workdir` | Keeps the rendered HCL and `terraform.tfstate` after the VM powers off, so `--destroy` can clean up. |

The harness starts from a fresh state every run, resets any resources left
behind by an earlier failed run, then asserts three things: the unit's
`Result=success`, `Apply complete` on the serial console, and the bucket,
service account and IAM binding through the GCP APIs from the host.

## Home Manager

```nix
programs.python-tofu.enable = true;
```

The flake's `homeManagerModules.default` defaults `programs.python-tofu.package`
to the flake package, so no overlay is needed. This only adds the package to
`home.packages`, including the shell completions installed in the package's
`share/` directory.
