"""Discovery and deletion planning for the ``projects`` prune section.

The section exists to retire projects the stack no longer declares. Because a
project delete takes everything inside it with it, the tests pin the exemptions
(organization, declared/external/protected projects, the provider project and
the project that owns the active credential) as hard requirements.
"""

from __future__ import annotations

import pytest

from python_tofu.core.hcl import render
from python_tofu.core.models import PruneConfig
from python_tofu.providers.gcp import GCP, GcpProvider, GcpStack
from python_tofu.providers.gcp import prune as gcp_prune
from python_tofu.providers.gcp.models import GCP_PRUNE_SECTIONS, GcpProject

PROJECT = "demo-project"
ORG = "123456789"

LIVE_PROJECTS = [
    {"projectId": "demo-project", "name": "Demo", "lifecycleState": "ACTIVE"},
    {"projectId": "admin-project", "name": "Admin", "lifecycleState": "ACTIVE"},
    {"projectId": "declared-project", "name": "Declared", "lifecycleState": "ACTIVE"},
    {"projectId": "external-project", "name": "External", "lifecycleState": "ACTIVE"},
    {"projectId": "protected-project", "name": "Protected", "lifecycleState": "ACTIVE"},
    {
        "projectId": "stray-project",
        "name": "Stray",
        "lifecycleState": "ACTIVE",
        "labels": {"goog-terraform-provisioned": "true"},
    },
    {"projectId": "manual-project", "name": "Manual", "lifecycleState": "ACTIVE"},
    {
        "projectId": "denied-project",
        "name": "Denied",
        "lifecycleState": "ACTIVE",
        "labels": {"goog-terraform-provisioned": "true"},
    },
    {"projectId": "dying-project", "name": "Dying", "lifecycleState": "DELETE_REQUESTED"},
]


def _stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "provider": GcpProvider(project=PROJECT, region="us-central1"),
        "prune": PruneConfig(enabled=True, protected_projects=("protected-project",)),
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


@pytest.fixture
def inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gcp_prune, "access_token", lambda stack: "token")
    monkeypatch.setattr(gcp_prune, "project_organization", lambda token, project: ORG)
    monkeypatch.setattr(gcp_prune, "list_org_projects", lambda token, org: list(LIVE_PROJECTS))
    monkeypatch.setattr(
        gcp_prune,
        "can_delete_project",
        lambda token, project: project != "denied-project",
    )
    monkeypatch.setattr(
        gcp_prune,
        "credential_identities",
        lambda *args, **kwargs: frozenset({"org-admin@admin-project.iam.gserviceaccount.com"}),
    )


def test_only_undeclared_active_projects_are_planned(inventory: None) -> None:
    stack = _stack(
        projects=[GcpProject(project_id="declared-project", name="Declared")],
        external_projects=["external-project"],
    )

    plan = gcp_prune.discover(stack, ("projects",))

    assert [resource.description for resource in plan.resources] == ["project stray-project"]
    assert plan.resources[0].section == "projects"
    assert plan.resources[0].import_id == "stray-project"


def test_skipped_projects_report_their_reason(inventory: None) -> None:
    stack = _stack(
        projects=[GcpProject(project_id="declared-project", name="Declared")],
        external_projects=["external-project"],
    )

    plan = gcp_prune.discover(stack, ("projects",))

    assert "stray-project" not in " ".join(plan.skipped)
    for expected in (
        "admin-project: protected project",
        "declared-project: protected project",
        "external-project: protected project",
        "protected-project: protected project",
        "demo-project: protected project",
        "manual-project: not provisioned by OpenTofu (created manually)",
        "denied-project: no resourcemanager.projects.delete permission",
        "dying-project: lifecycle state DELETE_REQUESTED",
    ):
        assert expected in plan.skipped


def test_manual_projects_are_skipped_not_deleted(inventory: None) -> None:
    stack = _stack(
        projects=[GcpProject(project_id="declared-project", name="Declared")],
        external_projects=["external-project"],
    )

    plan = gcp_prune.discover(stack, ("projects",))

    assert "manual-project" not in {resource.import_id for resource in plan.resources}
    assert "manual-project: not provisioned by OpenTofu (created manually)" in plan.skipped


def test_projects_without_delete_permission_are_skipped(inventory: None) -> None:
    stack = _stack(
        projects=[GcpProject(project_id="declared-project", name="Declared")],
        external_projects=["external-project"],
    )

    plan = gcp_prune.discover(stack, ("projects",))

    assert "denied-project" not in {resource.import_id for resource in plan.resources}
    assert "denied-project: no resourcemanager.projects.delete permission" in plan.skipped


