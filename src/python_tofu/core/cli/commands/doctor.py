"""``doctor`` — read-only preflight: credentials, project, billing, APIs, backend."""

from __future__ import annotations

import json
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
from python_tofu.core.doctor import CheckResult, CheckStatus, DoctorReport
from python_tofu.core.exceptions import TofuError
from python_tofu.core.limits import LimitMode, LimitReport, UsageMode
from python_tofu.core.models import BaseStack
from python_tofu.core.provider import Provider
from python_tofu.core.toolchain import run_checks as run_toolchain_checks

_COLORS = {
    CheckStatus.OK: typer.colors.GREEN,
    CheckStatus.FAIL: typer.colors.RED,
    CheckStatus.UNKNOWN: typer.colors.YELLOW,
    CheckStatus.SKIP: typer.colors.BRIGHT_BLACK,
}


def _limits_check(command: BaseCommand, stack: BaseStack) -> CheckResult | None:
    """Summarise the provider's limits, reusing the measured usage."""

    policy = command.ctx.provider.limit_policy
    if policy is None:
        return None
    if (command.ctx.limit_mode or stack.limits_mode or policy.default_mode) is LimitMode.OFF:
        return None
    try:
        report: LimitReport | None = command.limit_report(stack)
    except TofuError as exc:
        return CheckResult("limits", CheckStatus.UNKNOWN, str(exc))

    if report is None:
        return None
    if report.errors:
        keys = ", ".join(check.key for check in report.errors)
        return CheckResult(
            "limits",
            CheckStatus.FAIL,
            f"{len(report.errors)} exceeded: {keys}",
            fix="python-tofu limits --all",
        )
    if report.unknown and command.ctx.fail_on_unknown:
        return CheckResult(
            "limits",
            CheckStatus.FAIL,
            f"{len(report.unknown)} limit(s) could not be measured",
            fix="python-tofu limits --all --usage live",
        )
    if report.unknown:
        measure = "" if command.ctx.usage_mode is UsageMode.LIVE else ", --usage live to measure"
        return CheckResult(
            "limits",
            CheckStatus.UNKNOWN,
            f"{report.summary()} (use --all to list{measure})",
        )
    if report.warnings:
        keys = ", ".join(check.key for check in report.warnings)
        return CheckResult("limits", CheckStatus.OK, f"warnings only: {keys}")
    return CheckResult("limits", CheckStatus.OK, report.summary())


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Check credentials, project state, billing, APIs and the state backend.")

    @app.callback(invoke_without_command=True)
    def doctor(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        limits: LimitModeOption = None,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        stack_name: StackNameOption = None,
        json_output: bool = typer.Option(False, "--json", help="Emit the checklist as JSON."),
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
        stack = command.load()

        results: list[CheckResult] = []
        try:
            required = command.ctx.renderer().required_providers(stack)
        except TofuError:
            required = {}
        results.extend(
            run_toolchain_checks(
                command.ctx.binary,
                stack.required_version,
                required,
                command.ctx.workdir,
            )
        )

        if not provider.has_doctor:
            results.append(
                CheckResult(
                    "provider",
                    CheckStatus.SKIP,
                    f"{provider.label} does not define preflight checks",
                )
            )
        try:
            results.extend(provider.run_doctor(stack, command.ctx.workdir))
        except TofuError as exc:
            command.abort(str(exc))

        limits_result = _limits_check(command, stack)
        if limits_result is not None:
            results.append(limits_result)

        report = DoctorReport(tuple(results))
        if json_output:
            typer.echo(json.dumps(report.as_dict(fail_on_unknown)))
        else:
            width = max((len(result.name) for result in report.results), default=0)
            for result in report.results:
                typer.secho(
                    f"{result.status.symbol} {result.name.ljust(width)}  {result.message}",
                    fg=_COLORS[result.status],
                )
                if result.fix and result.status is CheckStatus.FAIL:
                    typer.echo(f"  fix: {result.fix}")
            if report.failed:
                typer.secho(
                    f"Doctor found {len(report.failed)} problem(s).", fg=typer.colors.RED, err=True
                )
            else:
                typer.secho("No blocking problems found.", fg=typer.colors.GREEN, err=True)

        raise typer.Exit(report.exit_code(fail_on_unknown))

    return app
