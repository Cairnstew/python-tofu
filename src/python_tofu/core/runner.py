"""Subprocess wrapper around the OpenTofu CLI."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from python_tofu.core.exceptions import TofuNotInstalledError
from python_tofu.core.results import CommandResult


class TofuRunner:
    """Run ``tofu`` commands in a working directory and capture their output."""

    def __init__(
        self,
        workdir: str | Path,
        binary: str = "tofu",
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.workdir = Path(workdir)
        self.binary = binary
        self.env = {**os.environ, **dict(env or {})}

    def run(self, *args: str) -> CommandResult:
        """Invoke ``tofu`` with ``args`` and return a captured result."""

        command = [self.binary, *args]
        try:
            process = subprocess.run(
                command,
                cwd=self.workdir,
                env=self.env,
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise TofuNotInstalledError(self.binary) from exc

        return CommandResult(
            args=tuple(command),
            returncode=process.returncode,
            stdout=process.stdout or "",
            stderr=process.stderr or "",
        )

    def init(self, upgrade: bool = False, extra: Sequence[str] = ()) -> CommandResult:
        args = ["init", "-input=false"]
        if upgrade:
            args.append("-upgrade")
        args.extend(extra)
        return self.run(*args)

    def validate(self) -> CommandResult:
        return self.run("validate", "-no-color")

    def plan(
        self,
        plan_file: str | Path | None = None,
        destroy: bool = False,
        var_file: str | Path | None = None,
        extra: Sequence[str] = (),
    ) -> CommandResult:
        args = ["plan", "-input=false", "-no-color"]
        if destroy:
            args.append("-destroy")
        if var_file is not None:
            args.extend(["-var-file", str(var_file)])
        if plan_file is not None:
            args.extend(["-out", str(plan_file)])
        args.extend(extra)
        return self.run(*args)

    def apply(
        self,
        auto_approve: bool = False,
        plan_file: str | Path | None = None,
        var_file: str | Path | None = None,
        extra: Sequence[str] = (),
    ) -> CommandResult:
        args = ["apply", "-no-color"]
        if auto_approve:
            args.append("-auto-approve")
        if var_file is not None:
            args.extend(["-var-file", str(var_file)])
        if plan_file is not None:
            args.append(str(plan_file))
        args.extend(extra)
        return self.run(*args)

    def destroy(
        self,
        auto_approve: bool = False,
        var_file: str | Path | None = None,
        extra: Sequence[str] = (),
    ) -> CommandResult:
        args = ["destroy", "-no-color"]
        if auto_approve:
            args.append("-auto-approve")
        if var_file is not None:
            args.extend(["-var-file", str(var_file)])
        args.extend(extra)
        return self.run(*args)

    def output(self, json_output: bool = True) -> CommandResult:
        args = ["output"]
        if json_output:
            args.append("-json")
        return self.run(*args)

    def show_json(self, plan_file: str | Path) -> dict[str, Any]:
        """Return the JSON representation of a saved plan."""

        result = self.run("show", "-json", str(plan_file))
        if not result.ok:
            from python_tofu.core.exceptions import TofuCommandError

            raise TofuCommandError(result.command, result.returncode, result.stdout, result.stderr)
        parsed: dict[str, Any] = json.loads(result.stdout or "{}")
        return parsed
