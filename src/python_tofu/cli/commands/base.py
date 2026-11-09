"""Shared command behavior: load, render, execute, report."""

from __future__ import annotations

from typing import NoReturn

import typer

from python_tofu.cli.context import AppContext
from python_tofu.exceptions import ConfigError, TofuError
from python_tofu.models.results import CommandResult, RenderResult
from python_tofu.models.stack import GcpStack
from python_tofu.services.runner import TofuRunner


class BaseCommand:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def load(self) -> GcpStack:
        try:
            return self.ctx.load_stack()
        except ConfigError as exc:
            self.abort(str(exc))

    def prepare(self) -> tuple[GcpStack, RenderResult]:
        stack = self.load()
        try:
            return stack, self.ctx.renderer().render(stack)
        except TofuError as exc:
            self.abort(str(exc))

    def runner(self) -> TofuRunner:
        return self.ctx.runner()

    def handle(self, result: CommandResult) -> None:
        if self.ctx.verbose:
            typer.echo("$ " + " ".join(result.args))
        if result.stdout.strip():
            typer.echo(result.stdout.rstrip())
        if not result.ok:
            if result.stderr.strip():
                typer.secho(result.stderr.rstrip(), fg=typer.colors.RED, err=True)
            raise typer.Exit(result.returncode or 1)

    def abort(self, message: str) -> NoReturn:
        typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
