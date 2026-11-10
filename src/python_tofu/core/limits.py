"""Provider-agnostic usage limits and throttling.

A provider supplies a :class:`LimitPolicy` (its free tier, quota or budget) and
a measurement function that turns a stack into :class:`Usage`. Core owns the
arithmetic, reporting and enforcement, so adding a provider does not add another
enforcement mechanism.

Limit keys are opaque strings such as ``gcp.storage.standard_gb``. Units are
descriptive (``GB``, ``requests``, ``hours``); core never converts them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from python_tofu.core.exceptions import TofuError


class LimitMode(str, Enum):
    """How the CLI should react to exceeded limits."""

    OFF = "off"
    WARN = "warn"
    ERROR = "error"


class LimitPeriod(str, Enum):
    """Window a limit applies to. Descriptive only."""

    HOUR = "hour"
    DAY = "day"
    MONTH = "month"
    TOTAL = "total"


class LimitAction(str, Enum):
    """What an exceeded limit means when enforcement is enabled."""

    WARN = "warn"
    ERROR = "error"


class LimitStatus(str, Enum):
    """Outcome of checking one limit."""

    OK = "ok"
    EXCEEDED = "exceeded"
    UNKNOWN = "unknown"


class UsageMode(str, Enum):
    """Where measured usage comes from.

    ``stack`` reads only what the stack declares (offline). ``live`` asks the
    provider to measure existing infrastructure and lets those values win.
    """

    STACK = "stack"
    LIVE = "live"


@dataclass(frozen=True)
class Limit:
    """One provider-defined ceiling."""

    key: str
    area: str
    unit: str
    amount: float
    period: LimitPeriod = LimitPeriod.MONTH
    action: LimitAction = LimitAction.ERROR
    description: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("limit key must not be empty")
        if self.amount <= 0:
            raise ValueError(f"limit {self.key!r} must have a positive amount")


@dataclass(frozen=True)
class AggregateLimit:
    """A ceiling on the sum of normalised utilisation of other limits.

    ``amount=1.0`` means "the included limits together may use one full free
    tier". This is how a project can be well under each individual limit yet
    still be throttled as a whole (or summarised under one number).
    """

    key: str
    amount: float = 1.0
    areas: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    action: LimitAction = LimitAction.ERROR
    description: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("aggregate limit key must not be empty")
        if self.amount <= 0:
            raise ValueError(f"aggregate limit {self.key!r} must be positive")


@dataclass(frozen=True)
class LimitPolicy:
    """A provider's complete set of ceilings."""

    limits: tuple[Limit, ...]
    aggregates: tuple[AggregateLimit, ...] = ()
    default_mode: LimitMode = LimitMode.ERROR
    description: str = ""

    def get(self, key: str) -> Limit:
        for limit in self.limits:
            if limit.key == key:
                return limit
        raise KeyError(key)

    def for_area(self, area: str) -> tuple[Limit, ...]:
        return tuple(limit for limit in self.limits if limit.area == area)

    @property
    def areas(self) -> tuple[str, ...]:
        return tuple(sorted({limit.area for limit in self.limits}))


@dataclass(frozen=True)
class Usage:
    """Measured or estimated amounts, keyed by limit key.

    ``observed`` records which keys were actually measured. A key that is absent
    is *unknown*, never zero: an unmeasured limit must not look like it passed.
    Constructing ``Usage`` with values marks those keys observed; build an empty
    :class:`Usage` when a measurement is unavailable.
    """

    values: Mapping[str, float] = field(default_factory=dict)
    observed: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # A value that is present was, by definition, measured.
        if self.values and not self.values.keys() <= self.observed:
            object.__setattr__(self, "observed", self.observed | frozenset(self.values))

    def add(self, key: str, amount: float = 1.0) -> "Usage":
        merged = dict(self.values)
        merged[key] = merged.get(key, 0.0) + amount
        return Usage(merged, self.observed | {key})

    def get(self, key: str, default: float = 0.0) -> float:
        return float(self.values.get(key, default))

    def is_observed(self, key: str) -> bool:
        return key in self.observed

    def merge(self, other: "Usage") -> "Usage":
        """Add ``other``'s amounts to ours (use when both are contributions)."""

        merged = dict(self.values)
        for key, amount in other.values.items():
            merged[key] = merged.get(key, 0.0) + amount
        return Usage(merged, self.observed | other.observed)

    def override(self, other: "Usage") -> "Usage":
        """Take ``other``'s values for the keys it observed (live wins)."""

        merged = dict(self.values)
        for key in other.observed:
            merged[key] = other.get(key)
        return Usage(merged, self.observed | other.observed)

    def __bool__(self) -> bool:
        return any(value for value in self.values.values())

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, float] | None,
        observed: Iterable[str] | None = None,
    ) -> "Usage":
        return cls(dict(values or {}), frozenset(observed or ()))


