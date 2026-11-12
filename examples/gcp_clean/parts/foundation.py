"""Foundation: provider defaults, the project itself and its APIs.

Every other part imports ``PROJECT`` from here, so there is exactly one place to
rename the project or change region/labels.
"""

from python_tofu import GcpProject, GcpProvider, ProjectApi

PROJECT = "acme-platform"
REGION = "europe-west1"
LOCATION = "EU"

provider = GcpProvider(
    project=PROJECT,
    region=REGION,
    default_labels={"managed-by": "python-tofu", "stack": "platform"},
)

projects = [
    GcpProject(
        project_id=PROJECT,
        name="Acme Platform",
        auto_create_network=False,
        labels={"environment": "prod"},
    ),
]

apis = [
    ProjectApi(project=PROJECT, service=service)
    for service in (
        "cloudresourcemanager.googleapis.com",
        "iam.googleapis.com",
        "storage.googleapis.com",
        "bigquery.googleapis.com",
    )
]
