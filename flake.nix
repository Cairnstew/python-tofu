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

      # The Nix build owns the provider/toolchain versions; the packaged app
      # exports these values and the checks below keep them honest.
      versions = import ./nix/provider-versions.nix;

      # Evaluate the Nix authoring option tree (nix/stack.nix) into the JSON
      # schema the provider's Pydantic models validate. Nix composes; Python
      # still owns validation, limits and HCL.
      evalStack =
        { modules ? [ ]
        , specialArgs ? { }
        }:
        let
          evaluated = lib.evalModules {
            modules = [ ./nix/stack.nix ] ++ modules;
            specialArgs = specialArgs;
          };
        in
        evaluated.config._stack;

      mkStackJson = args: builtins.toJSON { stack = evalStack args; };

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
        let
          p = pythonSets.${system};
          app = p.pkgs.callPackage ./nix/default.nix {
            inherit (p) pythonSet pkgs;
            inherit workspace pyproject-nix;
          };

          # The app plus an OpenTofu build that already carries the mirrored
          # provider. The wrapper points --binary at the sibling `tofu`, so
          # `nix run .#with-tofu` works without anything on the caller's PATH.
          tofu = p.pkgs.opentofu.withPlugins (plugins: [ plugins.hashicorp_google ]);
        in
        {
          default = app;

          with-tofu = p.pkgs.symlinkJoin {
            name = "python-tofu-with-tofu";
            paths = [ app tofu ];
            nativeBuildInputs = [ p.pkgs.makeWrapper ];
            postBuild = ''
              wrapProgram "$out/bin/python-tofu" \
                --set PYTHON_TOFU_BINARY "$out/bin/tofu"
            '';
          };

          # The stack JSON for the live VM test, so the host can inspect it or
          # run `destroy` against the state the VM wrote (shared workdir).
          live-stack = p.pkgs.writeText "python-tofu-live-vm-stack.json" (
            mkStackJson { modules = [ ./nix/live-vm-stack.nix ]; }
          );

          # For `--config ./infra.nix` outside a systemd unit. Nix-declared
          # `services.python-tofu.stack` configs are evaluated at build time and
          # do not need this variant.
          with-tofu-nix = p.pkgs.symlinkJoin {
            name = "python-tofu-with-tofu-nix";
            paths = [ self.packages.${system}.with-tofu p.pkgs.nix ];
            nativeBuildInputs = [ p.pkgs.makeWrapper ];
            postBuild = ''
              wrapProgram "$out/bin/python-tofu" \
                --prefix PATH : ${p.pkgs.nix}/bin
            '';
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

          with-tofu = {
            type = "app";
            program = "${self.packages.${system}.with-tofu}/bin/python-tofu";
            meta = {
              description = "python-tofu with the mirrored hashicorp/google provider and OpenTofu";
            };
          };

          with-tofu-nix = {
            type = "app";
            program = "${self.packages.${system}.with-tofu-nix}/bin/python-tofu";
            meta = {
              description = "with-tofu plus a Nix binary for `.nix` stack configs";
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

      # A flake-input API for authoring stacks elsewhere.
      lib = {
        # Import this path next to a declaration module in `lib.evalModules`.
        stackModule = ./nix/stack.nix;

        inherit evalStack mkStackJson;

        # `pkgs` is explicit because a JSON file is a system-specific derivation.
        mkStackFile = pkgs: name: args:
          pkgs.writeText name (mkStackJson args);
      };

      overlays.default = final: prev: {
        python-tofu = pythonSets.${final.stdenv.hostPlatform.system}.pythonSet."python-tofu";
      };

      nixosModules.default = { lib, pkgs, ... }: {
        imports = [ ./nix/module.nix ];
        services.python-tofu.package =
          lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      };

      # Alias so a flake input can be imported by its own name. `default` stays
      # for backward compatibility.
      nixosModules.python-tofu = self.nixosModules.default;

      # Live end-to-end test of the module (scripts/live-module-vm.sh). Not a
      # flake check: it boots a VM, reads /run/agenix and calls the GCP APIs, so
      # it only runs on demand against the throwaway project.
      nixosConfigurations.tofu-live = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          self.nixosModules.default
          ./nix/live-vm.nix
        ];
      };

      homeManagerModules.default = { lib, pkgs, ... }: {
        imports = [ ./nix/home-module.nix ];
        programs.python-tofu.package =
          lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      };

      homeManagerModules.python-tofu = self.homeManagerModules.default;

      checks = forAllSystems (system:
        let
          p = pythonSets.${system};
          pkgs = p.pkgs;
          pkg = p.pythonSet."python-tofu";
        in
        {
          build = pkg;

          # The self-contained variant must ship both binaries and point the
          # CLI at the sibling `tofu` (which carries the provider mirror).
          with-tofu-wired = pkgs.runCommand "check-with-tofu"
            {
              nativeBuildInputs = [ self.packages.${system}.with-tofu ];
            }
            ''
              test -x ${self.packages.${system}.with-tofu}/bin/tofu
              python-tofu --version > /dev/null
              grep -q "PYTHON_TOFU_BINARY" ${self.packages.${system}.with-tofu}/bin/python-tofu
              touch "$out"
            '';

          # The `.nix`-config variant must keep the sibling `tofu` and add `nix`.
          with-tofu-nix-wired = pkgs.runCommand "check-with-tofu-nix"
            {
              nativeBuildInputs = [ self.packages.${system}.with-tofu-nix ];
            }
            ''
              set -eu
              test -x ${self.packages.${system}.with-tofu-nix}/bin/tofu
              python-tofu --version > /dev/null
              command -v nix > /dev/null
              # The env export lives on the inner wrapper, so search the bin dir.
              grep -Rq "PYTHON_TOFU_BINARY" ${self.packages.${system}.with-tofu-nix}/bin
              touch "$out"
            '';

          # The provider nixpkgs bundles must satisfy the constraint the app
          # renders. When the weekly flake update moves hashicorp/google out of
          # range, this check fails instead of a live `tofu init`.
          provider-version =
            let
              constraint = versions.google;
              mirror = pkgs.opentofu.plugins.hashicorp_google.version;
              # `~> 7.0` means ">= 7.0, < 8.0": only the major has to match.
              matched = builtins.match "~> ([0-9]+)\\.([0-9]+)" constraint;
              expected = if matched == null then null else builtins.elemAt matched 0;
            in
            if expected == null then
              throw "provider-version: unsupported constraint '${constraint}' in nix/provider-versions.nix (use '~> MAJOR.MINOR')"
            else if lib.versions.major mirror == expected then
              pkgs.writeText "provider-version" "${mirror} satisfies ${constraint}\n"
            else
              throw "provider-version: nixpkgs hashicorp/google ${mirror} does not satisfy '${constraint}' from nix/provider-versions.nix";

          # The Python fallback (used outside Nix) must match the Nix value, so
          # a `pip install` and a Nix install render the same constraint.
          provider-version-default =
            pkgs.runCommand "check-provider-version-default"
              {
                nativeBuildInputs = [ p.checkVenv ];
              }
              ''
                got=$(env -u PYTHON_TOFU_GOOGLE_PROVIDER_VERSION python -c '
                from python_tofu.providers.gcp.models import GcpProvider
                from python_tofu.providers.gcp.stack import GcpStack
                print(GcpStack(provider=GcpProvider(project="demo")).google_provider_version)
                ')
                if [ "$got" != "${versions.google}" ]; then
                  echo "FAIL: python default '$got' != '${versions.google}' from nix/provider-versions.nix"
                  exit 1
                fi
                echo "$got" > "$out"
              '';

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

          # Two-phase org example: phase 1 creates the identities and the
          # delegation grants; phase 2 impersonates the project provisioner.
          render-org-example = pkgs.runCommand "render-org-example"
            {
              nativeBuildInputs = [ self.packages.${system}.default pkgs.opentofu ];
            } ''
            python-tofu render \
              --config ${./examples/org_projects}/platform.py \
              --workdir "$out/platform" > /dev/null
            python-tofu render \
              --config ${./examples/org_projects}/acme_data.py \
              --workdir "$out/acme-data" > /dev/null
            grep -q 'google_service_account_iam_member' "$out/platform/main.tf"
            grep -q 'impersonate_service_account' "$out/acme-data/providers.tf"
            tofu fmt -check -recursive "$out"
          '';

          # The Nix option tree is the authoring surface. Evaluate it at check
          # time and assert the keyed sections land in the JSON schema.
          stack-eval =
            let
              stack = evalStack { modules = [ ./examples/gcp_nix/module.nix ]; };
              project = builtins.head stack.projects;
              bucket = builtins.head stack.buckets;
              account = builtins.head stack.service_accounts;
              delegation = builtins.head stack.service_account_iam_members;
            in
            if project.project_id == "example-bootstrap"
              && bucket.name == "example-bootstrap-artifacts"
              && account.account_id == "ci-runner"
              && delegation.role == "roles/iam.serviceAccountTokenCreator"
            then pkgs.writeText "stack-eval" (builtins.toJSON stack)
            else throw "stack-eval: keyed sections did not fill the identity fields";

          # The two live prune-test stacks are Nix-authored and carry the
          # agenix credential path; render both and keep them fmt-clean.
          render-prune-test =
            let
              platform = mkStackJson {
                modules = [ ./examples/org_projects/test-platform.nix ];
              };
              project = mkStackJson {
                modules = [ ./examples/org_projects/test-project.nix ];
              };
            in
            pkgs.runCommand "render-prune-test"
              {
                nativeBuildInputs = [ self.packages.${system}.default pkgs.opentofu ];
              } ''
              mkdir -p "$TMPDIR/platform" "$TMPDIR/project"
              printf '%s' ${lib.escapeShellArg platform} > "$TMPDIR/platform/stack.json"
              printf '%s' ${lib.escapeShellArg project} > "$TMPDIR/project/stack.json"
              python-tofu render \
                --config "$TMPDIR/platform/stack.json" --workdir "$TMPDIR/platform/out" > /dev/null
              python-tofu render \
                --config "$TMPDIR/project/stack.json" --workdir "$TMPDIR/project/out" > /dev/null
              grep -q 'credentials = "/run/agenix/gcloud-auth"' "$TMPDIR/platform/out/providers.tf"
              grep -q 'credentials = "/run/agenix/gcloud-auth"' "$TMPDIR/project/out/providers.tf"
              tofu fmt -check -recursive "$TMPDIR/platform/out" "$TMPDIR/project/out"
              touch "$out"
            '';

          # The strong cross-language check: a Nix-authored stack must render
          # byte-for-byte like the Python example it mirrors. Any schema drift
          # in either authoring surface breaks this.
          render-nix-example =
            let
              stack = mkStackJson { modules = [ ./examples/gcp_nix/module.nix ]; };
            in
            pkgs.runCommand "render-nix-example"
              {
                nativeBuildInputs = [ self.packages.${system}.default pkgs.opentofu ];
              } ''
              mkdir -p "$TMPDIR/nix" "$TMPDIR/python"
              printf '%s' ${lib.escapeShellArg stack} > "$TMPDIR/stack.json"
              python-tofu render --config "$TMPDIR/stack.json" --workdir "$TMPDIR/nix" > /dev/null
              python-tofu render \
                --config ${./examples/gcp_bootstrap/infra.py} \
                --workdir "$TMPDIR/python" > /dev/null
              diff -ru "$TMPDIR/python" "$TMPDIR/nix"
              tofu fmt -check -recursive "$TMPDIR/nix"
              touch "$out"
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
              # `doctor` probes the local OpenTofu binary as part of its
              # toolchain checks, so the tests need a real one on PATH.
              nativeBuildInputs = [ p.checkVenv pkgs.opentofu ];
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

          # `with-tofu` carries the mirrored provider, so init/validate are
          # hermetic. The proxies point at a dead address: a registry lookup
          # fails the check instead of being papered over.
          validate-examples = pkgs.runCommand "validate-examples"
            {
              nativeBuildInputs = [ self.packages.${system}.with-tofu ];
            } ''
            export HOME="$TMPDIR"
            check() {
              name=$1
              config=$2
              workdir="$TMPDIR/$name"
              python-tofu render --config "$config" --workdir "$workdir" > /dev/null
              (
                cd "$workdir"
                export HTTP_PROXY=http://127.0.0.1:0
                export HTTPS_PROXY=http://127.0.0.1:0
                tofu init -backend=false -input=false -no-color > /dev/null
                tofu validate -no-color
              )
            }
            check bootstrap ${./examples/gcp_bootstrap}/infra.py
            check clean ${./examples/gcp_clean}/stack.py
            check test-infra ${./examples/gcp_test_infra}/stack.py
            check org-platform ${./examples/org_projects}/platform.py
            check org-acme ${./examples/org_projects}/acme_data.py
            # The Nix-authored stack is validated by the same provider schema.
            check nix ${pkgs.writeText "nix-stack.json" (mkStackJson {
              modules = [ ./examples/gcp_nix/module.nix ];
            })}
            touch "$out"
          '';

          # The module's promise is argv + state directory + PATH. Evaluate-time
          # tests cover the option shapes; this boots a VM and checks the unit.
          module-vm = pkgs.testers.nixosTest {
            name = "python-tofu-module";
            nodes.machine = { pkgs, ... }: {
              imports = [ self.nixosModules.default ];
              services.python-tofu = {
                enable = true;
                package = pkgs.writeShellScriptBin "python-tofu" ''
                  echo "$@" >> /var/lib/python-tofu/invocations
                  echo "tofu=$(command -v tofu)" >> /var/lib/python-tofu/invocations
                '';
                tofuPackage = pkgs.writeShellScriptBin "tofu" ''
                  echo "OpenTofu v9.9.9"
                '';
                stack = {
                  provider.project = "demo-project";
                  buckets.artifacts = {
                    location = "EU";
                  };
                };
                settings = {
                  command = "plan";
                  workdir = "/var/lib/python-tofu";
                  stackName = "prod";
                  prune = true;
                };
              };
            };
            testScript = ''
              machine.wait_for_unit("python-tofu.service")
              machine.succeed("test -d /var/lib/python-tofu/.tofu-plugins")
              machine.succeed("grep -q -- '--workdir=/var/lib/python-tofu' /var/lib/python-tofu/invocations")
              machine.succeed("grep -q -- '--stack-name=prod' /var/lib/python-tofu/invocations")
              machine.succeed("grep -q -- '--prune' /var/lib/python-tofu/invocations")
              machine.succeed("grep -q 'tofu=.*/tofu' /var/lib/python-tofu/invocations")
              machine.succeed("grep -q 'python-tofu-stack.json' /var/lib/python-tofu/invocations")
              machine.succeed("grep -q 'artifacts' $(sed -n 's/.*--config=\\([^ ]*\\).*/\\1/p' /var/lib/python-tofu/invocations)")
            '';
          };

          module-eval =
            let
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
