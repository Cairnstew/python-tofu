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

          # Editable environment for `nix develop`: `python-tofu` imports from
          # $REPO_ROOT/src and every dependency group (pytest, ruff, mypy, ...)
          # comes from the same uv.lock as CI.
          devVenv = editablePythonSet.mkVirtualEnv "dev-env" workspace.deps.all;

          # Read-only environment for `nix flake check`. The source is a store
          # path here, so use the non-editable package build instead.
          checkVenv = pythonSet.mkVirtualEnv "check-env" workspace.deps.all;
        in
        {
          inherit pythonSet editablePythonSet python pkgs devVenv checkVenv;
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

      # Format Nix files with `nix fmt`; the `format` check uses the same tool.
      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixpkgs-fmt);

      devShells = forAllSystems (system:
        let
          p = pythonSets.${system};
          inherit (p) pkgs python;

          # Shared environment. `nix develop` is impure, so host tooling (nix,
          # direnv, editors) stays on PATH; these packages are only additions.
          devPackages = [
            p.devVenv
            pkgs.uv
            pkgs.opentofu
            pkgs.just
            pkgs.pre-commit
            pkgs.nixpkgs-fmt
            pkgs.git
            pkgs.gh
            pkgs.curl
            pkgs.jq
          ];

          shellHook = ''
            unset PYTHONPATH
            export REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")

            # Cache providers inside the repo so repeated `tofu init` is fast
            # and nothing leaks into the user's home. Gitignored via `.cache/`.
            export TOFU_PLUGIN_CACHE_DIR="$REPO_ROOT/.cache/tofu/plugins"
            mkdir -p "$TOFU_PLUGIN_CACHE_DIR"
            export CHECKPOINT_DISABLE=1

            # Install the pre-commit hook once per clone. Never let a missing
            # network or bare worktree block entering the shell.
            if [ -d "$REPO_ROOT/.git" ] && [ ! -f "$REPO_ROOT/.git/hooks/pre-commit" ]; then
              pre-commit install >/dev/null 2>&1 || true
            fi
          '';

          devShell = pkgs.mkShell {
            packages = devPackages;
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = "${python.interpreter}";
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = shellHook + ''
              echo "python-tofu dev shell — Python 3.12 + tofu $(tofu version | head -n1 | cut -d' ' -f2)"
              echo "  just check        lint, typecheck, tests, nix flake check"
              echo "  just lint-fix     apply ruff fixes and formatting"
              echo "  nix fmt           format .nix files"
              echo "  nix flake check   every check CI runs"
              echo "  python-tofu --help"
            '';
          };
        in
        {
          default = devShell;
          dev = devShell;

          # Only what `uv add` / `uv lock` / `uv lock --upgrade` need. Kept
          # separate because it deliberately does not pin the Nix virtualenv.
          bootstrap = pkgs.mkShell {
            packages = [ pkgs.python312 pkgs.uv pkgs.git ];
            env = {
              UV_PYTHON = "${pkgs.python312.interpreter}";
              UV_PYTHON_DOWNLOADS = "never";
              UV_NO_SYNC = "1";
            };
            shellHook = ''
              echo "python-tofu bootstrap shell — edit pyproject.toml, then:"
              echo "  uv add <package> && uv lock"
              echo "  uv lock --upgrade"
            '';
          };

          # Opt-in shell for live GCP work. The SDK is large, so it is not in
          # the default shell; `python-tofu` itself only needs the Python deps.
          cloud = pkgs.mkShell {
            packages = devPackages ++ [ pkgs.google-cloud-sdk ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = "${python.interpreter}";
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = shellHook + ''
              echo "python-tofu cloud shell — google-cloud-sdk on PATH"
            '';
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

          render-test-example = pkgs.runCommand "render-test-example"
            {
              nativeBuildInputs = [ self.packages.${system}.default pkgs.opentofu ];
            } ''
            python-tofu render \
              --config ${./examples/gcp_test_infra/stack.py} \
              --workdir "$out" > /dev/null
            grep -q 'google_pubsub_topic' "$out/main.tf"
            grep -q 'google_storage_bucket' "$out/main.tf"
            tofu fmt -check -recursive "$out"
          '';

          # The checks below run the same locked dev toolchain as the dev shell,
          # so `nix flake check` locally covers everything CI runs separately.
          lint = pkgs.runCommand "lint"
            {
              nativeBuildInputs = [ p.checkVenv ];
            } ''
            cd ${./.}
            export PYTHONDONTWRITEBYTECODE=1
            export RUFF_CACHE_DIR="$TMPDIR/ruff-cache"
            ruff check --no-cache src tests
            ruff format --check src tests
            touch "$out"
          '';

          typecheck = pkgs.runCommand "typecheck"
            {
              nativeBuildInputs = [ p.checkVenv ];
            } ''
            cd ${./.}
            export PYTHONDONTWRITEBYTECODE=1
            mypy --cache-dir "$TMPDIR/mypy-cache" src
            touch "$out"
          '';

          unit-tests = pkgs.runCommand "unit-tests"
            {
              nativeBuildInputs = [ p.checkVenv ];
            } ''
            cd ${./.}
            export HOME="$TMPDIR"
            export PYTHONDONTWRITEBYTECODE=1
            pytest tests/unit -q -p no:cacheprovider --no-header
            touch "$out"
          '';

          integration-tests = pkgs.runCommand "integration-tests"
            {
              nativeBuildInputs = [ p.checkVenv ];
            } ''
            cd ${./.}
            export HOME="$TMPDIR"
            export PYTHONDONTWRITEBYTECODE=1
            pytest tests/integration -q -p no:cacheprovider --no-header
            touch "$out"
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
