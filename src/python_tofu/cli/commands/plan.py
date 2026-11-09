"""``python-tofu plan`` — render, init and produce a plan summary."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from python_tofu.cli.commands.base import BaseCommand
from python_tofu.cli.options import (
    BinaryOption,
    ConfigOption,
    VarFileOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.exceptions import TofuCommandError
from python_tofu.models.results import PlanSummary

app = typer.Typer(help="Render the stack and show an OpenTofu plan.")


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


@app.callback(invoke_without_command=True)
def plan(
    config: ConfigOption = Path("infra.py"),
    workdir: WorkdirOption = Path(".tofu"),
    binary: BinaryOption = "tofu",
    verbose: VerboseOption = False,
    destroy: bool = typer.Option(False, "--destroy", help="Plan a destroy instead of an apply."),
    no_init: bool = typer.Option(False, "--no-init", help="Skip `tofu init` before planning."),
    var_file: VarFileOption = None,
    json_output: bool = typer.Option(False, "--json", help="Print the summary as JSON."),
) -> None:
    command = BaseCommand(make_context(config, workdir, binary, verbose))
    command.prepare()
    runner = command.runner()

    if not no_init:
        command.handle(runner.init())

    plan_file = command.ctx.workdir / "plan.tfplan"
    result = runner.plan(destroy=destroy, var_file=var_file, plan_file=plan_file)
    command.handle(result)

    try:
        payload = runner.show_json(plan_file)
    except TofuCommandError as exc:
        if json_output:
            typer.echo(json.dumps({"error": str(exc)}))
        else:
            typer.secho(f"Could not parse plan summary: {exc}", fg=typer.colors.YELLOW, err=True)
        return

    summary = PlanSummary.from_show_json(payload)
    if json_output:
        typer.echo(json.dumps(summary.as_dict()))
    else:
        typer.echo(format_summary(summary))
