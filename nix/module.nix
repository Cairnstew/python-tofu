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
  autoApproveCommands = [ "apply" "destroy" ];
  configCommands = workdirCommands ++ [ "limits" ];

  accepts = commands: builtins.elem cfg.settings.command commands;

  # A Nix-declared stack is evaluated *now*, at build time, and written to the
  # store as JSON. The service therefore needs no `nix` binary and no network
  # at activation: it only reads the immutable JSON next to the binary.
  hasStackModule = cfg.stack != null || cfg.stackFile != null;
  stackModules =
    lib.optional (cfg.stack != null) cfg.stack
    ++ lib.optional (cfg.stackFile != null) cfg.stackFile;
  evaluatedStack = lib.evalModules {
    modules = [ ./stack.nix ] ++ stackModules;
    specialArgs = { inherit lib pkgs; };
  };
  stackConfigFile = pkgs.writeText "python-tofu-stack.json" (
    builtins.toJSON { stack = evaluatedStack.config._stack; }
  );
  configFile =
    if hasStackModule && cfg.settings.config != null then
      throw "services.python-tofu: set either `settings.config` or `stack`/`stackFile`, not both"
    else if hasStackModule then
      stackConfigFile
    else
      cfg.settings.config;

  needsNix = configFile != null && lib.hasSuffix ".nix" (toString configFile);

  workdir = lib.removeSuffix "/" (toString cfg.settings.workdir);
  pluginCacheDir = "${workdir}/.tofu-plugins";

  commandArgs =
    [ "${cfg.package}/bin/python-tofu" cfg.settings.command ]
    ++ lib.optionals (accepts configCommands) (
      lib.optional (configFile != null) "--config=${toString configFile}"
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
    ++ lib.optionals (accepts autoApproveCommands && cfg.settings.autoApprove) [
      "--auto-approve"
    ]
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

    nixPackage = lib.mkOption {
      type = lib.types.package;
      default = pkgs.nix;
      defaultText = lib.literalExpression "pkgs.nix";
      description = ''
        Nix package placed on the unit's PATH when ``settings.config`` is a
        ``.nix`` file. Nix-declared ``stack``/``stackFile`` configs are evaluated
        at build time and do not need it.
      '';
    };

    stack = lib.mkOption {
      type = lib.types.nullOr (lib.types.attrsOf lib.types.anything);
      default = null;
      example = lib.literalExpression ''
        {
          provider.project = "my-project";
          buckets.artifacts = { location = "EU"; };
        }
      '';
      description = ''
        Declare the cloud stack in Nix. The value uses the option tree from
        ``nix/stack.nix`` (sections keyed by local name; the key fills the
        resource identity field). It is evaluated at build time and written to
        the store as JSON; the service applies it on activation.

        Mutually exclusive with ``settings.config`` and ``stackFile``.
      '';
    };

    stackFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      example = lib.literalExpression "./infra.nix";
      description = ''
        A Nix module using the ``nix/stack.nix`` options, evaluated at build
        time. Use it instead of ``stack`` when the declaration needs ``imports``
        or ``mkMerge``. Mutually exclusive with ``settings.config`` and ``stack``.
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

      autoApprove = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = ''
          Pass ``--auto-approve`` to ``apply``/``destroy``. Required for an
          unattended rebuild-time apply; off by default so an accidental
          ``command = "apply"`` still stops at the approval prompt.
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
      # though the Python package is self-contained. A `.nix` config also needs
      # `nix` at runtime; a Nix-declared stack is already JSON in the store.
      path = [ cfg.tofuPackage ] ++ lib.optional needsNix cfg.nixPackage;

      # A boot-time oneshot with RemainAfterExit stays active, so a rebuild would
      # otherwise never re-run it. Anchor the unit to the evaluated config and
      # the toolchain: `nixos-rebuild switch` restarts it when any of them moves.
      restartTriggers =
        lib.optional (configFile != null) configFile
        ++ [ cfg.package cfg.tofuPackage ];

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
