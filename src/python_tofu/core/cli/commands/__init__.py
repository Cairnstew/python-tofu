"""Command factories shared by every provider.

Each module exposes ``create_app(provider)``; the provider is captured by the
command closure, so adding a provider does not require touching the core CLI.
"""

from python_tofu.core.cli.commands import (
    apply,
    destroy,
    init,
    limits,
    output,
    plan,
    render,
    validate,
)

COMMANDS = (
    ("render", render.create_app),
    ("init", init.create_app),
    ("validate", validate.create_app),
    ("plan", plan.create_app),
    ("apply", apply.create_app),
    ("destroy", destroy.create_app),
    ("output", output.create_app),
    ("limits", limits.create_app),
)

__all__ = [
    "COMMANDS",
    "apply",
    "destroy",
    "init",
    "limits",
    "output",
    "plan",
    "render",
    "validate",
]
