"""``apply`` — render and apply the stack."""

from __future__ import annotations

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
from python_tofu.core.models import BaseStack
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Render the stack and apply it with OpenTofu.")

    @app.callback(invoke_without_command=True)
    def apply(
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
        plan_file: Path | None = typer.Option(
            None, "--plan-file", help="Apply a previously saved plan."
        ),
        var_file: VarFileOption = None,
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
        plan_file = resolve_path(plan_file)

        stack: BaseStack | None = None
        sections: tuple[str, ...] = ()
        if plan_file is None:
            stack, _ = command.prepare()
            sections = command.prune_sections(
                stack,
                prune,
                prune_section,
                allow_service_accounts=allow_service_accounts,
            )
            command.run_tofu("init")
        else:
            if prune or prune_section:
                command.abort("--prune cannot be combined with --plan-file")
            if not command.ctx.workdir.is_dir():
                command.abort(f"working directory does not exist: {command.ctx.workdir}")

        command.run_tofu(
            "apply",
            auto_approve=auto_approve,
            plan_file=plan_file,
            var_file=resolve_path(var_file),
        )
        if stack is not None:
            command.prune(stack, sections, dry_run=False, auto_approve=auto_approve)

    return app
