from __future__ import annotations

import subprocess

import pytest


@pytest.mark.nix
def test_module_evaluates() -> None:
    result = subprocess.run(
        ["nix", "eval", ".#nixosModules.default", "--apply", "builtins.typeOf"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "lambda" in result.stdout


@pytest.mark.nix
def test_module_option_empty_list_preserved() -> None:
    expr = """
      let
        flake = builtins.getFlake (toString ./.);
        nixpkgs = flake.inputs.nixpkgs;
        system = nixpkgs.lib.nixosSystem {
          system = "x86_64-linux";
          modules = [
            flake.nixosModules.default
            {
              services.python-tofu.enable = true;
              services.python-tofu.package =
                nixpkgs.legacyPackages.x86_64-linux.hello;
            }
          ];
        };
        json = builtins.fromJSON (builtins.toJSON system.config.services.python-tofu.settings);
      in builtins.typeOf json.extraArgs
    """
    result = subprocess.run(
        ["nix", "eval", "--impure", "--expr", expr],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "list" in result.stdout
