"""``plan`` — render, init and produce a plan summary."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import (
    AllowServiceAccountsOption,
    BinaryOption,
    ConfigOption,
    FailOnUnknownOption,
    LimitModeOption,
    PruneOption,
    PruneSectionOption,
    StackNameOption,
    UsageModeOption,
    VarFileOption,
    VerboseOption,
    WorkdirOption,
    make_context,
    resolve_path,
)
from python_tofu.core.exceptions import TofuError
from python_tofu.core.provider import Provider
from python_tofu.core.results import PlanSummary


def format_summary(summary: PlanSummary) -> str:
    if not summary.has_changes:
        return f"Plan: no changes ({summary.no_op} resources unchanged)."
    parts = [
        f"{summary.create} to create",
        f"{summary.update} to update",
        f"{summary.delete} to delete",
    ]
    if summary.replace:
        parts.append(f"{summary.replace} to replace")
    if summary.other:
        parts.append(f"{summary.other} other")
    return "Plan: " + ", ".join(parts) + "."


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Render the stack and show an OpenTofu plan.")

    @app.callback(invoke_without_command=True)
    def plan(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        limits: LimitModeOption = None,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        stack_name: StackNameOption = None,
        destroy: bool = typer.Option(
            False, "--destroy", help="Plan a destroy instead of an apply."
        ),
        no_init: bool = typer.Option(False, "--no-init", help="Skip `tofu init` before planning."),
        var_file: VarFileOption = None,
        json_output: bool = typer.Option(False, "--json", help="Print the summary as JSON."),
        exit_code: bool = typer.Option(
            False,
            "--exit-code",
            help=(
                "Exit 2 when the plan has changes, 0 when it is empty and 1 on "
                "error. Useful for CI without parsing the summary."
            ),
        ),
        prune: PruneOption = None,
        prune_section: PruneSectionOption = None,
        allow_service_accounts: AllowServiceAccountsOption = False,
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
        stack, _ = command.prepare()
        sections = command.prune_sections(
            stack,
            prune,
            prune_section,
            allow_service_accounts=allow_service_accounts,
        )
        if destroy and sections:
            command.abort("--prune cannot be combined with --destroy")
        runner = command.runner()

        if not no_init:
            command.run_tofu("init")

        # ``tofu`` runs with cwd=<workdir>; keep the plan file absolute so a
        # relative ``--workdir`` does not nest it inside the workdir a second time.
        plan_file = (command.ctx.workdir / "plan.tfplan").resolve()
        command.run_tofu(
            "plan", destroy=destroy, var_file=resolve_path(var_file), plan_file=plan_file
        )
        command.prune(stack, sections, dry_run=True)

        try:
            payload = runner.show_json(plan_file)
        except TofuError as exc:
            if json_output:
                typer.echo(json.dumps({"error": str(exc)}))
            else:
                typer.secho(
                    f"Could not parse plan summary: {exc}", fg=typer.colors.YELLOW, err=True
                )
            # ``--exit-code`` promises a verdict; without a summary we cannot
            # prove the plan is empty, so report an error instead of "no changes".
            if exit_code:
                raise typer.Exit(1)
            return

        summary = PlanSummary.from_show_json(payload)
        if json_output:
            typer.echo(json.dumps(summary.as_dict()))
        else:
            typer.echo(format_summary(summary))
        if exit_code and summary.has_changes:
            raise typer.Exit(2)

    return app
