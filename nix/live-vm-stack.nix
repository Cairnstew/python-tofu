# Stack for the live VM test of the NixOS module (nix/live-vm.nix).
#
# This is the *throwaway* project. Never point it at the host project: the
# module applies for real, and `prune` only inspects `provider.project`.
#
# The resources use names that the earlier live tests do not own, so a fresh
# state in the VM creates them instead of colliding with existing infra.
{ ... }:
{
  name = "pt-live-vm";

  provider = {
    project = "pt-live-0361f9";
    region = "europe-west1";
    credentials = "/run/agenix/gcloud-auth";
  };

  backend = {
    kind = "local";
    path = "terraform.tfstate";
  };

  buckets.pt-live-0361f9-livevm = {
    project = "pt-live-0361f9";
    location = "EU";
    force_destroy = true;
  };

  service_accounts.livevm-runtime = {
    project = "pt-live-0361f9";
    display_name = "python-tofu live module test";
  };

  # Exercises the `service_account` cross-reference added for project IAM:
  # the member is `${google_service_account.sa_livevm-runtime.email}`, so the
  # grant waits for the account instead of hard-coding the email.
  iam_members.livevm_viewer = {
    project = "pt-live-0361f9";
    role = "roles/viewer";
    service_account = "livevm-runtime";
  };
}
