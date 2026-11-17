# A standalone .nix stack in the exact GcpStack JSON schema.
#
#   python-tofu render --config examples/gcp_nix/stack.nix --workdir .tofu/nix
#
# This form is evaluated directly by `nix eval --file`, so it needs no
# nixpkgs. For the keyed/composable authoring surface, see module.nix and
# `python-tofu.lib.evalStack`.
#
# A computed Terraform reference is a plain string with an escaped
# interpolation, e.g. "\${google_storage_bucket.bucket_artifacts.name}".
{
  stack = {
    provider = {
      project = "example-bootstrap";
      region = "europe-west1";
      default_labels = {
        managed-by = "python-tofu";
      };
    };

    backend = {
      kind = "local";
      path = "terraform.tfstate";
    };

    projects = [
      {
        project_id = "example-bootstrap";
        name = "Example Bootstrap";
        auto_create_network = false;
        labels = {
          environment = "dev";
        };
      }
    ];

    apis = [
      {
        project = "example-bootstrap";
        service = "cloudresourcemanager.googleapis.com";
      }
      {
        project = "example-bootstrap";
        service = "iam.googleapis.com";
      }
      {
        project = "example-bootstrap";
        service = "storage.googleapis.com";
      }
    ];

    service_accounts = [
      {
        project = "example-bootstrap";
        account_id = "ci-runner";
        display_name = "CI runner";
        description = "Used by CI to publish build artifacts";
        roles = [
          "roles/iam.serviceAccountUser"
          "roles/storage.admin"
        ];
      }
    ];

    buckets = [
      {
        project = "example-bootstrap";
        name = "example-bootstrap-artifacts";
        location = "EU";
        versioning = true;
        labels = {
          environment = "dev";
        };
      }
    ];
  };
}
