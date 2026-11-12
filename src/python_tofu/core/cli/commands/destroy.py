"""``destroy`` — render and destroy the stack."""

from __future__ import annotations

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
    VarFileOption,
    VerboseOption,
    WorkdirOption,
    make_context,
    resolve_path,
)
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Render the stack and destroy it with OpenTofu.")

    @app.callback(invoke_without_command=True)
    def destroy(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        limits: LimitModeOption = None,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        stack_name: StackNameOption = None,
        auto_approve: bool = typer.Option(
            False, "--auto-approve", help="Skip the interactive approval."
        ),
        var_file: VarFileOption = None,
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
        command.prepare()
        command.run_tofu("init")
        command.run_tofu("destroy", auto_approve=auto_approve, var_file=resolve_path(var_file))

    return app
