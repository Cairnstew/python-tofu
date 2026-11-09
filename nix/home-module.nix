{ config, lib, pkgs, ... }:

let
  cfg = config.programs.python-tofu;
in

{

  options.programs.python-tofu = {
    enable = lib.mkEnableOption "python-tofu home-manager integration";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.python-tofu;
      defaultText = lib.literalExpression "pkgs.python-tofu";
      description = "Package to add to the user session";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };

}
