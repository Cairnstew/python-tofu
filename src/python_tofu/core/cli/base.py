"""Shared command behavior: load, render, execute, report."""

from __future__ import annotations

from typing import Any, NoReturn

import typer

from python_tofu.core.cli.context import AppContext
from python_tofu.core.exceptions import ConfigError, TofuError
from python_tofu.core.limits import (
    LimitCheck,
    LimitMode,
    LimitReport,
    LimitUnknown,
    Throttler,
    UsageMode,
)
from python_tofu.core.models import BaseStack
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.results import CommandResult, RenderResult
from python_tofu.core.runner import TofuRunner


def _format_amount(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def format_limit(check: LimitCheck) -> str:
    if not check.observed:
        return f"{check.key}: unknown/{_format_amount(check.amount)} {check.unit}"
    return (
        f"{check.key}: {_format_amount(check.used)}/{_format_amount(check.amount)} "
        f"{check.unit} ({check.ratio * 100:.1f}%)"
    )


class BaseCommand:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def load(self) -> BaseStack:
        try:
            return self.ctx.load_stack()
        except ConfigError as exc:
            self.abort(str(exc))

    def prepare(self) -> tuple[BaseStack, RenderResult]:
        stack = self.load()
        self.check_limits(stack)
        try:
            renderer: BaseRenderer[Any] = self.ctx.renderer()
            return stack, renderer.render(stack)
        except TofuError as exc:
            self.abort(str(exc))

    def limit_report(self, stack: BaseStack) -> LimitReport | None:
        """Measure ``stack`` against the provider policy without enforcing it."""

        policy = self.ctx.provider.limit_policy
        if policy is None:
            return None
        live = self.ctx.usage_mode is UsageMode.LIVE
        try:
            usage = self.ctx.provider.usage(stack, live=live)
        except TofuError as exc:
            self.abort(str(exc))
        return Throttler(policy).check(usage)

    def check_limits(
        self,
        stack: BaseStack,
        mode: LimitMode | None = None,
        fail_on_unknown: bool | None = None,
    ) -> LimitReport | None:
        """Enforce the provider's limits before any OpenTofu command runs."""

        policy = self.ctx.provider.limit_policy
        if policy is None:
            return None

        effective = mode or self.ctx.limit_mode or policy.default_mode
        if effective is LimitMode.OFF:
            return None

        report = self.limit_report(stack)
        if report is None:
            return None

        if effective is LimitMode.ERROR and report.errors:
            heading = policy.description or f"{self.ctx.provider.label} limits"
            details = "\n  ".join(format_limit(check) for check in report.errors)
            self.abort(f"{heading} exceeded:\n  {details}")

        strict = self.ctx.fail_on_unknown if fail_on_unknown is None else fail_on_unknown
        if strict and report.unknown:
            self.abort(str(LimitUnknown(report)))

        for check in report.exceeded:
            typer.secho("Warning: " + format_limit(check), fg=typer.colors.YELLOW, err=True)
        return report

    def runner(self) -> TofuRunner:
        return self.ctx.runner()

    def run_tofu(self, action: str, **kwargs: Any) -> CommandResult:
        """Run a :class:`TofuRunner` method and report it like a command.

        Turns ``TofuNotInstalledError`` (and any other runner error) into the
        same red ``Error:`` line as configuration failures instead of a
        traceback.
        """

        try:
            result: CommandResult = getattr(self.runner(), action)(**kwargs)
        except TofuError as exc:
            self.abort(str(exc))
        self.handle(result)
        return result

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
