"""Example stack: bootstrap a GCP project, APIs, service account and bucket.

Run it from the repository root:

    python-tofu plan  --config examples/gcp_bootstrap/infra.py --workdir .tofu/example
    python-tofu apply --config examples/gcp_bootstrap/infra.py --workdir .tofu/example

The example deliberately uses local state. Point ``backend`` at a GCS bucket
once you are ready to share state with a team.
"""

from python_tofu import (
    BackendConfig,
    GcpProject,
    GcpProvider,
    GcpStack,
    ProjectApi,
    ServiceAccount,
    StorageBucket,
)

PROJECT_ID = "example-bootstrap"

stack = GcpStack(
    provider=GcpProvider(
        project=PROJECT_ID,
        region="europe-west1",
        default_labels={"managed-by": "python-tofu"},
    ),
    backend=BackendConfig(kind="local", path="terraform.tfstate"),
    projects=[
        GcpProject(
            project_id=PROJECT_ID,
            name="Example Bootstrap",
            auto_create_network=False,
            labels={"environment": "dev"},
        )
    ],
    apis=[
        ProjectApi(project=PROJECT_ID, service="cloudresourcemanager.googleapis.com"),
        ProjectApi(project=PROJECT_ID, service="iam.googleapis.com"),
        ProjectApi(project=PROJECT_ID, service="storage.googleapis.com"),
    ],
    service_accounts=[
        ServiceAccount(
            project=PROJECT_ID,
            account_id="ci-runner",
            display_name="CI runner",
            description="Used by CI to publish build artifacts",
            roles=["roles/iam.serviceAccountUser", "roles/storage.admin"],
        )
    ],
    buckets=[
        StorageBucket(
            project=PROJECT_ID,
            name=f"{PROJECT_ID}-artifacts",
            location="EU",
            versioning=True,
            labels={"environment": "dev"},
        )
    ],
)
