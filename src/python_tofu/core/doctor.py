"""Provider-agnostic preflight results.

Providers supply the checks through :attr:`Provider.doctor_checks`; the core
runs them before anything renders and decides the exit code. Nothing here
touches the network or OpenTofu — these are plain value objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CheckStatus(str, Enum):
    """Outcome of one preflight check."""

    OK = "ok"
    FAIL = "fail"
    UNKNOWN = "unknown"
    SKIP = "skip"

    @property
    def symbol(self) -> str:
        return {
            CheckStatus.OK: "✓",
            CheckStatus.FAIL: "✗",
            CheckStatus.UNKNOWN: "?",
            CheckStatus.SKIP: "-",
        }[self]


@dataclass(frozen=True)
class CheckResult:
    """One line of ``python-tofu doctor`` output."""

    name: str
    status: CheckStatus
    message: str
    fix: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass(frozen=True)
class DoctorReport:
    """Every check, in display order."""

    results: tuple[CheckResult, ...] = ()

    @property
    def failed(self) -> tuple[CheckResult, ...]:
        return tuple(result for result in self.results if result.status is CheckStatus.FAIL)

    @property
    def unknown(self) -> tuple[CheckResult, ...]:
        return tuple(result for result in self.results if result.status is CheckStatus.UNKNOWN)

    @property
    def ok(self) -> bool:
        return not self.failed

    def exit_code(self, fail_on_unknown: bool = False) -> int:
        if self.failed or (fail_on_unknown and self.unknown):
            return 1
        return 0

    def as_dict(self, fail_on_unknown: bool = False) -> dict[str, Any]:
        return {
            "ok": self.exit_code(fail_on_unknown) == 0,
            "failed": len(self.failed),
            "unknown": len(self.unknown),
            "checks": [result.as_dict() for result in self.results],
        }


__all__ = ["CheckResult", "CheckStatus", "DoctorReport"]
