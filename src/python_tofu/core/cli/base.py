"""Shared command behavior: load, render, execute, report."""

from __future__ import annotations

from typing import Any, NoReturn, Sequence

import typer

from python_tofu.core.cli.context import AppContext
from python_tofu.core.exceptions import ConfigError, PruneError, TofuError
from python_tofu.core.limits import (
    LimitCheck,
    LimitMode,
    LimitReport,
    LimitUnknown,
    Throttler,
    UsageMode,
)
from python_tofu.core.models import BaseStack, PruneConfig
from python_tofu.core.prune import PrunePlan, Reaper
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.results import CommandResult, RenderResult
from python_tofu.core.runner import TofuRunner


def _format_amount(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,}"
    if abs(value) < 0.01:
        # Preserve small nonzero usage (e.g. a 1 MB bucket estimate) instead of
        # rounding it to 0, which would look like "unmeasured".
        return f"{value:.3g}"
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

        effective = mode or self.ctx.limit_mode or stack.limits_mode or policy.default_mode
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

    # ── pruning ───────────────────────────────────────────────────────
    def prune_sections(
        self,
        stack: BaseStack,
        enabled: bool | None = None,
        sections: list[str] | None = None,
        allow_service_accounts: bool = False,
    ) -> tuple[str, ...]:
        """Resolve the stack config and CLI overrides into concrete sections.

        Returns an empty tuple when pruning stays disabled, so callers can use
        the result as a simple "should I prune?" check. Service accounts need
        both ``stack.prune.include_service_accounts`` and
        ``allow_service_accounts``; otherwise they are dropped from an ``all``
        selection and rejected from an explicit one.
        """

        provider = self.ctx.provider
        if not provider.can_prune:
            if enabled or sections:
                self.abort(f"provider {provider.name!r} does not support pruning")
            return ()

        if sections:
            chosen: tuple[str, ...] = tuple(dict.fromkeys(sections))
        else:
            chosen = stack.prune.sections

        active = True if sections else (stack.prune.enabled if enabled is None else enabled)
        if not active:
            return ()
        try:
            # Bypass the config-level gate here: this method applies the
            # two-key gate explicitly, and an "all" selection must resolve.
            resolved = PruneConfig(
                enabled=True,
                sections=chosen,
                include_service_accounts=True,
            ).resolve(provider.prune_sections, provider.prune_explicit_only)
        except ValueError as exc:
            self.abort(str(exc))

        gate = stack.prune.include_service_accounts and allow_service_accounts
        if "service_accounts" in resolved and not gate:
            if sections and "service_accounts" in chosen:
                self.abort(
                    "pruning service accounts requires both "
                    "prune.include_service_accounts=True in the stack and "
                    "--allow-service-accounts on this run"
                )
            resolved = tuple(item for item in resolved if item != "service_accounts")
            typer.secho(
                "Note: service accounts are skipped; set "
                "prune.include_service_accounts=True and pass "
                "--allow-service-accounts to include them.",
                fg=typer.colors.YELLOW,
                err=True,
            )
        return resolved

    def prune(
        self,
        stack: BaseStack,
        sections: tuple[str, ...],
        *,
        dry_run: bool,
        auto_approve: bool = False,
        explain: bool = False,
    ) -> None:
        """Discover and (unless ``dry_run``) delete undeclared live resources."""

        if not sections:
            return
        try:
            plan = self.ctx.provider.plan_prune(stack, sections)
        except TofuError as exc:
            self.abort(str(exc))

        for warning in plan.warnings:
            typer.secho(f"Note: {warning}", fg=typer.colors.YELLOW, err=True)
        if explain and plan.skipped:
            typer.echo("Skipped resources:")
            for detail in plan.skipped:
                typer.echo(f"    - {detail}")
        if plan.empty:
            return

        self._print_prune_plan(plan, sections)
        if dry_run:
            typer.echo("Dry run: no resources were deleted (re-run with apply or --apply).")
            return

        if not auto_approve:
            typer.confirm(
                f"Delete {len(plan.resources)} resource(s) not declared by the stack?",
                abort=True,
            )

        def _echo(args: Sequence[str]) -> None:
            typer.echo("$ " + " ".join(args))

        reaper = Reaper(
            self.ctx.workdir,
            self.ctx.renderer(),
            stack,
            binary=self.ctx.binary,
            on_command=_echo if self.ctx.verbose else None,
        )
        try:
            for _section, group in plan.by_section(sections):
                reaper.reap(group)
        except PruneError as exc:
            self.abort(str(exc))

        typer.echo(f"Pruned {len(plan.resources)} resource(s).")

    def quota(self, stack: BaseStack, *, dry_run: bool, auto_approve: bool = False) -> None:
        """Print the declared quota overrides that differ live, and apply them."""

        provider = self.ctx.provider
        if not provider.can_manage_quota:
            self.abort(f"provider {provider.name!r} does not support quota overrides")
        try:
            plan = provider.plan_quota(stack)
        except TofuError as exc:
            self.abort(str(exc))

        for warning in plan.warnings:
            typer.secho(f"Note: {warning}", fg=typer.colors.YELLOW, err=True)
        if plan.empty:
            typer.echo("Quota overrides match the declared stack.")
            return

        typer.echo(f"Quota plan: {len(plan.changes)} override(s)")
        for change in plan.changes:
            before = "none" if change.current is None else change.current
            typer.echo(f"  {change.action}: {change.address} ({before} -> {change.desired})")
        if dry_run:
            typer.echo("Dry run: no overrides were changed (re-run with apply or --apply).")
            return

        if not auto_approve:
            typer.confirm(
                f"Apply {len(plan.changes)} quota override(s)?",
                abort=True,
            )
        try:
            provider.apply_quota(stack, plan)
        except TofuError as exc:
            self.abort(str(exc))
        typer.echo(f"Applied {len(plan.changes)} quota override(s).")

    @staticmethod
    def _print_prune_plan(plan: PrunePlan, sections: tuple[str, ...]) -> None:
        typer.echo(f"Prune plan: {len(plan.resources)} undeclared resource(s)")
        for section, group in plan.by_section(sections):
            typer.echo(f"  {section}:")
            for resource in group:
                typer.echo(f"    - {resource.description}")

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
