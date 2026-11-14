{ config, lib, pkgs, ... }:

let
  cfg = config.services.python-tofu;

  # The CLI accepts different flags per subcommand, and Typer rejects unknown
  # options. Build argv from these sets instead of passing everything to every
  # command (e.g. ``limits`` accepts --config but not --workdir).
  stackCommands = [ "render" "init" "validate" "doctor" "plan" "apply" "destroy" "prune" ];
  workdirCommands = stackCommands ++ [ "output" ];
  limitCommands = [ "render" "init" "validate" "doctor" "plan" "apply" "destroy" ];
  usageCommands = stackCommands ++ [ "limits" ];
  stackNameCommands = workdirCommands;
  varFileCommands = [ "plan" "apply" "destroy" ];
  pruneCommands = [ "plan" "apply" ];
  configCommands = workdirCommands ++ [ "limits" ];

  accepts = commands: builtins.elem cfg.settings.command commands;

  workdir = lib.removeSuffix "/" (toString cfg.settings.workdir);
  pluginCacheDir = "${workdir}/.tofu-plugins";

  commandArgs =
    [ "${cfg.package}/bin/python-tofu" cfg.settings.command ]
    ++ lib.optionals (accepts configCommands) (
      lib.optional (cfg.settings.config != null) "--config=${toString cfg.settings.config}"
    )
    ++ lib.optionals (accepts workdirCommands) [ "--workdir=${workdir}" ]
    ++ lib.optionals (accepts stackNameCommands) (
      lib.optional (cfg.settings.stackName != null) "--stack-name=${cfg.settings.stackName}"
    )
    ++ lib.optionals (accepts limitCommands) (
      lib.optional (cfg.settings.limits != null) "--limits=${cfg.settings.limits}"
    )
    ++ lib.optionals (accepts usageCommands) (
      lib.optional (cfg.settings.usage != null) "--usage=${cfg.settings.usage}"
    )
    ++ lib.optionals (accepts varFileCommands) (
      lib.optional (cfg.settings.varFile != null) "--var-file=${toString cfg.settings.varFile}"
    )
    ++ lib.optionals (accepts pruneCommands) (
      lib.optional (cfg.settings.prune != null)
        (if cfg.settings.prune then "--prune" else "--no-prune")
    )
    ++ cfg.settings.extraArgs;
in
{

  options.services.python-tofu = {
    enable = lib.mkEnableOption "the python-tofu infrastructure service";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.python-tofu;
      defaultText = lib.literalExpression "pkgs.python-tofu";
      description = "python-tofu package to invoke.";
    };

    tofuPackage = lib.mkOption {
      type = lib.types.package;
      default = pkgs.opentofu;
      defaultText = lib.literalExpression "pkgs.opentofu";
      description = ''
        OpenTofu package placed on the unit's PATH. Ignored only when a
        ``--binary`` path is supplied through ``settings.extraArgs``.
      '';
    };

    environment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = ''
        Environment variables for the service. Values are world-readable Nix
        store data: use paths (such as ``/run/agenix/gcloud-auth``) rather than
        secret contents.
      '';
    };

    environmentFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      example = "/run/agenix/python-tofu.env";
      description = ''
        File read by systemd as ``KEY=VALUE`` pairs before the service starts.
        Use it for secrets (agenix, sops-nix, ``systemd.credentials`` paths)
        instead of putting values in ``environment``.
      '';
    };

    schedule = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "daily";
      description = ''
        systemd ``OnCalendar`` expression. When set, a
        ``python-tofu.timer`` runs the service on that schedule instead of once
        at boot. Leave null for the boot-time oneshot behaviour.
      '';
    };

    settings = {
      command = lib.mkOption {
        type = lib.types.enum [
          "render"
          "init"
          "validate"
          "doctor"
          "plan"
          "apply"
          "destroy"
          "output"
          "prune"
          "limits"
        ];
        default = "render";
        description = ''
          python-tofu subcommand to run. ``apis`` is intentionally excluded: it
          is an interactive inspection command, not a reconciliation step.
        '';
      };

      config = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = "Python infrastructure module to load (sets --config).";
      };

      workdir = lib.mkOption {
        type = lib.types.str;
        default = "/var/lib/python-tofu";
        description = ''
          Working directory for rendered HCL and state. Must be writable by the
          service; a path literal would be copied into the read-only Nix store,
          so this option takes a string.
        '';
      };

      stackName = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "State name (sets --stack-name); defaults to the config file stem.";
      };

      limits = lib.mkOption {
        type = lib.types.nullOr (lib.types.enum [ "error" "warn" "off" ]);
        default = null;
        description = "Provider limit enforcement (sets --limits). Default: the stack or policy default.";
      };

      usage = lib.mkOption {
        type = lib.types.nullOr (lib.types.enum [ "stack" "live" ]);
        default = null;
        description = "Usage measurement mode (sets --usage). Default: stack.";
      };

      varFile = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = "Extra tfvars file for plan/apply/destroy (sets --var-file).";
      };

      prune = lib.mkOption {
        type = lib.types.nullOr lib.types.bool;
        default = null;
        description = ''
          Delete live resources the stack does not declare (sets --prune or
          --no-prune, plan/apply only). Null leaves the decision to the stack.
        '';
      };

      extraArgs = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Extra CLI arguments passed to python-tofu.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.python-tofu = {
      description = "python-tofu infrastructure service";
      wantedBy = lib.optional (cfg.schedule == null) "multi-user.target";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];

      # The CLI shells out to `tofu`; without this the unit cannot find it even
      # though the Python package is self-contained.
      path = [ cfg.tofuPackage ];

      environment = {
        CHECKPOINT_DISABLE = "1";
        TF_PLUGIN_CACHE_DIR = lib.mkDefault pluginCacheDir;
      } // cfg.environment;

      serviceConfig = {
        Type = "oneshot";
        # A timer cannot retrigger a unit that stays active, so only the
        # boot-time shape keeps RemainAfterExit.
        RemainAfterExit = cfg.schedule == null;
        StateDirectory = "python-tofu";
        ExecStartPre = [
          "${pkgs.coreutils}/bin/mkdir -p ${lib.escapeShellArg pluginCacheDir}"
        ];
        ExecStart = lib.escapeShellArgs commandArgs;
        EnvironmentFile = lib.optional (cfg.environmentFile != null) cfg.environmentFile;
        ReadWritePaths = [ "-${workdir}" ];
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
      };
    };

    systemd.timers.python-tofu = lib.mkIf (cfg.schedule != null) {
      description = "python-tofu infrastructure reconciliation";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.schedule;
        Persistent = true;
      };
    };
  };

}
