"""Build the Typer application for a provider."""

import typer

from python_tofu.core.cli.commands import COMMANDS
from python_tofu.core.provider import Provider


def build_app(
    provider: Provider,
    *,
    version: str,
    name: str = "python-tofu",
) -> typer.Typer:
    """Return a Typer app whose commands render ``provider`` stacks."""

    app = typer.Typer(
        name=name,
        no_args_is_help=True,
        help=f"Manage {provider.label} infrastructure with a typed Python DSL and OpenTofu.",
    )

    def _show_version(value: bool) -> None:
        if value:
            typer.echo(f"{name} {version}")
            raise typer.Exit()

    @app.callback()
    def main(
        version_option: bool = typer.Option(
            False,
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ) -> None:
        """Manage infrastructure with a typed Python DSL and OpenTofu."""

    for command_name, create_app in COMMANDS:
        app.add_typer(create_app(provider), name=command_name)

    return app
