{ config, lib, pkgs, ... }:

let
  cfg = config.services.python-tofu;

  commandArgs =
    [ "${cfg.package}/bin/python-tofu" cfg.settings.command ]
    ++ lib.optional (cfg.settings.config != null) "--config=${toString cfg.settings.config}"
    ++ [ "--workdir=${toString cfg.settings.workdir}" ]
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

    settings = {
      command = lib.mkOption {
        type = lib.types.enum [ "render" "init" "validate" "plan" "apply" "destroy" "output" ];
        default = "render";
        description = "python-tofu subcommand to run.";
      };

      config = lib.mkOption {
        type = lib.types.nullOr lib.types.path;
        default = null;
        description = "Python infrastructure module to load (sets --config).";
      };

      workdir = lib.mkOption {
        type = lib.types.path;
        default = "/var/lib/python-tofu";
        description = "Working directory for rendered HCL and state.";
      };

      extraArgs = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Extra CLI arguments passed to python-tofu.";
      };
    };

    environment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = ''
        Environment variables for the service, such as
        GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_PROJECT.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.python-tofu = {
      description = "python-tofu infrastructure service";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        StateDirectory = "python-tofu";
        ExecStart = lib.escapeShellArgs commandArgs;
        Environment = lib.mapAttrsToList (name: value: "${name}=${value}") cfg.environment;
        ReadWritePaths = [ "-${toString cfg.settings.workdir}" ];
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
      };
    };
  };

}
