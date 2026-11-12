"""``init`` — render then run ``tofu init``."""

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
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Render the stack and initialise the OpenTofu working directory.")

    @app.callback(invoke_without_command=True)
    def init(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        limits: LimitModeOption = None,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        stack_name: StackNameOption = None,
        upgrade: bool = typer.Option(
            False,
            "--upgrade",
            help="Reinstall providers to the newest allowed version.",
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
        command.prepare()
        command.run_tofu("init", upgrade=upgrade)

    return app
