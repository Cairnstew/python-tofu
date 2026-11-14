# NixOS Integration Guide

## Adding to a NixOS configuration

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    python-tofu = {
      url = "github:your-user/python-tofu";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, python-tofu, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      modules = [
        python-tofu.nixosModules.default
        ./configuration.nix
      ];
    };
  };
}
```

## Basic configuration

```nix
{ config, ... }: {
  services.python-tofu = {
    enable = true;
    settings = {
      command = "render";
      config = ./infra.py;
      workdir = "/var/lib/python-tofu";
    };
  };
}
```

The unit is `oneshot`; run `systemctl start python-tofu` after a deploy, or set
`schedule` for periodic reconciliation.

## Scheduling

```nix
services.python-tofu = {
  enable = true;
  schedule = "hourly";            # systemd OnCalendar expression
  settings = {
    command = "plan";
    config = ./infra.py;
    stackName = "prod";
  };
};
```

A scheduled unit does not also run at boot: it is pulled in by
`python-tofu.timer` instead of `multi-user.target`.

## Credentials

Pass a path, never a value:

```nix
services.python-tofu.environment.GOOGLE_APPLICATION_CREDENTIALS =
  "/run/agenix/gcloud-auth";

# secret values (tokens, TF_VAR_*) belong in a root-readable file
services.python-tofu.environmentFile = "/run/agenix/python-tofu.env";
```

`settings` and `environment` end up world-readable in the Nix store; only paths
are safe there.

## Using with Home Manager

```nix
{
  imports = [ python-tofu.homeManagerModules.default ];
  programs.python-tofu.enable = true;
}
```

The module output supplies the package from this flake, so the overlay is not
required for the Home Manager path. The package installs bash, zsh and fish
completions under `share/`.

## Using the overlay directly

```nix
{
  nixpkgs.overlays = [ python-tofu.overlays.default ];
  environment.systemPackages = [ pkgs.python-tofu ];
}
```

## Toolchain

The NixOS module puts `pkgs.opentofu` on the unit's `PATH` by default
(`tofuPackage`). Override it to pin a specific OpenTofu build:

```nix
services.python-tofu.tofuPackage = pkgs.opentofu;
```

`TF_PLUGIN_CACHE_DIR` points at `${settings.workdir}/.tofu-plugins`, so provider
downloads happen once per working directory rather than on every start.

## Self-contained runs

`packages.<system>.with-tofu` bundles the app with an OpenTofu build that
already contains the mirrored `hashicorp/google` provider
(`opentofu.withPlugins`), and points the CLI at it through
`PYTHON_TOFU_BINARY`. `tofu init` then works with no registry access:

```bash
nix run .#with-tofu -- render --config infra.py --workdir .tofu/demo
nix run .#with-tofu -- plan   --config infra.py --workdir .tofu/demo
```

To use the same toolchain in a service, put the bundle on the unit's path:

```nix
services.python-tofu.tofuPackage = python-tofu.packages.${system}.with-tofu;
```

Alternatively, keep the default `pkgs.opentofu` and rely on the plugin cache;
the first start downloads the provider, later starts reuse it.
