# Org projects: per-project identities without keys

Two phases, one project, no service-account keys.

```
examples/org_projects/
├── models.py        # frozen dataclasses: ProjectSpec, Identity
├── platform.py      # phase 1 — runs as the org-admin seed key
└── acme_data.py     # phase 2 — runs as the project provisioner (impersonation)
```

## Why two phases

OpenTofu configures a provider before it creates any resource, so a service
account created in an `apply` cannot be the identity for resources in that same
`apply`. Phase 1 creates the project and its identities; phase 2 operates the
project as the provisioner.

```bash
# 1. as org-admin (agenix /run/agenix/gcloud-auth in GOOGLE_APPLICATION_CREDENTIALS)
python-tofu apply --config examples/org_projects/platform.py --workdir .tofu/platform

# 2. as provisioner@acme-data... (the admin key mints the token)
python-tofu apply --config examples/org_projects/acme_data.py --workdir .tofu/acme-data
```

## What phase 1 creates

- the project (`GcpProject`) and its APIs;
- `provisioner` — `roles/owner` on the project only, used by phase 2;
- `runtime` — the Cloud Run runtime identity, `roles/storage.objectViewer`;
- `google_service_account_iam_member` grants:
  - admin → provisioner `roles/iam.serviceAccountTokenCreator`;
  - provisioner → runtime `roles/iam.serviceAccountUser` (actAs).
- outputs: both emails.

## What phase 2 does

`GcpProvider(impersonate_service_account="provisioner@acme-data...")` makes the
effective identity project-scoped. It creates the bucket and a Cloud Run
service whose runtime identity is `runtime@acme-data...`.

No JSON key is written and no private key enters OpenTofu state. If a
non-GCP consumer genuinely needs a key, add `google_service_account_key` in
phase 1's `extra_files` and encrypt `tofu output -raw ...` into
`.cache/gcp-keys/` — and remember the private key then lives in state.

## Extending to more projects

Add another `ProjectSpec` to `models.py`, then run both phases with a distinct
workdir/`name` per project. Keep `account_id` values distinct across projects:
the renderer's HCL label comes from the account id alone, so two projects
cannot both declare `runtime` in one stack. One project per stack avoids it.

## Nix

The same stack works through `nix/stack.nix`; only the authoring changes:

```nix
service_accounts.provisioner = {
  project = "acme-data";
  display_name = "Acme Data provisioner";
  roles = [ "roles/owner" ];
};

service_account_iam_members.admin_impersonates_provisioner = {
  service_account = "provisioner@acme-data.iam.gserviceaccount.com";
  role = "roles/iam.serviceAccountTokenCreator";
  member = "serviceAccount:org-admin@nixos-infra-496517.iam.gserviceaccount.com";
};
```

## Live prune test (`test-platform.nix` / `test-project.nix`)

This is a throwaway project, not the host project. Prune only inspects
`provider.project`, so phase 2 must target the test project: running it with
`provider.project = "nixos-infra-496517"` would sweep the host's buckets.

```bash
# 1. create the throwaway project (admin key; auto-owner on the new project)
python-tofu apply --config examples/org_projects/test-platform.nix \
  --workdir .tofu/pt-test-platform --auto-approve

# 2. create the declared bucket + enable bucket pruning
python-tofu apply --config examples/org_projects/test-project.nix \
  --workdir .tofu/pt-test-project --auto-approve

# 3. add a bucket the stack does not declare
gcloud auth activate-service-account --key-file=/run/agenix/gcloud-auth
gcloud storage buckets create gs://python-tofu-prune-496517-stray \
  --project python-tofu-prune-496517 --location=EU

# 4. dry run, then delete
python-tofu prune --config examples/org_projects/test-project.nix \
  --workdir .tofu/pt-test-project
python-tofu prune --config examples/org_projects/test-project.nix \
  --workdir .tofu/pt-test-project --apply

# 5. clean up the test project (phase 2 first, then phase 1)
python-tofu destroy --config examples/org_projects/test-project.nix \
  --workdir .tofu/pt-test-project --auto-approve
python-tofu destroy --config examples/org_projects/test-platform.nix \
  --workdir .tofu/pt-test-platform --auto-approve
```

`prune.sections = [ "buckets" ]` is deliberate: service accounts are excluded
unless both `prune.include_service_accounts = true` and
`--allow-service-accounts` are set. `apply --prune` also works and prunes after
a successful apply.
