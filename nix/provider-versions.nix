# Single source for the toolchain versions the Nix build provides.
#
# The packaged app exports `google` as PYTHON_TOFU_GOOGLE_PROVIDER_VERSION, and
# `checks.provider-version` asserts that the nixpkgs provider mirror satisfies
# it. Only `~> MAJOR.MINOR` is supported; extend the check before using a
# different operator.
{
  google = "~> 7.0";
}
