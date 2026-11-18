"""Phase 1: run once as the org-admin seed key (agenix ``gcloud-auth``).

    python-tofu apply --config examples/org_projects/platform.py \\
        --workdir .tofu/platform

Creates the project, its APIs, the service accounts and the delegation grants.
Phase 2 (``acme_data.py``) then applies as the project provisioner, so the
org-admin key is only the credential that mints the impersonated token.
"""

from models import (
    ADMIN_EMAIL,
    HOST_PROJECT,
    ORG_ID,
    PROJECT,
    STATE_BUCKET,
    account_email,
)

from python_tofu import (
    BackendConfig,
    GcpProject,
    GcpProvider,
    GcpStack,
    Output,
    ProjectApi,
    ServiceAccount,
    ServiceAccountIamMember,
    ref,
)

PROJECT_ID = PROJECT.project_id
PROVISIONER = account_email(PROJECT_ID, "provisioner")
RUNTIME = account_email(PROJECT_ID, "runtime")

# APIs are also derived from the resources; declaring them makes intent clear.
APIS = (
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
)

stack = GcpStack(
    name="platform",
    provider=GcpProvider(project=HOST_PROJECT, region=PROJECT.region),
    backend=BackendConfig(kind="gcs", bucket=STATE_BUCKET),
    projects=[
        GcpProject(
            project_id=PROJECT_ID,
            name=PROJECT.name,
            org_id=ORG_ID,
            billing_account=PROJECT.billing_account,
            labels={"managed-by": "python-tofu"},
        )
    ],
    apis=[ProjectApi(project=PROJECT_ID, service=service) for service in APIS],
    service_accounts=[
        ServiceAccount(
            project=PROJECT_ID,
            account_id=identity.account_id,
            display_name=identity.display_name,
            description=identity.description or None,
            roles=list(identity.roles),
        )
        for identity in PROJECT.identities
    ],
    service_account_iam_members=[
        # The seed key may mint tokens as the project provisioner ...
        ServiceAccountIamMember(
            service_account=PROVISIONER,
            role="roles/iam.serviceAccountTokenCreator",
            member=ADMIN_EMAIL,
        ),
        # ... and the provisioner may deploy a workload as the runtime account.
        ServiceAccountIamMember(
            service_account=RUNTIME,
            role="roles/iam.serviceAccountUser",
            member=PROVISIONER,
        ),
    ],
    outputs=[
        Output("provisioner_email", ref("google_service_account.sa_provisioner.email")),
        Output("runtime_email", ref("google_service_account.sa_runtime.email")),
    ],
)
