# Phase 1 of the live prune test.
#
# Run as the org-admin seed key:
#   python-tofu apply --config examples/org_projects/test-platform.nix \
#     --workdir .tofu/pt-test-platform --auto-approve
#
# Creates a throwaway project inside the org. Phase 2 (test-project.nix)
# targets that project and enables bucket pruning.
{ ... }:
{
  name = "pt-test-platform";

  provider = {
    project = "nixos-infra-496517"; # org-admin key's project
    region = "europe-west1";
    credentials = "/run/agenix/gcloud-auth";
  };

  backend = {
    kind = "local";
    path = "terraform.tfstate";
  };

  projects.python-tofu-prune-496517 = {
    name = "python-tofu prune test";
    org_id = "595961694991";
    billing_account = "01FDB7-83376D-105D8B";
    labels.purpose = "python-tofu-prune-test";
  };

  apis = {
    storage = {
      project = "python-tofu-prune-496517";
      service = "storage.googleapis.com";
    };
    iam = {
      project = "python-tofu-prune-496517";
      service = "iam.googleapis.com";
    };
  };
}
