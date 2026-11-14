"""``prune`` — delete live resources the stack does not declare.

Pruning is a dry run by default: it discovers and lists the resources, then
requires ``--apply`` to adopt and destroy them. Unlike ``apply --prune`` it does
not render or apply the stack first.
"""

from __future__ import annotations

from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import (
    AllowServiceAccountsOption,
    BinaryOption,
    ConfigOption,
    FailOnUnknownOption,
    PruneSectionOption,
    StackNameOption,
    UsageModeOption,
    VerboseOption,
    WorkdirOption,
    make_context,
)
from python_tofu.core.limits import LimitMode
from python_tofu.core.provider import Provider


def create_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(
        help="Delete live resources that the stack does not declare. Dry run by default."
    )

    @app.callback(invoke_without_command=True)
    def prune(
        config: ConfigOption = Path("infra.py"),
        workdir: WorkdirOption = None,
        binary: BinaryOption = "tofu",
        verbose: VerboseOption = False,
        usage: UsageModeOption = None,
        fail_on_unknown: FailOnUnknownOption = False,
        stack_name: StackNameOption = None,
        section: PruneSectionOption = None,
        all_sections: bool = typer.Option(
            False, "--all", help="Prune every section the provider supports."
        ),
        apply_changes: bool = typer.Option(
            False, "--apply", help="Actually delete the discovered resources."
        ),
        auto_approve: bool = typer.Option(
            False, "--auto-approve", help="Skip the deletion confirmation."
        ),
        allow_service_accounts: AllowServiceAccountsOption = False,
    ) -> None:
        command = BaseCommand(
            make_context(
                config,
                workdir,
                binary,
                verbose,
                provider,
                LimitMode.OFF,
                usage,
                fail_on_unknown,
                stack_name=stack_name,
            )
        )
        stack = command.load()

        if all_sections and section:
            command.abort("use either --all or --section, not both")
        if all_sections:
            selected: list[str] | None = ["all"]
        elif section:
            selected = section
        else:
            selected = None

        if selected is None and not stack.prune.enabled:
            command.abort(
                "pruning is disabled in the stack; enable `prune` in the config, "
                "or pass --section/--all"
            )

        sections = command.prune_sections(
            stack,
            enabled=True if selected else None,
            sections=selected,
            allow_service_accounts=allow_service_accounts,
        )
        command.prune(stack, sections, dry_run=not apply_changes, auto_approve=auto_approve)

    return app
