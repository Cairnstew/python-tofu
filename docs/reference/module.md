# NixOS Module Reference

All options live under `services.python-tofu`.

The module installs a `oneshot` systemd service that runs one `python-tofu`
subcommand against a rendered working directory. It is intended for scheduled
or boot-time reconciliation, not for storing credentials in the Nix store.

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | bool | false | Enable the service |
| `package` | package | `pkgs.python-tofu` | Package to invoke |
| `settings.command` | enum | `"render"` | `render`, `init`, `validate`, `plan`, `apply`, `destroy` or `output` |
| `settings.config` | path or null | `null` | Python infrastructure module (sets `--config`) |
| `settings.workdir` | path | `/var/lib/python-tofu` | Working directory for HCL and state |
| `settings.extraArgs` | list of str | `[]` | Extra CLI arguments |
| `environment` | attrs of str | `{}` | Environment variables for the service |

## Systemd service

The module creates `python-tofu.service` with:

- `Type=oneshot`
- `StateDirectory=python-tofu`
- `ExecStart` built from the options above
- `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`
- `ReadWritePaths` for the working directory

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
  environment.GOOGLE_APPLICATION_CREDENTIALS = "/run/secrets/gcp.json";
};
```

Do not put secret values in `settings`; they are world-readable Nix store data.

## Home Manager

```nix
programs.python-tofu.enable = true;
```

The flake's `homeManagerModules.default` defaults `programs.python-tofu.package`
to the flake package, so no overlay is needed. This only adds the package to
`home.packages`.
