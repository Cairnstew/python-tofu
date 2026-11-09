"""Typer application entry point."""

from __future__ import annotations

import typer

from python_tofu.cli.commands import apply, destroy, init, output, plan, render, validate

app = typer.Typer(
    no_args_is_help=True,
    help="Manage GCP infrastructure with a typed Python DSL and OpenTofu.",
)

app.add_typer(render.app, name="render")
app.add_typer(init.app, name="init")
app.add_typer(validate.app, name="validate")
app.add_typer(plan.app, name="plan")
app.add_typer(apply.app, name="apply")
app.add_typer(destroy.app, name="destroy")
app.add_typer(output.app, name="output")
