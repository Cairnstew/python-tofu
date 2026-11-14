from __future__ import annotations

import json
import subprocess

import pytest

# The module writes to ``systemd.services`` and ``systemd.timers``; a bare
# evalModules call needs those option trees to exist.
_STUB = """
  stub = { lib, ... }: {
    options.systemd.services = lib.mkOption {
      type = lib.types.attrsOf (lib.types.attrsOf lib.types.anything);
      default = { };
    };
    options.systemd.timers = lib.mkOption {
      type = lib.types.attrsOf (lib.types.attrsOf lib.types.anything);
      default = { };
    };
  };
"""


def _eval_module(settings: str, extra: str = "") -> dict:
    """Evaluate the module with ``settings`` and return the renderable result."""

    expr = f"""
      let
        flake = builtins.getFlake (toString ./.);
        nixpkgs = flake.inputs.nixpkgs;
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        {_STUB}
        evaled = nixpkgs.lib.evalModules {{
          modules = [
            flake.nixosModules.default
            stub
            {{
              _module.args.pkgs = pkgs;
              services.python-tofu = {{
                enable = true;
                {extra}
                settings = {{ {settings} }};
              }};
            }}
          ];
        }};
        svc = evaled.config.systemd.services.python-tofu;
        timer = evaled.config.systemd.timers.python-tofu or null;
      in
      {{
        exec = svc.serviceConfig.ExecStart;
        execPre = builtins.concatStringsSep " " svc.serviceConfig.ExecStartPre;
        cache = svc.environment.TF_PLUGIN_CACHE_DIR;
        hasTofu = builtins.any (p: toString p == toString pkgs.opentofu) svc.path;
        remain = svc.serviceConfig.RemainAfterExit;
        wantedBy = svc.wantedBy;
        timer = timer == null;
        timerCalendar = if timer == null then null else timer.timerConfig.OnCalendar;
        timerPersistent = if timer == null then null else timer.timerConfig.Persistent;
        timerWantedBy = if timer == null then null else timer.wantedBy;
      }}
    """
    result = subprocess.run(
        ["nix", "eval", "--impure", "--json", "--expr", expr],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


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
def test_home_module_defaults_to_flake_package() -> None:
    expr = """
      let
        flake = builtins.getFlake (toString ./.);
        nixpkgs = flake.inputs.nixpkgs;
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        stub = { lib, ... }: {
          options.home.packages = lib.mkOption {
            type = lib.types.listOf lib.types.package;
            default = [ ];
          };
        };
        evaled = nixpkgs.lib.evalModules {
          modules = [
            flake.homeManagerModules.default
            stub
            {
              _module.args.pkgs = pkgs;
              programs.python-tofu.enable = true;
            }
          ];
        };
        packages = evaled.config.home.packages;
      in
        builtins.length packages == 1
        && builtins.head packages == flake.packages.x86_64-linux.default
    """
    result = subprocess.run(
        ["nix", "eval", "--impure", "--expr", expr],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "true"


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


@pytest.mark.nix
def test_module_accepts_preflight_and_reconciliation_commands() -> None:
    """The module must be able to run the commands the CLI ships."""

    for command in ("doctor", "prune", "limits"):
        config = _eval_module(f'command = "{command}"; workdir = "/tmp/w";')
        assert command in config["exec"]


@pytest.mark.nix
def test_module_rejects_interactive_apis_command() -> None:
    """``apis`` is an inspection command, not a reconciliation step."""

    expr = (
        """
      let
        flake = builtins.getFlake (toString ./.);
        nixpkgs = flake.inputs.nixpkgs;
        """
        + _STUB
        + """
        evaled = nixpkgs.lib.evalModules {
          modules = [
            flake.nixosModules.default
            stub
            {
              _module.args.pkgs = nixpkgs.legacyPackages.x86_64-linux;
              services.python-tofu = {
                enable = true;
                settings.command = "apis";
              };
            }
          ];
        };
      in evaled.config.systemd.services.python-tofu.serviceConfig.ExecStart
    """
    )
    result = subprocess.run(
        ["nix", "eval", "--impure", "--expr", expr],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "apis" in result.stderr


@pytest.mark.nix
def test_module_routes_flags_to_the_commands_that_accept_them() -> None:
    """``limits`` takes --config but not --workdir/--stack-name."""

    limits = _eval_module(
        'command = "limits"; config = "/tmp/infra.py"; workdir = "/tmp/w"; stackName = "prod";'
    )
    assert "--config=/tmp/infra.py" in limits["exec"]
    assert "--workdir" not in limits["exec"]
    assert "--stack-name" not in limits["exec"]

    plan = _eval_module(
        'command = "plan"; config = "/tmp/infra.py"; workdir = "/tmp/w"; '
        'stackName = "prod"; limits = "warn"; usage = "live"; '
        'varFile = "/tmp/prod.tfvars"; prune = true;',
        extra='schedule = "daily";',
    )
    for flag in (
        "--workdir=/tmp/w",
        "--stack-name=prod",
        "--limits=warn",
        "--usage=live",
        "--var-file=/tmp/prod.tfvars",
        "--prune",
    ):
        assert flag in plan["exec"]

    # --no-prune is the explicit opt-out, not the absence of the flag.
    no_prune = _eval_module('command = "apply"; workdir = "/tmp/w"; prune = false;')
    assert "--no-prune" in no_prune["exec"]


@pytest.mark.nix
def test_module_provides_toolchain_and_plugin_cache() -> None:
    config = _eval_module('command = "plan"; workdir = "/tmp/w";')
    assert config["hasTofu"] is True
    assert config["cache"] == "/tmp/w/.tofu-plugins"
    assert ".tofu-plugins" in config["execPre"]


@pytest.mark.nix
def test_module_boot_unit_stays_active() -> None:
    boot = _eval_module('command = "render"; workdir = "/tmp/w";')
    assert boot["remain"] is True
    assert boot["wantedBy"] == ["multi-user.target"]
    assert boot["timer"] is True


@pytest.mark.nix
def test_module_scheduled_unit_is_retriggerable() -> None:
    scheduled = _eval_module('command = "plan"; workdir = "/tmp/w";', extra='schedule = "daily";')
    # A timer cannot start a unit that is still active.
    assert scheduled["remain"] is False
    assert scheduled["wantedBy"] == []
    assert scheduled["timer"] is False
    assert scheduled["timerCalendar"] == "daily"
    assert scheduled["timerPersistent"] is True
    assert scheduled["timerWantedBy"] == ["timers.target"]
