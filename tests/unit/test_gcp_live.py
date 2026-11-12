from __future__ import annotations

from typing import Any

import pytest

from python_tofu.providers.gcp import GCP, GcpProvider, GcpStack
from python_tofu.providers.gcp import live
from python_tofu.providers.gcp.live import (
    FREE_COMPUTE_REGIONS,
    HOURS_PER_MONTH,
    LiveUsageError,
    _is_free_tier_cluster,
    _is_free_tier_disk,
    _is_free_tier_e2_micro,
    _region,
    live_measure_usage,
)

ZONE = "https://www.googleapis.com/compute/v1/projects/demo-project/zones/{zone}"
MACHINE = (
    "https://www.googleapis.com/compute/v1/projects/demo-project/zones/{zone}/machineTypes/{kind}"
)


def e2_micro(zone: str, *, preemptible: bool = False, model: str = "STANDARD") -> dict[str, Any]:
    return {
        "machineType": MACHINE.format(zone=zone, kind="e2-micro"),
        "zone": ZONE.format(zone=zone),
        "scheduling": {"preemptible": preemptible, "provisioningModel": model},
    }


def disk(zone: str, kind: str, size_gb: str) -> dict[str, Any]:
    return {
        "type": f"https://www.googleapis.com/compute/v1/projects/demo-project/zones/{zone}/diskTypes/{kind}",
        "zone": ZONE.format(zone=zone),
        "sizeGb": size_gb,
    }


def stack(**kwargs: Any) -> GcpStack:
    return GcpStack(provider=GcpProvider(project="demo-project"), **kwargs)


@pytest.fixture
def inventory(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    data: dict[str, list[dict[str, Any]]] = {
        live.INSTANCE_TYPE: [
            e2_micro("us-central1-a"),
            e2_micro("us-east1-b", preemptible=True),
            e2_micro("us-west1-c", model="SPOT"),
            e2_micro("europe-west1-b"),
            {
                "machineType": MACHINE.format(zone="us-central1-a", kind="n2-standard-2"),
                "zone": ZONE.format(zone="us-central1-a"),
                "scheduling": {},
            },
        ],
        live.DISK_TYPE: [
            disk("us-central1-a", "pd-standard", "20"),
            disk("us-west1-b", "pd-ssd", "50"),
            disk("europe-west1-b", "pd-standard", "100"),
        ],
        live.CLUSTER_TYPE: [
            {"location": "us-central1-a", "autopilot": {"enabled": False}},
            {"location": "us-central1", "autopilot": {"enabled": False}},
            {"location": "europe-west1", "autopilot": {"enabled": True}},
        ],
    }
    monkeypatch.setattr(live, "access_token", lambda stack: "token")
    monkeypatch.setattr(live, "list_assets", lambda project, token, asset_type: data[asset_type])
    return data


def test_region_and_basename_handle_full_resource_urls() -> None:
    assert _region(ZONE.format(zone="us-central1-a")) == "us-central1"
    assert _region("europe-west4") == "europe-west4"
    assert _region("") == ""


def test_free_tier_instance_rules() -> None:
    assert _is_free_tier_e2_micro(e2_micro("us-central1-a"))
    assert not _is_free_tier_e2_micro(e2_micro("europe-west1-b"))
    assert not _is_free_tier_e2_micro(e2_micro("us-central1-a", preemptible=True))
    assert not _is_free_tier_e2_micro(e2_micro("us-central1-a", model="SPOT"))


def test_free_tier_disk_rules() -> None:
    assert _is_free_tier_disk(disk("us-east1-b", "pd-standard", "30"))
    assert not _is_free_tier_disk(disk("us-east1-b", "pd-ssd", "30"))
    assert not _is_free_tier_disk(disk("europe-west1-b", "pd-standard", "30"))


def test_free_tier_cluster_rules() -> None:
    assert _is_free_tier_cluster({"location": "us-central1-a", "autopilot": {"enabled": False}})
    assert _is_free_tier_cluster({"location": "europe-west1", "autopilot": {"enabled": True}})
    assert not _is_free_tier_cluster({"location": "us-central1", "autopilot": {"enabled": False}})


def test_live_usage_counts_only_free_tier_resources(
    inventory: dict[str, list[dict[str, Any]]],
) -> None:
    usage = live_measure_usage(stack())
    # One eligible instance; preemptible, Spot, non-free region and n2 excluded.
    assert usage.get("gcp.compute.e2_micro_hours") == HOURS_PER_MONTH
    # One 20 GB pd-standard disk in a free region.
    assert usage.get("gcp.compute.standard_pd_gb") == 20
    # Zonal Standard + Autopilot; regional Standard excluded.
    assert usage.get("gcp.gke.free_clusters") == 2
    assert FREE_COMPUTE_REGIONS == {"us-central1", "us-east1", "us-west1"}


def test_live_usage_marks_inventory_keys_observed_even_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live, "access_token", lambda stack: "token")
    monkeypatch.setattr(live, "list_assets", lambda project, token, asset_type: [])
    usage = live_measure_usage(stack())
    for key in (
        "gcp.compute.e2_micro_hours",
        "gcp.compute.standard_pd_gb",
        "gcp.gke.free_clusters",
    ):
        assert usage.is_observed(key)
        assert usage.get(key) == 0
    # Inventory says nothing about byte-based limits.
    assert not usage.is_observed("gcp.storage.standard_gb")


def test_list_assets_paginates_and_skips_missing_resource_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages: list[dict[str, Any]] = [
        {"assets": [{"resource": {"data": {"name": "a"}}}, {"resource": {}}], "nextPageToken": "n"},
        {"assets": [{"resource": {"data": {"name": "b"}}}]},
    ]
    calls: list[dict[str, str]] = []

    def fake_get(url: str, token: str, params: dict[str, str]) -> dict[str, Any]:
        calls.append(dict(params))
        return pages[len(calls) - 1]

    monkeypatch.setattr(live, "get_json", fake_get)
    data = live.list_assets("demo-project", "token", live.INSTANCE_TYPE)
    assert [item["name"] for item in data] == ["a", "b"]
    assert calls[0]["assetTypes"] == live.INSTANCE_TYPE
    assert calls[0]["contentType"] == "RESOURCE"
    assert calls[1]["pageToken"] == "n"


def test_provider_live_usage_overrides_stack_estimates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live, "access_token", lambda stack: "token")
    monkeypatch.setattr(
        live,
        "list_assets",
        lambda project, token, asset_type: (
            [e2_micro("us-central1-a")] if asset_type == live.INSTANCE_TYPE else []
        ),
    )
    configured = stack(
        usage_estimates={
            "gcp.compute.e2_micro_hours": 10,
            "gcp.storage.standard_gb": 1.5,
        }
    )

    offline = GCP.usage(configured)
    assert offline.get("gcp.compute.e2_micro_hours") == 10
    assert offline.get("gcp.storage.standard_gb") == 1.5

    measured = GCP.usage(configured, live=True)
    # Live inventory wins for the key it measures ...
    assert measured.get("gcp.compute.e2_micro_hours") == HOURS_PER_MONTH
    # ... estimates survive for keys inventory cannot see.
    assert measured.get("gcp.storage.standard_gb") == 1.5


def test_live_measurement_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(stack: GcpStack) -> str:
        raise LiveUsageError("could not obtain Google credentials: no key")

    monkeypatch.setattr(live, "access_token", boom)
    with pytest.raises(LiveUsageError, match="credentials"):
        live_measure_usage(stack())
