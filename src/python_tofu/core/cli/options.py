"""Shared option types and context construction for every command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from python_tofu.core.cli.context import AppContext, check_stack_name
from python_tofu.core.limits import LimitMode, UsageMode
from python_tofu.core.provider import Provider

ConfigOption = Annotated[
    Path,
    typer.Option("--config", "-c", help="Python module exposing a module-level `stack`."),
]
WorkdirOption = Annotated[
    Path | None,
    typer.Option(
        "--workdir",
        "-w",
        help=(
            "Directory where HCL and state are written. Default: "
            "`.tofu/<stack-name>` from the config file stem."
        ),
    ),
]
BinaryOption = Annotated[
    str,
    typer.Option(
        "--binary",
        envvar="PYTHON_TOFU_BINARY",
        help="OpenTofu binary to invoke. Default: $PYTHON_TOFU_BINARY, else tofu.",
    ),
]
VerboseOption = Annotated[bool, typer.Option("--verbose", "-v", help="Print every tofu command.")]
VarFileOption = Annotated[
    Path | None,
    typer.Option("--var-file", help="Pass an extra tfvars file to tofu."),
]
LimitModeOption = Annotated[
    LimitMode | None,
    typer.Option(
        "--limits",
        help="Enforce provider limits: error (default), warn, or off.",
    ),
]
UsageModeOption = Annotated[
    UsageMode | None,
    typer.Option(
        "--usage",
        help="Measure declared stack only (stack) or also live infrastructure (live).",
    ),
]
FailOnUnknownOption = Annotated[
    bool,
    typer.Option(
        "--fail-on-unknown",
        help="Fail when a limit could not be measured instead of treating it as unseen.",
    ),
]
PruneOption = Annotated[
    bool | None,
    typer.Option(
        "--prune/--no-prune",
        help=(
            "Delete live resources the stack does not declare, per the stack's "
            "`prune` config. Default: the stack setting (off unless enabled)."
        ),
    ),
]
PruneSectionOption = Annotated[
    list[str] | None,
    typer.Option(
        "--prune-section",
        "--section",
        help=(
            "Restrict pruning to a section (repeatable): buckets, subscriptions, "
            "topics, service_accounts or apis. Implies --prune."
        ),
    ),
]
AllowServiceAccountsOption = Annotated[
    bool,
    typer.Option(
        "--allow-service-accounts",
        help=(
            "Second gate for pruning service accounts. Requires "
            "prune.include_service_accounts=True in the stack."
        ),
    ),
]
StackNameOption = Annotated[
    str | None,
    typer.Option(
        "--stack-name",
        help=(
            "Name for this stack's state. Default: the config file stem, or the "
            "stack's own `name`. Drives the default workdir and GCS prefix."
        ),
    ),
]


def make_context(
    config: Path,
    workdir: Path | None,
    binary: str,
    verbose: bool,
    provider: Provider,
    limit_mode: LimitMode | None = None,
    usage_mode: UsageMode | None = None,
    fail_on_unknown: bool = False,
    stack_name: str | None = None,
) -> AppContext:
    selected = check_stack_name(stack_name)
    explicit_workdir = workdir is not None
    target = workdir.expanduser() if workdir is not None else None
    # A stack without an explicit name is named after its config file; the
    # stack's own `name` may override that once it loads.
    default_name = check_stack_name(selected or config.stem) or config.stem
    # Typer hands paths through unchanged, so a quoted ``~/...`` keeps its
    # tilde. Expand it here; relative paths stay relative to the caller.
    return AppContext(
        provider=provider,
        config_path=config,
        workdir=target if target is not None else Path(".tofu") / default_name,
        binary=binary,
        verbose=verbose,
        limit_mode=limit_mode,
        usage_mode=usage_mode or UsageMode.STACK,
        fail_on_unknown=fail_on_unknown,
        stack_name=selected,
        workdir_is_default=not explicit_workdir,
    )


def resolve_path(path: Path | None) -> Path | None:
    """Resolve a user-supplied path against the current directory.

    ``tofu`` runs with ``cwd=<workdir>``, so a relative ``--plan-file`` or
    ``--var-file`` would otherwise be looked up inside the workdir instead of
    next to the user. Resolve it up front so paths mean what the shell says.
    """

    return None if path is None else path.expanduser().resolve()
