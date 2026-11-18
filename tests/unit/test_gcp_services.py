from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from python_tofu.providers.gcp import services as gcp_services
from python_tofu.providers.gcp.live import GoogleApiError
from python_tofu.providers.gcp.models import ProjectApi
from python_tofu.providers.gcp.services import (
    AmbiguousService,
    Service,
    ServiceCatalog,
    ServiceUsageError,
    UnknownService,
    canonical_service,
    enable_apis,
)

ENABLED_RAW = [
    {
        "name": "projects/1/services/storage.googleapis.com",
        "config": {"name": "storage.googleapis.com", "title": "Cloud Storage"},
        "state": "ENABLED",
    },
    {
        "name": "projects/1/services/compute.googleapis.com",
        "config": {"name": "compute.googleapis.com", "title": "Compute Engine API"},
        "state": "ENABLED",
    },
]
DISABLED_RAW = [
    {
        "name": "projects/1/services/run.googleapis.com",
        "config": {"name": "run.googleapis.com", "title": "Cloud Run Admin API"},
        "state": "DISABLED",
    },
    {
        "name": "projects/1/services/cloudfunctions.googleapis.com",
        "config": {
            "name": "cloudfunctions.googleapis.com",
            "title": "Cloud Functions API",
        },
        "state": "DISABLED",
    },
]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    """Replace the HTTP layer with the fixture catalog and record fetches."""

    catalog = {
        service.name: service
        for service in (gcp_services._parse_service(item) for item in ENABLED_RAW + DISABLED_RAW)
    }
    calls: list[tuple[str, str | None]] = []

    def fake_list(
        project: str,
        token: str,
        *,
        state: str | None = None,
        quota_project: str | None = None,
    ) -> list[Service]:
        calls.append(("list", state))
        raw = {
            None: ENABLED_RAW + DISABLED_RAW,
            "ENABLED": ENABLED_RAW,
            "DISABLED": DISABLED_RAW,
        }[state]
        return [gcp_services._parse_service(item) for item in raw]

    def fake_get(
        project: str,
        token: str,
        name: str,
        *,
        quota_project: str | None = None,
    ) -> Service | None:
        calls.append(("get", name))
        return catalog.get(gcp_services.canonical_service(name))

    monkeypatch.setattr(gcp_services, "list_services", fake_list)
    monkeypatch.setattr(gcp_services, "get_service", fake_get)
    monkeypatch.setattr(
        gcp_services,
        "access_token_for",
        lambda credentials=None, impersonate_service_account=None: "token",
    )
    return calls


def test_canonical_service() -> None:
    assert canonical_service("compute") == "compute.googleapis.com"
    assert canonical_service("COMPUTE.GOOGLEAPIS.COM") == "compute.googleapis.com"
    assert canonical_service("projects/1/services/run.googleapis.com") == "run.googleapis.com"
    with pytest.raises(ServiceUsageError, match="must not be empty"):
        canonical_service("  ")


