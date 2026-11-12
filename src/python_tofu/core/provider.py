"""Provider plugin contract and registry.

A provider packages three things: the stack model a config file returns, the
renderer that turns it into HCL, and a name used for lookup. The core CLI and
loader only depend on this contract, so GCP quirks can live in
:mod:`python_tofu.providers.gcp` without leaking into the core.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from python_tofu.core.doctor import CheckResult
from python_tofu.core.exceptions import TofuError
from python_tofu.core.limits import LimitPolicy, Throttler, Usage
from python_tofu.core.models import BaseStack
from python_tofu.core.prune import PrunePlan
from python_tofu.core.renderer import BaseRenderer


@dataclass(frozen=True)
class Provider:
    """Everything the core needs to work with one OpenTofu provider."""

    name: str
    stack_type: type[BaseStack]
    renderer_type: type[BaseRenderer[Any]]
    display_name: str = ""
    description: str = ""
    limit_policy: LimitPolicy | None = None
    measure_usage: Callable[[Any], Usage] | None = None
    live_measure_usage: Callable[[Any], Usage] | None = None
    prune_sections: tuple[str, ...] = ()
    prune_plan: Callable[[Any, tuple[str, ...]], PrunePlan] | None = None
    doctor_checks: Callable[[Any, Path], Sequence[CheckResult]] | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.name.upper()

    @property
    def has_live_measurement(self) -> bool:
        return self.live_measure_usage is not None

    @property
    def can_prune(self) -> bool:
        return bool(self.prune_sections) and self.prune_plan is not None

    @property
    def has_doctor(self) -> bool:
        return self.doctor_checks is not None

    def run_doctor(self, stack: BaseStack, workdir: Path) -> tuple[CheckResult, ...]:
        """Run the provider's read-only preflight checks."""

        if self.doctor_checks is None:
            return ()
        return tuple(self.doctor_checks(stack, workdir))

    def plan_prune(self, stack: BaseStack, sections: tuple[str, ...]) -> PrunePlan:
        """Discover live resources in ``sections`` that ``stack`` does not declare."""

        if self.prune_plan is None:
            raise TofuError(f"provider {self.name!r} does not support pruning")
        unknown = sorted(set(sections) - set(self.prune_sections))
        if unknown:
            raise TofuError(
                "unsupported prune section(s): "
                + ", ".join(unknown)
                + ". Supported: "
                + ", ".join(self.prune_sections)
            )
        return self.prune_plan(stack, tuple(sections))

    def usage(self, stack: BaseStack, live: bool = False) -> Usage:
        """Measure ``stack``; ``live`` adds (and prefers) existing infrastructure."""

        measured = Usage() if self.measure_usage is None else self.measure_usage(stack)
        if not live or self.live_measure_usage is None:
            return measured
        return measured.override(self.live_measure_usage(stack))

    def throttler(self) -> Throttler | None:
        return None if self.limit_policy is None else Throttler(self.limit_policy)


_REGISTRY: dict[str, Provider] = {}


def register_provider(provider: Provider) -> Provider:
    """Register ``provider`` under its name and return it."""

    if provider.name in _REGISTRY and _REGISTRY[provider.name] is not provider:
        raise TofuError(f"provider {provider.name!r} is already registered")
    _REGISTRY[provider.name] = provider
    return provider


def get_provider(name: str) -> Provider:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise TofuError(f"unknown provider {name!r} (registered: {known})") from None


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))
