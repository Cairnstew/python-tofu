"""Dataclass specs for the org-project example.

These are authoring sugar only: they carry no validation and no HCL. The two
stack files turn them into the frozen Pydantic models the renderer consumes,
so the guardrails still live in ``python_tofu.providers.gcp.models``.

Keep ``account_id`` values distinct across projects: the renderer derives the
HCL label from the account id alone, so two projects cannot both declare
``runtime`` in one stack. One project per stack (as here) avoids the issue.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Organization that receives the project, and the host project that owns the
#: org-admin seed key (``org-admin@HOST_PROJECT`` in agenix).
ORG_ID = "595961694991"
HOST_PROJECT = "nixos-infra-496517"
BILLING_ACCOUNT = "0X0X0X-0X0X0X-0X0X0X"
STATE_BUCKET = f"{HOST_PROJECT}-tfstate"
ADMIN_EMAIL = f"org-admin@{HOST_PROJECT}.iam.gserviceaccount.com"


def account_email(project_id: str, account_id: str) -> str:
    return f"{account_id}@{project_id}.iam.gserviceaccount.com"


@dataclass(frozen=True)
class Identity:
    """One service account and the project roles it holds."""

    account_id: str
    display_name: str
    description: str = ""
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectSpec:
    """Everything the two phases need to know about one project."""

    project_id: str
    name: str
    region: str = "europe-west1"
    billing_account: str = BILLING_ACCOUNT
    identities: tuple[Identity, ...] = ()


#: One project per trust boundary. Add another ``ProjectSpec`` and run both
#: phases for it; each phase keeps its own workdir and state prefix.
PROJECT = ProjectSpec(
    project_id="acme-data",
    name="Acme Data",
    identities=(
        Identity(
            account_id="provisioner",
            display_name="Acme Data provisioner",
            description="Applies this project's stack through impersonation.",
            roles=("roles/owner",),
        ),
        Identity(
            account_id="runtime",
            display_name="Acme Data runtime",
            description="Runtime identity for Cloud Run workloads.",
            roles=("roles/storage.objectViewer",),
        ),
    ),
)
