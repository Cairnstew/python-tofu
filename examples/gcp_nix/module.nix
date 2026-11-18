# The same stack as examples/gcp_bootstrap/infra.py, authored in Nix.
#
# Use it with the flake helper:
#
#   python-tofu.lib.evalStack { modules = [ ./module.nix ]; }
#
# or in a NixOS configuration:
#
#   services.python-tofu.stackFile = ./module.nix;
#
# Sections are keyed by a local name. The key fills the resource identity field
# (`projects` -> project_id, `buckets`/`pubsub_topics` -> name, and so on).
{ ... }:
{
  provider = {
    project = "example-bootstrap";
    region = "europe-west1";
    default_labels.managed-by = "python-tofu";
  };

  backend = {
    kind = "local";
    path = "terraform.tfstate";
  };

  projects.example-bootstrap = {
    name = "Example Bootstrap";
    auto_create_network = false;
    labels.environment = "dev";
  };

  apis = {
    cloudresourcemanager = {
      project = "example-bootstrap";
      service = "cloudresourcemanager.googleapis.com";
    };
    iam = {
      project = "example-bootstrap";
      service = "iam.googleapis.com";
    };
    storage = {
      project = "example-bootstrap";
      service = "storage.googleapis.com";
    };
  };

  service_accounts.ci-runner = {
    project = "example-bootstrap";
    display_name = "CI runner";
    description = "Used by CI to publish build artifacts";
    roles = [
      "roles/iam.serviceAccountUser"
      "roles/storage.admin"
    ];
  };

  service_account_iam_members.ci-token-creator = {
    service_account = "ci-runner";
    role = "roles/iam.serviceAccountTokenCreator";
    member = "user:alice@example.com";
  };

  buckets.example-bootstrap-artifacts = {
    project = "example-bootstrap";
    location = "EU";
    versioning = true;
    labels.environment = "dev";
  };
}