def test_provisioned_by_tofu_reads_the_attribution_label() -> None:
    assert gcp_prune.provisioned_by_tofu({"labels": {"goog-terraform-provisioned": "true"}})
    assert gcp_prune.provisioned_by_tofu({"labels": {"goog-terraform-provisioned": "True"}})
    assert not gcp_prune.provisioned_by_tofu({"labels": {}})
    assert not gcp_prune.provisioned_by_tofu({})


def test_can_delete_project_asks_for_the_delete_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_post_json(
        url: str, token: str, payload: dict[str, object], headers: object = None
    ) -> dict[str, object]:
        seen.update({"url": url, "payload": payload})
        return {"permissions": ["resourcemanager.projects.get", "resourcemanager.projects.delete"]}

    monkeypatch.setattr(gcp_prune, "post_json", fake_post_json)

    assert gcp_prune.can_delete_project("token", "manual-project")
    assert str(seen["url"]).endswith("/projects/manual-project:testIamPermissions")
    assert seen["payload"] == {"permissions": ["resourcemanager.projects.delete"]}

    monkeypatch.setattr(
        gcp_prune,
        "post_json",
        lambda *args, **kwargs: {"permissions": ["resourcemanager.projects.get"]},
    )
    assert not gcp_prune.can_delete_project("token", "manual-project")


def test_provider_project_is_protected_without_declarations(inventory: None) -> None:
    plan = gcp_prune.discover(_stack(), ("projects",))

    assert "demo-project" not in {resource.import_id for resource in plan.resources}


def test_projects_section_is_explicit_only() -> None:
    implicit = PruneConfig(enabled=True).resolve(GCP_PRUNE_SECTIONS, GCP.prune_explicit_only)
    explicit = PruneConfig(enabled=True, sections=("projects",)).resolve(
        GCP_PRUNE_SECTIONS, GCP.prune_explicit_only
    )

    assert "projects" not in implicit
    assert explicit == ("projects",)


def test_project_without_an_organization_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gcp_prune, "access_token", lambda stack: "token")
    monkeypatch.setattr(gcp_prune, "project_organization", lambda token, project: None)

    plan = gcp_prune.discover(_stack(), ("projects",))

    assert plan.resources == ()
    assert any("not inside an organization" in warning for warning in plan.warnings)


def test_project_block_is_minimal_and_fmt_clean(inventory: None) -> None:
    plan = gcp_prune.discover(_stack(), ("projects",))
    resource = next(item for item in plan.resources if item.import_id == "stray-project")

    text = render(resource.block)

    assert 'project_id      = "stray-project"' in text
    assert 'name            = "Stray"' in text
    assert 'deletion_policy = "DELETE"' in text
    # Only identity fields and the delete policy are configured; everything the
    # adopt step cannot reconstruct is ignored so it never edits the project.
    configured = [
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if " = " in line and "ignore_changes" not in line
    ]
    assert configured == ["project_id", "name", "deletion_policy"]
    for ignored in ("billing_account", "labels", "org_id", "folder_id"):
        assert f'"{ignored}"' in text
    assert text.count("lifecycle") == 1


def test_list_org_projects_walks_folders(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_projects(token: str, parent: str) -> list[dict[str, str]]:
        seen.append(("projects", parent))
        return [{"projectId": parent.replace("/", "-")}]

    def fake_folders(parent: str, token: str) -> list[dict[str, str]]:
        if parent == f"organizations/{ORG}":
            return [{"name": "folders/42"}]
        return []

    monkeypatch.setattr(gcp_prune, "list_projects", fake_projects)
    monkeypatch.setattr(gcp_prune, "list_folders", fake_folders)

    result = gcp_prune.list_org_projects("token", ORG)

    assert {item["projectId"] for item in result} == {
        f"organizations-{ORG}",
        "folders-42",
    }
    assert ("projects", "folders/42") in seen


def test_list_projects_filters_by_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_get_json(
        url: str, token: str, params: dict[str, str], headers: object = None
    ) -> dict[str, object]:
        seen.update({"url": url, "params": params})
        return {"projects": []}

    monkeypatch.setattr(gcp_prune, "get_json", fake_get_json)

    gcp_prune.list_projects("token", f"organizations/{ORG}")

    assert str(seen["url"]).endswith("/v1/projects")
    assert seen["params"] == {
        "filter": f"parent.type:organization parent.id:{ORG}",
    }


def test_project_blocks_are_unique_per_project(inventory: None) -> None:
    stack = _stack(external_projects=["external-project"])

    plan = gcp_prune.discover(stack, ("projects",))

    addresses = [resource.address for resource in plan.resources]
    assert len(addresses) == len(set(addresses))
