"""Shared CLI context built from global options."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from python_tofu.loader import load_stack
from python_tofu.models.stack import GcpStack
from python_tofu.services.renderer import Renderer
from python_tofu.services.runner import TofuRunner


@dataclass
class AppContext:
    config_path: Path = Path("infra.py")
    workdir: Path = Path(".tofu")
    binary: str = "tofu"
    verbose: bool = False

    def load_stack(self) -> GcpStack:
        return load_stack(self.config_path)

    def renderer(self) -> Renderer:
        return Renderer(self.workdir)

    def runner(self) -> TofuRunner:
        return TofuRunner(self.workdir, binary=self.binary)
