# Phase 2 of the live prune test.
#
# The provider project is the throwaway project from phase 1. Prune only looks
# at `provider.project`, which is exactly why this is a second stack: running it
# against the host project would sweep the host's buckets.
#
#   python-tofu apply --config examples/org_projects/test-project.nix \
#     --workdir .tofu/pt-test-project --auto-approve
#
# Then create a stray bucket and watch prune find it:
#   gcloud auth activate-service-account --key-file=/run/agenix/gcloud-auth
#   gcloud storage buckets create gs://python-tofu-prune-496517-stray \
#     --project python-tofu-prune-496517 --location=EU
#
#   python-tofu prune --config examples/org_projects/test-project.nix \
#     --workdir .tofu/pt-test-project                     # dry run
#   python-tofu prune --config examples/org_projects/test-project.nix \
#     --workdir .tofu/pt-test-project --apply             # delete
#
# `prune --apply` and `apply --prune` never touch the real state backend: they
# adopt each bucket into a local scratch module and run `tofu destroy`.
{ ... }:
{
  name = "pt-test-project";

  provider = {
    project = "python-tofu-prune-496517";
    region = "europe-west1";
    credentials = "/run/agenix/gcloud-auth";
  };

  backend = {
    kind = "local";
    path = "terraform.tfstate";
  };

  buckets.python-tofu-prune-496517-artifacts = {
    project = "python-tofu-prune-496517";
    location = "EU";
    force_destroy = true; # pruning a bucket deletes its objects
  };

  # Buckets only. Service accounts stay behind the two-key gate
  # (prune.include_service_accounts + --allow-service-accounts).
  prune = {
    enabled = true;
    sections = [ "buckets" ];
  };
}
