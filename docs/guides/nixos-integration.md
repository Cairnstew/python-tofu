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

The unit is `oneshot`; run `systemctl start python-tofu` after a deploy, or add a
timer if you want periodic reconciliation.

## Using with Home Manager

```nix
{
  imports = [ python-tofu.homeManagerModules.default ];
  programs.python-tofu.enable = true;
}
```

The module output supplies the package from this flake, so the overlay is not
required for the Home Manager path.

## Using the overlay directly

```nix
{
  nixpkgs.overlays = [ python-tofu.overlays.default ];
  environment.systemPackages = [ pkgs.python-tofu ];
}
```
