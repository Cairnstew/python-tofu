from __future__ import annotations

import pytest

from python_tofu.core.limits import (
    AggregateLimit,
    Limit,
    LimitAction,
    LimitExceeded,
    LimitMode,
    LimitPeriod,
    LimitPolicy,
    LimitStatus,
    LimitUnknown,
    Throttler,
    Usage,
)


def policy() -> LimitPolicy:
    return LimitPolicy(
        limits=(
            Limit("storage.gb", "storage", "GB", 10),
            Limit("compute.hours", "compute", "hours", 100, LimitPeriod.MONTH),
            Limit("requests", "serverless", "requests", 1_000, action=LimitAction.WARN),
        ),
        aggregates=(
            AggregateLimit(
                "total",
                amount=1.0,
                areas=("storage", "compute"),
                action=LimitAction.WARN,
            ),
        ),
        default_mode=LimitMode.ERROR,
        description="test limits",
    )


def test_usage_adds_and_merges() -> None:
    usage = Usage.from_mapping({"a": 1}).add("a", 2).add("b", 3)
    assert usage.get("a") == 3
    assert usage.get("b") == 3
    assert usage.get("missing") == 0
    assert usage.merge(Usage({"a": 10})).get("a") == 13
    assert bool(Usage({"a": 0})) is False
    assert bool(usage) is True


def test_checks_compute_ratios_and_remaining() -> None:
    report = Throttler(policy()).check({"storage.gb": 4, "compute.hours": 50})
    storage = next(check for check in report.checks if check.key == "storage.gb")
    assert storage.used == 4
    assert storage.ratio == pytest.approx(0.4)
    assert storage.remaining == pytest.approx(6)
    assert storage.exceeded is False
    assert report.exceeded == ()


def test_exceeded_error_limits_raise_under_error_mode() -> None:
    throttler = Throttler(policy())
    report = throttler.check({"storage.gb": 11})
    assert [check.key for check in report.errors] == ["storage.gb"]
    with pytest.raises(LimitExceeded, match="storage.gb"):
        throttler.enforce({"storage.gb": 11})

    # warn mode reports without raising
    assert throttler.enforce({"storage.gb": 11}, LimitMode.WARN) is not None
    # off mode still returns a report, but never raises
    assert throttler.enforce({"storage.gb": 11}, LimitMode.OFF) is not None


def test_warn_limits_do_not_raise() -> None:
    report = Throttler(policy()).enforce({"requests": 2_000})
    assert [check.key for check in report.warnings] == ["requests"]
    assert report.errors == ()


def test_aggregate_sums_normalised_utilisation() -> None:
    report = Throttler(policy()).check({"storage.gb": 5, "compute.hours": 100})
    total = next(check for check in report.checks if check.key == "total")
    # 5/10 + 100/100 = 1.5
    assert total.used == pytest.approx(1.5)
    assert total.amount == pytest.approx(1.0)
    assert total.exceeded is True

    included = Throttler(policy()).check({"storage.gb": 5})
    total = next(check for check in included.checks if check.key == "total")
    assert total.used == pytest.approx(0.5)
    assert total.exceeded is False


def test_report_groups_by_area_and_serialises() -> None:
    report = Throttler(policy()).check({"storage.gb": 10})
    grouped = report.by_area()
    assert set(grouped) == {"storage", "compute", "serverless", "total"}
    payload = report.as_dict()
    assert payload["exceeded"] == 0
    assert payload["checks"][0]["key"] == "storage.gb"
    assert "limits checked" in payload["summary"]


def test_policy_lookup_helpers() -> None:
    p = policy()
    assert p.get("storage.gb").area == "storage"
    assert [limit.key for limit in p.for_area("compute")] == ["compute.hours"]
    assert p.areas == ("compute", "serverless", "storage")
    with pytest.raises(KeyError):
        p.get("missing")


@pytest.mark.parametrize("amount", [0, -1])
def test_limits_require_positive_amounts(amount: float) -> None:
    with pytest.raises(ValueError):
        Limit("bad", "area", "unit", amount)
    with pytest.raises(ValueError):
        AggregateLimit("bad", amount=amount)


def test_usage_tracks_which_keys_were_observed() -> None:
    assert not Usage().is_observed("storage.gb")
    assert Usage({"storage.gb": 0}).is_observed("storage.gb")
    assert Usage().add("storage.gb", 0).is_observed("storage.gb")
    assert not Usage({"a": 1}).is_observed("b")


def test_override_lets_live_values_win() -> None:
    base = Usage.from_mapping({"storage.gb": 5, "compute.hours": 1})
    live = Usage.from_mapping({"storage.gb": 2})
    merged = base.override(live)
    assert merged.get("storage.gb") == 2
    assert merged.get("compute.hours") == 1
    assert merged.is_observed("storage.gb")
    assert merged.is_observed("compute.hours")


def test_unmeasured_limits_are_unknown_not_zero() -> None:
    report = Throttler(policy()).check(Usage())
    assert all(check.status is LimitStatus.UNKNOWN for check in report.checks)
    assert len(report.unknown) == len(report.checks)
    assert report.errors == ()
    assert "unknown" in report.summary()
    assert all(check["status"] == "unknown" for check in report.as_dict()["checks"])


def test_aggregate_is_unknown_until_every_included_limit_is_measured() -> None:
    throttler = Throttler(policy())
    partial = throttler.check(Usage({"storage.gb": 1}))
    total = next(check for check in partial.checks if check.key == "total")
    assert total.status is LimitStatus.UNKNOWN

    complete = throttler.check(Usage({"storage.gb": 1, "compute.hours": 1}))
    total = next(check for check in complete.checks if check.key == "total")
    assert total.status is LimitStatus.OK


def test_fail_on_unknown_raises_but_off_mode_disables_it() -> None:
    throttler = Throttler(policy())
    usage = Usage({"storage.gb": 1})
    assert throttler.check(usage).unknown

    with pytest.raises(LimitUnknown, match="could not be measured"):
        throttler.enforce(usage, fail_on_unknown=True)

    report = throttler.enforce(Usage(), LimitMode.OFF, fail_on_unknown=True)
    assert report.unknown
