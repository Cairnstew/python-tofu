"""Shared CLI context built from global options and the bound provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from python_tofu.core.limits import LimitMode, UsageMode
from python_tofu.core.loader import load_stack
from python_tofu.core.models import BaseStack
from python_tofu.core.provider import Provider
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.runner import TofuRunner


@dataclass
class AppContext:
    provider: Provider
    config_path: Path = Path("infra.py")
    workdir: Path = Path(".tofu")
    binary: str = "tofu"
    verbose: bool = False
    limit_mode: LimitMode | None = None
    usage_mode: UsageMode = UsageMode.STACK
    fail_on_unknown: bool = False

    def load_stack(self) -> BaseStack:
        return load_stack(self.config_path, self.provider.stack_type)

    def renderer(self) -> BaseRenderer[Any]:
        return self.provider.renderer_type(self.workdir)

    def runner(self) -> TofuRunner:
        return TofuRunner(self.workdir, binary=self.binary)
