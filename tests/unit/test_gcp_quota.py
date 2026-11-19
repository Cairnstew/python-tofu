"""Quota overrides: the only GCP ceiling the cloud itself enforces.

These tests pin the properties that make the section safe to run unattended:
discovery never writes, a matching value is a no-op, an unknown limit is a
warning rather than a failure, and only declared overrides are touched.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tofu.providers.gcp import GCP, GcpProvider, GcpStack
from python_tofu.providers.gcp import quota as gcp_quota
from python_tofu.providers.gcp.live import GoogleApiError
from python_tofu.providers.gcp.models import QuotaOverride

PROJECT = "demo-project"
SERVICE = "compute.googleapis.com"
METRIC = "compute.googleapis.com/cpus_all_regions"
LIMIT = "/project/region"


def _override(**overrides: object) -> QuotaOverride:
    values: dict[str, object] = {
        "project": PROJECT,
        "service": SERVICE,
        "metric": METRIC,
        "limit": LIMIT,
        "value": 0,
    }
    values.update(overrides)
    return QuotaOverride(**values)  # type: ignore[arg-type]


def _stack(*overrides: QuotaOverride) -> GcpStack:
    return GcpStack(
        provider=GcpProvider(project=PROJECT, region="us-central1"),
        quota_overrides=list(overrides),
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(gcp_quota, "access_token", lambda stack: "token")
    return monkeypatch


def test_limit_path_quotes_both_segments() -> None:
    path = gcp_quota.limit_path(PROJECT, SERVICE, METRIC, LIMIT)
    assert path == (
        "projects/demo-project/services/compute.googleapis.com"
        "/consumerQuotaMetrics/compute.googleapis.com%2Fcpus_all_regions"
        "/limits/%2Fproject%2Fregion"
    )


def test_value_formatting_has_no_trailing_zeros() -> None:
    assert gcp_quota.format_value(0) == "0"
    assert gcp_quota.format_value(1.5) == "1.5"
    assert gcp_quota.format_value(-1) == "-1"


def test_create_when_no_override_exists(api: pytest.MonkeyPatch) -> None:
    api.setattr(gcp_quota, "list_overrides", lambda path, token: [])
    plan = gcp_quota.discover(_stack(_override()))

    assert len(plan.changes) == 1
    change = plan.changes[0]
    assert change.action == "create"
    assert change.desired == "0"
    assert change.current is None
    assert change.handle.startswith("projects/demo-project/services/")


def test_matching_value_is_a_no_op(api: pytest.MonkeyPatch) -> None:
    api.setattr(
        gcp_quota,
        "list_overrides",
        lambda path, token: [{"name": "projects/1/overrides/abc", "overrideValue": "0"}],
    )
    assert gcp_quota.discover(_stack(_override())).empty


def test_update_when_value_differs(api: pytest.MonkeyPatch) -> None:
    api.setattr(
        gcp_quota,
        "list_overrides",
        lambda path, token: [{"name": "projects/1/overrides/abc", "overrideValue": "8"}],
    )
    plan = gcp_quota.discover(_stack(_override(value=0)))

    assert [change.action for change in plan.changes] == ["update"]
    assert plan.changes[0].current == "8"
    assert plan.changes[0].desired == "0"
    assert plan.changes[0].handle == "projects/1/overrides/abc"


def test_unknown_limit_warns_instead_of_failing(api: pytest.MonkeyPatch) -> None:
    def boom(path: str, token: str) -> list[dict[str, object]]:
        raise GoogleApiError("not found", status=404)

    api.setattr(gcp_quota, "list_overrides", boom)
    plan = gcp_quota.discover(_stack(_override()))

    assert plan.empty
    assert any("no such limit" in warning for warning in plan.warnings)


def test_duplicate_declarations_warn_and_keep_the_last(api: pytest.MonkeyPatch) -> None:
    api.setattr(gcp_quota, "list_overrides", lambda path, token: [])
    plan = gcp_quota.discover(_stack(_override(value=4), _override(value=0)))

    assert any("more than once" in warning for warning in plan.warnings)
    assert plan.changes[0].desired == "0"


def test_apply_creates_then_patches(api: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def post(url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(("post", url, payload))
        return {}

    def patch(url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(("patch", url, payload))
        return {}

    api.setattr(gcp_quota, "post_json", post)
    api.setattr(gcp_quota, "patch_json", patch)
    api.setattr(gcp_quota, "list_overrides", lambda path, token: [])

    plan = gcp_quota.discover(_stack(_override()))
    gcp_quota.apply_plan(_stack(_override()), plan)

    assert calls[0][0] == "post"
    assert "consumerOverrides?force=true" in calls[0][1]
    assert calls[0][2] == {"overrideValue": "0"}


def test_apply_patches_an_existing_override(api: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    api.setattr(
        gcp_quota,
        "post_json",
        lambda url, token, payload: calls.append(("post", url, payload)) or {},
    )
    api.setattr(
        gcp_quota,
        "patch_json",
        lambda url, token, payload: calls.append(("patch", url, payload)) or {},
    )
    api.setattr(
        gcp_quota,
        "list_overrides",
        lambda path, token: [{"name": "projects/1/overrides/abc", "overrideValue": "8"}],
    )

    plan = gcp_quota.discover(_stack(_override()))
    gcp_quota.apply_plan(_stack(_override()), plan)

    assert [call[0] for call in calls] == ["patch"]
    assert "projects/1/overrides/abc?force=true" in calls[0][1]


def test_empty_plan_writes_nothing(api: pytest.MonkeyPatch) -> None:
    called = False

    def post(url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    api.setattr(gcp_quota, "post_json", post)
    gcp_quota.apply_plan(_stack(), gcp_quota.discover(_stack()))
    assert called is False


def test_provider_exposes_quota_support() -> None:
    assert GCP.can_manage_quota
    assert GCP.quota_plan is gcp_quota.discover
    assert GCP.quota_apply is gcp_quota.apply_plan


def test_metric_must_belong_to_the_service() -> None:
    with pytest.raises(ValidationError, match="must belong to service"):
        _override(metric="storage.googleapis.com/something")


def test_limit_must_be_a_dimension_path() -> None:
    with pytest.raises(ValidationError, match="dimension path"):
        _override(limit="/project/region/")


def test_service_must_be_a_googleapis_name() -> None:
    with pytest.raises(ValidationError, match="googleapis.com"):
        _override(service="compute", metric="compute/x")


def test_value_cannot_be_below_minus_one() -> None:
    with pytest.raises(ValidationError):
        _override(value=-2)