@dataclass(frozen=True)
class LimitCheck:
    """One evaluated limit (either a single limit or an aggregate)."""

    key: str
    area: str
    unit: str
    used: float
    amount: float
    period: LimitPeriod = LimitPeriod.MONTH
    action: LimitAction = LimitAction.ERROR
    description: str = ""
    observed: bool = True

    @property
    def status(self) -> LimitStatus:
        if not self.observed:
            return LimitStatus.UNKNOWN
        return LimitStatus.EXCEEDED if self.exceeded else LimitStatus.OK

    @property
    def ratio(self) -> float:
        return self.used / self.amount if self.amount else float("inf")

    @property
    def remaining(self) -> float:
        return max(self.amount - self.used, 0.0)

    @property
    def exceeded(self) -> bool:
        return self.used > self.amount

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "area": self.area,
            "unit": self.unit,
            "used": self.used,
            "amount": self.amount,
            "ratio": self.ratio,
            "remaining": self.remaining,
            "exceeded": self.exceeded,
            "observed": self.observed,
            "status": self.status.value,
            "period": self.period.value,
            "action": self.action.value,
            "description": self.description,
        }


@dataclass(frozen=True)
class LimitReport:
    """Result of checking a policy against measured usage."""

    checks: tuple[LimitCheck, ...]

    @property
    def exceeded(self) -> tuple[LimitCheck, ...]:
        return tuple(check for check in self.checks if check.exceeded)

    @property
    def errors(self) -> tuple[LimitCheck, ...]:
        return tuple(
            check for check in self.checks if check.exceeded and check.action is LimitAction.ERROR
        )

    @property
    def warnings(self) -> tuple[LimitCheck, ...]:
        return tuple(
            check for check in self.checks if check.exceeded and check.action is LimitAction.WARN
        )

    @property
    def unknown(self) -> tuple[LimitCheck, ...]:
        return tuple(check for check in self.checks if not check.observed)

    @property
    def used_checks(self) -> tuple[LimitCheck, ...]:
        return tuple(check for check in self.checks if check.used)

    def by_area(self) -> dict[str, tuple[LimitCheck, ...]]:
        grouped: dict[str, list[LimitCheck]] = {}
        for check in self.checks:
            grouped.setdefault(check.area, []).append(check)
        return {area: tuple(checks) for area, checks in grouped.items()}

    def summary(self) -> str:
        if not self.checks:
            return "no limits configured"
        return (
            f"{len(self.checks)} limits checked; "
            f"{len(self.errors)} exceeded, {len(self.warnings)} warning, "
            f"{len(self.unknown)} unknown"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "exceeded": len(self.exceeded),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "unknown": len(self.unknown),
            "checks": [check.as_dict() for check in self.checks],
        }


class LimitExceeded(TofuError):
    """Raised when a policy's error-level limits are exceeded."""

    def __init__(self, report: LimitReport) -> None:
        self.report = report
        lines = [
            f"{check.key}: {check.used:g}/{check.amount:g} {check.unit}" for check in report.errors
        ]
        super().__init__("limits exceeded:\n  " + "\n  ".join(lines))


class LimitUnknown(TofuError):
    """Raised when ``fail_on_unknown`` is set and limits were not measured."""

    def __init__(self, report: LimitReport) -> None:
        self.report = report
        keys = [check.key for check in report.unknown]
        shown = ", ".join(keys[:8])
        if len(keys) > 8:
            shown += f", … (+{len(keys) - 8})"
        super().__init__(f"{len(keys)} limits could not be measured: {shown}")


class Throttler:
    """Evaluate a :class:`LimitPolicy` against :class:`Usage`."""

    def __init__(self, policy: LimitPolicy) -> None:
        self.policy = policy

    def check(self, usage: Usage | Mapping[str, float]) -> LimitReport:
        measured = usage if isinstance(usage, Usage) else Usage.from_mapping(usage)
        base_checks = [
            LimitCheck(
                key=limit.key,
                area=limit.area,
                unit=limit.unit,
                used=measured.get(limit.key),
                amount=limit.amount,
                period=limit.period,
                action=limit.action,
                description=limit.description,
                observed=measured.is_observed(limit.key),
            )
            for limit in self.policy.limits
        ]
        checks = list(base_checks)
        for aggregate in self.policy.aggregates:
            # Aggregates are computed from the individual limits only, never
            # from another aggregate.
            relevant = self._aggregate_checks(aggregate, base_checks)
            used = sum(check.ratio for check in relevant)
            checks.append(
                LimitCheck(
                    key=aggregate.key,
                    area="total",
                    unit="x free tier",
                    used=used,
                    amount=aggregate.amount,
                    period=LimitPeriod.TOTAL,
                    action=aggregate.action,
                    description=aggregate.description,
                    observed=bool(relevant) and all(check.observed for check in relevant),
                )
            )
        return LimitReport(tuple(checks))

    @staticmethod
    def _aggregate_checks(
        aggregate: AggregateLimit, checks: Iterable[LimitCheck]
    ) -> list[LimitCheck]:
        selected: list[LimitCheck] = []
        for check in checks:
            if aggregate.areas and check.area not in aggregate.areas:
                continue
            if aggregate.keys and check.key not in aggregate.keys:
                continue
            selected.append(check)
        return selected

    def enforce(
        self,
        usage: Usage | Mapping[str, float],
        mode: LimitMode | None = None,
        fail_on_unknown: bool = False,
    ) -> LimitReport:
        report = self.check(usage)
        effective = mode or self.policy.default_mode
        if effective is LimitMode.ERROR and report.errors:
            raise LimitExceeded(report)
        if effective is not LimitMode.OFF and fail_on_unknown and report.unknown:
            raise LimitUnknown(report)
        return report