def test_list_services_paginates_and_sends_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[dict[str, str], dict[str, str] | None]] = []

    def fake_get(
        url: str,
        token: str,
        params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        calls.append((dict(params), headers))
        if "pageToken" not in params:
            return {"services": [DISABLED_RAW[0]], "nextPageToken": "page-2"}
        return {"services": [DISABLED_RAW[1]]}

    monkeypatch.setattr(gcp_services, "get_json", fake_get)

    found = gcp_services.list_services(
        "demo-project", "token", state="disabled", quota_project="quota-project"
    )

    assert [item.name for item in found] == [
        "run.googleapis.com",
        "cloudfunctions.googleapis.com",
    ]
    assert calls[0][0]["filter"] == "state:DISABLED"
    assert calls[0][1] == {"x-goog-user-project": "quota-project"}
    assert calls[1][0]["pageToken"] == "page-2"


def test_get_service_returns_none_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> dict[str, object]:
        raise GoogleApiError("not found", status=404)

    monkeypatch.setattr(gcp_services, "get_json", missing)

    assert gcp_services.get_service("demo-project", "token", "nope") is None


def test_get_service_propagates_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> dict[str, object]:
        raise GoogleApiError("forbidden", status=403)

    monkeypatch.setattr(gcp_services, "get_json", forbidden)

    with pytest.raises(GoogleApiError, match="forbidden"):
        gcp_services.get_service("demo-project", "token", "run")


def test_get_service_parses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def found(*args: object, **kwargs: object) -> dict[str, object]:
        return {"config": {"name": "run.googleapis.com", "title": "Cloud Run"}, "state": "ENABLED"}

    monkeypatch.setattr(gcp_services, "get_json", found)

    service = gcp_services.get_service("demo-project", "token", "run")

    assert service is not None
    assert service.name == "run.googleapis.com"
    assert service.enabled


def test_available_listing_explains_429(monkeypatch: pytest.MonkeyPatch) -> None:
    def rate_limited(*args: object, **kwargs: object) -> dict[str, object]:
        raise GoogleApiError("Google API returned 429 for services")

    monkeypatch.setattr(gcp_services, "get_json", rate_limited)

    with pytest.raises(ServiceUsageError, match="rate-limits the available/disabled"):
        gcp_services.list_services("demo-project", "token", state="DISABLED")


def test_catalog_caches_each_listing(api: list[tuple[str, str | None]]) -> None:
    catalog = ServiceCatalog("demo-project")

    assert len(catalog.enabled()) == 2
    assert len(catalog.enabled()) == 2
    assert len(catalog.available()) == 2
    assert len(catalog.available()) == 2
    assert api == [("list", "ENABLED"), ("list", "DISABLED")]


def test_available_and_enabled_filters(api: list[tuple[str, str | None]]) -> None:
    catalog = ServiceCatalog("demo-project")

    assert [item.name for item in catalog.available("function")] == [
        "cloudfunctions.googleapis.com"
    ]
    assert [item.name for item in catalog.enabled("storage")] == ["storage.googleapis.com"]
    assert catalog.available("nope") == ()


def test_resolve_uses_direct_lookup_without_listing(api: list[tuple[str, str | None]]) -> None:
    catalog = ServiceCatalog("demo-project")

    service = catalog.resolve("compute")

    assert service.name == "compute.googleapis.com"
    assert service.enabled
    assert api == [("get", "compute.googleapis.com")]


def test_resolve_disabled_by_short_name(api: list[tuple[str, str | None]]) -> None:
    catalog = ServiceCatalog("demo-project")

    service = catalog.resolve("run")

    assert service.name == "run.googleapis.com"
    assert service.available


def test_resolve_ambiguous_short_name(api: list[tuple[str, str | None]]) -> None:
    catalog = ServiceCatalog("demo-project")

    with pytest.raises(AmbiguousService, match="cloud"):
        catalog.resolve("cloud")


def test_resolve_unknown_suggests_close_name(api: list[tuple[str, str | None]]) -> None:
    catalog = ServiceCatalog("demo-project")

    with pytest.raises(UnknownService, match="did you mean"):
        catalog.resolve("computee")


def test_enable_returns_ordered_unique_project_apis(api: list[tuple[str, str | None]]) -> None:
    catalog = ServiceCatalog("demo-project")

    apis = catalog.enable("storage", "run", "storage.googleapis.com")

    assert [item.service for item in apis] == [
        "storage.googleapis.com",
        "run.googleapis.com",
    ]
    assert all(isinstance(item, ProjectApi) and item.project == "demo-project" for item in apis)


def test_enable_apis_convenience(api: list[tuple[str, str | None]]) -> None:
    apis = enable_apis("demo-project", "compute")

    assert [item.service for item in apis] == ["compute.googleapis.com"]
    assert apis[0].disable_on_destroy is False


def test_enable_can_disable_on_destroy(api: list[tuple[str, str | None]]) -> None:
    apis = ServiceCatalog("demo-project").enable("compute", disable_on_destroy=True)

    assert apis[0].disable_on_destroy is True


# ── CLI ───────────────────────────────────────────────────────────────
def test_cli_apis_lists_enabled(
    runner: CliRunner, cli: object, api: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(
        cli, ["apis", "--project", "demo-project", "--state", "enabled", "--filter", "storage"]
    )

    assert result.exit_code == 0, result.output
    assert "storage.googleapis.com" in result.output
    assert "Cloud Storage" in result.output
    assert "1 service(s)." in result.output


def test_cli_apis_lists_available(
    runner: CliRunner, cli: object, api: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(cli, ["apis", "--project", "demo-project", "--state", "available"])

    assert result.exit_code == 0, result.output
    assert "run.googleapis.com" in result.output
    assert "cloudfunctions.googleapis.com" in result.output
    assert "2 service(s)." in result.output


def test_cli_apis_json(runner: CliRunner, cli: object, api: list[tuple[str, str | None]]) -> None:
    import json

    result = runner.invoke(
        cli, ["apis", "--project", "demo-project", "--state", "enabled", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert {item["name"] for item in payload} == {
        "storage.googleapis.com",
        "compute.googleapis.com",
    }
    assert all(item["state"] == "enabled" for item in payload)


def test_cli_apis_resolve(
    runner: CliRunner, cli: object, api: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(cli, ["apis", "--project", "demo-project", "--resolve", "run"])

    assert result.exit_code == 0, result.output
    assert "run.googleapis.com" in result.output
    assert "[disabled]" in result.output


def test_cli_apis_resolve_unknown_is_clean(
    runner: CliRunner, cli: object, api: list[tuple[str, str | None]]
) -> None:
    result = runner.invoke(cli, ["apis", "--project", "demo-project", "--resolve", "nope"])

    assert result.exit_code == 1
    assert "unknown Google API" in result.output + getattr(result, "stderr", "")


def test_cli_apis_uses_config_project(
    runner: CliRunner, cli: object, api: list[tuple[str, str | None]], config_file: Path
) -> None:
    result = runner.invoke(cli, ["apis", "--config", str(config_file), "--state", "enabled"])

    assert result.exit_code == 0, result.output
    assert "compute.googleapis.com" in result.output
