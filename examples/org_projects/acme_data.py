"""Phase 2: run as the project provisioner through impersonation.

    python-tofu apply --config examples/org_projects/acme_data.py \\
        --workdir .tofu/acme-data

The base credential is still the org-admin key; ``impersonate_service_account``
switches the effective identity to ``provisioner@acme-data...``, which holds
``roles/owner`` on this project only. No service-account key is created.
"""

from models import PROJECT, STATE_BUCKET, account_email

from python_tofu import (
    BackendConfig,
    CloudRunService,
    GcpProvider,
    GcpStack,
    StorageBucket,
)

PROJECT_ID = PROJECT.project_id
PROVISIONER = account_email(PROJECT_ID, "provisioner")
RUNTIME = account_email(PROJECT_ID, "runtime")
REGION = PROJECT.region
# Placeholder: push an image to Artifact Registry (which also needs
# artifactregistry.googleapis.com) or point this at your own registry.
IMAGE = f"{REGION}-docker.pkg.dev/{PROJECT_ID}/apps/api:latest"

stack = GcpStack(
    name=PROJECT_ID,
    provider=GcpProvider(
        project=PROJECT_ID,
        region=REGION,
        impersonate_service_account=PROVISIONER,
    ),
    backend=BackendConfig(kind="gcs", bucket=STATE_BUCKET),
    buckets=[
        StorageBucket(
            project=PROJECT_ID,
            name=f"{PROJECT_ID}-artifacts",
            location="EU",
        )
    ],
    cloud_run_services=[
        CloudRunService(
            project=PROJECT_ID,
            name="acme-data-api",
            image=IMAGE,
            service_account=RUNTIME,
            deletion_protection=False,
        )
    ],
)
