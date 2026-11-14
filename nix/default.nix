{ pkgs, pythonSet, workspace, pyproject-nix }:

let
  inherit (pkgs.callPackages pyproject-nix.build.util { }) mkApplication;
  venv = pythonSet.mkVirtualEnv "app-env" workspace.deps.default;
  versions = import ./provider-versions.nix;
in

(mkApplication {
  inherit venv;
  package = pythonSet."python-tofu";
}).overrideAttrs (old: {
  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ pkgs.makeWrapper ];

  postInstall = (old.postInstall or "") + ''
    # Typer can only show the completion for the detected shell, so generate all
    # three from the same templates with the venv interpreter (system Python has
    # no typer on its path).
    ${venv}/bin/python ${./gen-completions.py} "$out"

    # Nix owns the provider version. The app reads it from the environment, so
    # the rendered constraint and the mirrored provider cannot drift apart.
    mv "$out/bin/python-tofu" "$out/bin/.python-tofu-unwrapped"
    makeWrapper "$out/bin/.python-tofu-unwrapped" "$out/bin/python-tofu" \
      --set PYTHON_TOFU_GOOGLE_PROVIDER_VERSION "${versions.google}"
  '';
})
