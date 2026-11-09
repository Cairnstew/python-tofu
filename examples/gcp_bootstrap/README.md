# GCP bootstrap example

This stack creates:

- a `google_project`
- three enabled APIs
- a `ci-runner` service account with two project roles
- a versioned, private GCS bucket

## Prerequisites

1. Authenticate Application Default Credentials:

   ```bash
   gcloud auth application-default login
   ```

   Or set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account key that can
   create projects and buckets.

2. A billing account, if the project should be billable. Add
   `billing_account="XXXXXX-XXXXXX-XXXXXX"` to `GcpProject`.

## Render and plan

```bash
python-tofu render --config examples/gcp_bootstrap/infra.py --workdir .tofu/example
python-tofu plan   --config examples/gcp_bootstrap/infra.py --workdir .tofu/example
```

The plan summary is printed after `tofu plan`; pass `--json` for machine
consumption.

## Apply

```bash
python-tofu apply --config examples/gcp_bootstrap/infra.py --workdir .tofu/example
```

Destroy when finished:

```bash
python-tofu destroy --config examples/gcp_bootstrap/infra.py --workdir .tofu/example
```

> Creating a project requires organization/folder permissions. If you only have
> access to an existing project, remove the `projects` entry, add the project ID
> to `external_projects`, and point the resources at it.
