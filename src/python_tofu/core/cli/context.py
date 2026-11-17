"""Shared CLI context built from global options and the bound provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from python_tofu.core.exceptions import TofuError
from python_tofu.core.limits import LimitMode, UsageMode
from python_tofu.core.loader import load_stack
from python_tofu.core.models import BaseStack, validate_stack_name
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
    stack_name: str | None = None
    #: True when ``--workdir`` was omitted, so the directory may be re-derived
    #: from the stack's own ``name`` once the config has loaded.
    workdir_is_default: bool = False

    def load_stack(self) -> BaseStack:
        stack = load_stack(self.config_path, self.provider.stack_type)
        name = self.stack_name or stack.name or self.config_path.stem
        if stack.name != name:
            stack = stack.model_copy(update={"name": name})
        if self.workdir_is_default:
            self.workdir = Path(".tofu") / name
        return stack

    def derive_workdir(self, *, discover_name: bool = False) -> Path:
        """Resolve the workdir when the stack is not otherwise loaded.

        ``discover_name`` imports the config to honour ``GcpStack.name`` for
        commands that skip rendering (``output``, ``apply --plan-file``) without
        making a config import mandatory: an unloadable config falls back to
        the config file stem, exactly as before.
        """

        if not self.workdir_is_default:
            return self.workdir

        name = self.stack_name
        if name is None and discover_name:
            try:
                stack = load_stack(self.config_path, self.provider.stack_type)
            except TofuError:
                stack = None
            if stack is not None and stack.name:
                name = stack.name
        return Path(".tofu") / (name or self.config_path.stem)

    def renderer(self) -> BaseRenderer[Any]:
        return self.provider.renderer_type(self.workdir)

    def runner(self) -> TofuRunner:
        return TofuRunner(self.workdir, binary=self.binary)


def check_stack_name(value: str | None) -> str | None:
    """Reject names that would escape the workdir or break a state prefix."""

    if value is None:
        return None
    try:
        validate_stack_name(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return value
