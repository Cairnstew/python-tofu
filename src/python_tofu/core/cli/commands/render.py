"""``render`` — write HCL without invoking OpenTofu."""

from __future__ import annotations

import difflib
from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import (
    BinaryOption,
    ConfigOption,
    FailOnUnknownOption,
    LimitModeOption,
    StackNameOption,
    UsageModeOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.core.exceptions import TofuError
from python_tofu.core.provider import Provider


def _render_text(command: BaseCommand) -> dict[str, str]:
    """Render in memory so the read-only flags never touch the workdir."""

    stack = command.load()
    command.check_limits(stack)
    try:
        return command.ctx.renderer().render_text(stack)
    except TofuError as exc:
        command.abort(str(exc))


def _stale_files(workdir: Path, contents: dict[str, str]) -> list[tuple[str, str | None, str]]:
    """Return ``(name, on_disk, rendered)`` for every file that would change."""

    stale: list[tuple[str, str | None, str]] = []
    for name, text in contents.items():
        target = workdir / name
        existing = target.read_text(encoding="utf-8") if target.is_file() else None
        if existing != text:
            stale.append((name, existing, text))
    return stale


def _unified_diff(name: str, existing: str | None, text: str) -> str:
    before = (existing or "").splitlines(keepends=True)
    after = text.splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=f"a/{name}", tofile=f"b/{name}"))


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Render the Python stack to OpenTofu HCL.")

    @app.callback(invoke_without_command=True)
    def render(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        limits: LimitModeOption = None,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        stack_name: StackNameOption = None,
        check: bool = typer.Option(
            False,
            "--check",
            help="Exit 1 when the workdir differs from the rendered HCL; write nothing.",
        ),
        diff: bool = typer.Option(
            False,
            "--diff",
            help="Show the changes --check would report; write nothing.",
        ),
        stdout: str | None = typer.Option(
            None,
            "--stdout",
            metavar="FILE",
            help="Print one rendered file (e.g. main.tf) instead of writing anything.",
        ),
    ) -> None:
        command = BaseCommand(
            make_context(
                config,
                workdir,
                binary,
                verbose,
                provider,
                limits,
                usage,
                fail_on_unknown,
                stack_name=stack_name,
            )
        )
        if (check or diff) and stdout is not None:
            command.abort("--check/--diff cannot be combined with --stdout")

        if check or diff:
            contents = _render_text(command)
            stale = _stale_files(command.ctx.workdir, contents)
            if not stale:
                typer.echo(f"HCL is up to date ({len(contents)} files).")
                return
            typer.echo(f"HCL is out of date ({len(stale)} of {len(contents)} files):")
            for name, existing, text in stale:
                typer.echo(f"  {name}")
                if diff:
                    typer.echo(_unified_diff(name, existing, text), nl=False)
            typer.echo("Run `python-tofu render` to update.")
            raise typer.Exit(1)

        if stdout is not None:
            contents = _render_text(command)
            if stdout not in contents:
                command.abort(
                    f"no rendered file named {stdout!r}; choose from {', '.join(contents)}"
                )
            typer.echo(contents[stdout], nl=False)
            return

        _, result = command.prepare()
        typer.echo(f"Rendered {result.resources} resources into {result.workdir}")
        for path in result.files:
            typer.echo(f"  {path}")

    return app
