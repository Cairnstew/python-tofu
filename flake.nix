{
  description = "Typed Python DSL and OpenTofu wrapper for GCP infrastructure";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { self
    , nixpkgs
    , uv2nix
    , pyproject-nix
    , pyproject-build-systems
    , ...
    }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;

      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      editableOverlay = workspace.mkEditablePyprojectOverlay {
        root = "$REPO_ROOT";
      };

      # Hatchling's editable wheel builder imports the `editables` helper at
      # build time. nixpkgs does not propagate it, so add it explicitly.
      buildSystemOverrides = final: prev: {
        hatchling = prev.hatchling.overrideAttrs (old: {
          propagatedBuildInputs = (old.propagatedBuildInputs or [ ]) ++ [ final.editables ];
        });
      };

      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python312;

          baseSet = pkgs.callPackage pyproject-nix.build.packages {
            inherit python;
          };

          pythonSet = baseSet.overrideScope (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.wheel
              buildSystemOverrides
              overlay
            ]
          );

          editablePythonSet = pythonSet.overrideScope editableOverlay;
        in
        {
          inherit pythonSet editablePythonSet python pkgs;
        }
      );
    in
    {
      packages = forAllSystems (
        system:
        let p = pythonSets.${system}; in
        {
          default = p.pkgs.callPackage ./nix/default.nix {
            inherit (p) pythonSet pkgs;
            inherit workspace pyproject-nix;
          };
        }
      );

      apps = forAllSystems (system:
        {
          default = {
            type = "app";
            program = "${self.packages.${system}.default}/bin/python-tofu";
            meta = {
              description = "Typed Python DSL and CLI wrapper for OpenTofu on GCP";
            };
          };
        }
      );

      devShells = forAllSystems (system:
        let
          p = pythonSets.${system};
          virtualenv = p.editablePythonSet.mkVirtualEnv "dev-env" workspace.deps.all;
        in
        {
          default = p.pkgs.mkShell {
            packages = [ virtualenv p.pkgs.uv p.pkgs.opentofu p.pkgs.jq ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = "${p.python.interpreter}";
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };

          bootstrap = p.pkgs.mkShell {
            packages = [ p.pkgs.python312 p.pkgs.uv ];
          };
        }
      );

      overlays.default = final: prev: {
        python-tofu = pythonSets.${final.stdenv.hostPlatform.system}.pythonSet."python-tofu";
      };

      nixosModules.default = { pkgs, ... }: {
        imports = [ ./nix/module.nix ];
        services.python-tofu.package = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      };

      homeManagerModules.default = { pkgs, ... }: {
        imports = [ ./nix/home-module.nix ];
        programs.python-tofu.package =
          lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      };

      checks = forAllSystems (system:
        let
          p = pythonSets.${system};
          pkgs = p.pkgs;
          pkg = p.pythonSet."python-tofu";
        in
        {
          build = pkg;

          venv = p.pythonSet.mkVirtualEnv "app-env" { python-tofu = [ ]; };

          format = pkgs.runCommand "check-format"
            {
              nativeBuildInputs = [ pkgs.nixpkgs-fmt ];
            } ''
            nixpkgs-fmt --check ${./.}
            touch "$out"
          '';

          app-help = pkgs.runCommand "app-help"
            {
              nativeBuildInputs = [ self.packages.${system}.default ];
            } ''
            python-tofu --help > "$out" 2>&1
            grep -q "Usage" "$out" || {
              echo "FAIL: --help did not produce Usage output"
              exit 1
            }
          '';

          render-example = pkgs.runCommand "render-example"
            {
              nativeBuildInputs = [ self.packages.${system}.default pkgs.opentofu ];
            } ''
            python-tofu render \
              --config ${./examples/gcp_bootstrap/infra.py} \
              --workdir "$out" > /dev/null
            grep -q 'google_storage_bucket' "$out/main.tf"
            tofu fmt -check -recursive "$out"
          '';

          render-clean-example = pkgs.runCommand "render-clean-example"
            {
              nativeBuildInputs = [ self.packages.${system}.default pkgs.opentofu ];
            } ''
            python-tofu render \
              --config ${./examples/gcp_clean}/stack.py \
              --workdir "$out" > /dev/null
            grep -q 'google_storage_bucket' "$out/main.tf"
            grep -q 'google_project_iam_member' "$out/main.tf"
            tofu fmt -check -recursive "$out"
          '';

          module-eval =
            let
              stub = { lib, ... }: {
                options.systemd.services = lib.mkOption {
                  type = lib.types.attrsOf (lib.types.attrsOf lib.types.anything);
                  default = { };
                };
              };
              evaled = lib.evalModules {
                modules = [
                  ./nix/module.nix
                  stub
                  {
                    _module.args.pkgs = pkgs;
                    services.python-tofu.enable = true;
                    services.python-tofu.package = pkgs.hello;
                  }
                ];
              };
              settings = evaled.config.services.python-tofu.settings;
            in
            if builtins.typeOf settings.extraArgs == "list" then
              pkgs.writeText "module-eval" (builtins.toJSON settings)
            else
              throw "module-eval: services.python-tofu.settings.extraArgs is not a list";

          # The Home Manager output binds the package from this flake, so
          # `programs.python-tofu.enable = true` works without the overlay.
          # Evaluate it here; a bare `import ./nix/home-module.nix` would fall
          # back to `pkgs.python-tofu` and fail evaluation.
          home-module-eval =
            let
              stub = { lib, ... }: {
                options.home.packages = lib.mkOption {
                  type = lib.types.listOf lib.types.package;
                  default = [ ];
                };
              };
              evaled = lib.evalModules {
                modules = [
                  self.homeManagerModules.default
                  stub
                  {
                    _module.args.pkgs = pkgs;
                    programs.python-tofu.enable = true;
                  }
                ];
              };
              expected = self.packages.${system}.default;
              packages = evaled.config.home.packages;
            in
            if packages == [ expected ] then
              pkgs.writeText "home-module-eval" (builtins.toJSON (map (p: p.name) packages))
            else
              throw "home-module-eval: programs.python-tofu.package was not defaulted to the flake package";
        }
      );
    };
}
