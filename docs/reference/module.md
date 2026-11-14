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
| `environment` | attrs of str | `{}` | Environment variables (store-readable: use paths, not secret values) |
| `environmentFile` | path or null | `null` | `KEY=VALUE` file read by systemd before start (secrets, agenix, sops-nix) |
| `schedule` | str or null | `null` | systemd `OnCalendar` expression; null runs once at boot |
| `settings.command` | enum | `"render"` | `render`, `init`, `validate`, `doctor`, `plan`, `apply`, `destroy`, `output`, `prune` or `limits` |
| `settings.config` | path or null | `null` | Python infrastructure module (sets `--config`) |
| `settings.workdir` | str | `/var/lib/python-tofu` | Working directory for HCL and state |
| `settings.stackName` | str or null | `null` | State name (sets `--stack-name`) |
| `settings.limits` | `error`/`warn`/`off` or null | `null` | Limit enforcement (sets `--limits`) |
| `settings.usage` | `stack`/`live` or null | `null` | Usage measurement mode (sets `--usage`) |
| `settings.varFile` | path or null | `null` | Extra tfvars for plan/apply/destroy (sets `--var-file`) |
| `settings.prune` | bool or null | `null` | `true` → `--prune`, `false` → `--no-prune` (plan/apply only) |
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

## Systemd service

The module creates `python-tofu.service` with:

- `Type=oneshot`
- `RemainAfterExit` when `schedule = null` (boot-time shape); `false` for a
  timed unit so the timer can retrigger it
- `StateDirectory=python-tofu`
- `path = [ tofuPackage ]`, so the CLI finds `tofu` without a system-wide install
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

## Home Manager

```nix
programs.python-tofu.enable = true;
```

The flake's `homeManagerModules.default` defaults `programs.python-tofu.package`
to the flake package, so no overlay is needed. This only adds the package to
`home.packages`, including the shell completions installed in the package's
`share/` directory.
