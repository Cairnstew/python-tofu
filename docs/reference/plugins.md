# Commands and Plugins

The CLI is a registry of command factories. `build_app(provider, ...)` renders
whatever the registry contains, so the command set is data, not a hard-coded
chain of imports.

## In-tree commands

Built-ins are listed once in `core/cli/commands/__init__.py`:

```python
_BUILTINS = (
    ("render", render.create_app, "Write the stack as OpenTofu HCL."),
    # ...
)
```

Each factory has the signature `create_app(provider) -> typer.Typer` and owns
its options. To add a command, add the module and one tuple entry. A decorator is
also available:

```python
from python_tofu.core.cli.registry import register_command


@register_command("audit", help="Print a stack inventory.", order=50)
def create_app(provider):
    ...
```

`order` controls display order (built-ins use 0–10; plugins default to 100).

## Out-of-tree packages

A package can add providers and commands without importing CLI internals, using
setuptools entry points:

```toml
# pyproject.toml of the plugin package
[project.entry-points."python_tofu.providers"]
acme = "acme_tofu:PROVIDER"

[project.entry-points."python_tofu.commands"]
acme = "acme_tofu.commands:SPECS"
```

A **provider** entry point resolves to a `Provider` (or a zero-argument callable
returning one):

```python
# acme_tofu/__init__.py
from python_tofu.core.doctor import CheckResult, CheckStatus
from python_tofu.core.provider import Provider, register_provider


def check_credentials(stack, workdir):
    return [CheckResult("credentials", CheckStatus.OK, "token minted")]


PROVIDER = register_provider(
    Provider(
        name="acme",
        display_name="Acme Cloud",
        stack_type=AcmeStack,
        renderer_type=AcmeRenderer,
        doctor_checks=check_credentials,  # powers `python-tofu doctor`
    )
)
```

A **command** entry point resolves to a `CommandSpec` or an iterable of them:

```python
# acme_tofu/commands.py
from pathlib import Path

import typer

from python_tofu.core.cli.base import BaseCommand
from python_tofu.core.cli.options import ConfigOption, make_context
from python_tofu.core.cli.registry import CommandSpec
from python_tofu.core.provider import Provider


def create_audit_app(provider: Provider) -> typer.Typer:
    app = typer.Typer(help="Print the loaded stack type.")

    @app.callback(invoke_without_command=True)
    def audit(config: ConfigOption = Path("infra.py")) -> None:
        command = BaseCommand(make_context(config, Path(".tofu"), "tofu", False, provider))
        stack = command.load()
        typer.echo(f"loaded {type(stack).__name__}")

    return app


SPECS = [
    CommandSpec("audit", create_audit_app, help="Print the loaded stack type."),
]
```

## Discovery behaviour

- Discovery runs in `build_app` unless `plugins=False` or
  `PYTHON_TOFU_NO_PLUGINS` is set to `1`/`true`/`yes`/`on`.
- A plugin that fails to import or has the wrong type is reported as a warning on
  stderr; the rest of the CLI still starts.
- Re-registering the same factory is a no-op, so importing a plugin module and
  also discovering it is safe.
- `python-tofu plugins` lists the active provider, every registered command and
  what discovery loaded. Add `--json` for machine-readable output.

```bash
python-tofu plugins
# Active provider: GCP (gcp)
# Commands:     render, init, validate, doctor, plan, apply, destroy, prune,
#               output, limits, apis, plugins
# Providers:    gcp
# Plugins:      none discovered
```

## Embedding

`build_app` accepts an explicit registry and disables discovery, which is useful
in tests or when a host application wants a fixed command set:

```python
from python_tofu.core.cli.app import build_app
from python_tofu.core.cli.registry import CommandRegistry

registry = CommandRegistry()
registry.register("hello", create_hello_app)

app = build_app(PROVIDER, version="1.0.0", commands=registry, plugins=False)
```

## Security

Plugins execute Python at CLI startup with the user's privileges. Install only
packages you trust, and use `PYTHON_TOFU_NO_PLUGINS=1` when running in an
environment where unexpected entry points would be a risk.
