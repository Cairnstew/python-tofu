"""IAM: service accounts with their role bindings, plus standalone members."""

from python_tofu import ProjectIamMember, ServiceAccount

from .foundation import PROJECT

service_accounts = [
    ServiceAccount(
        project=PROJECT,
        account_id="ci-runner",
        display_name="CI runner",
        description="Publishes build artifacts and refreshes datasets",
        roles=[
            "roles/storage.admin",
            "roles/bigquery.dataEditor",
        ],
    ),
    ServiceAccount(
        project=PROJECT,
        account_id="readonly-audit",
        display_name="Read-only auditor",
        roles=["roles/viewer"],
    ),
]

iam_members = [
    ProjectIamMember(
        project=PROJECT,
        role="roles/viewer",
        member="group:platform@example.com",
    ),
]
