"""Built-in command factories, registered in display order.

Adding an in-tree command means adding one entry to ``_BUILTINS`` (or decorating
its ``create_app`` with :func:`~python_tofu.core.cli.registry.register_command`).
Out-of-tree packages extend the CLI through entry points instead; see
``core/cli/registry.py``.
"""

from python_tofu.core.cli.commands import (
    apply,
    destroy,
    doctor,
    init,
    limits,
    output,
    plan,
    plugins,
    prune,
    quota,
    render,
    validate,
)
from python_tofu.core.cli.registry import DEFAULT_COMMANDS

_BUILTINS = (
    ("render", render.create_app, "Write the stack as OpenTofu HCL."),
    ("init", init.create_app, "Render and run `tofu init`."),
    ("validate", validate.create_app, "Render, init and run `tofu validate`."),
    (
        "doctor",
        doctor.create_app,
        "Check credentials, project state, billing, APIs and the backend.",
    ),
    ("plan", plan.create_app, "Render, init and summarise a plan."),
    ("apply", apply.create_app, "Render, init and apply the stack."),
    ("destroy", destroy.create_app, "Render, init and destroy the stack."),
    ("prune", prune.create_app, "Delete live resources the stack does not declare."),
    (
        "quota",
        quota.create_app,
        "Apply the declared quota overrides (hard usage ceilings).",
    ),
    ("output", output.create_app, "Read outputs from the working directory."),
    ("limits", limits.create_app, "Show provider limits and measured usage."),
    ("plugins", plugins.create_app, "Show commands, providers and plugins."),
)

for _order, (_name, _factory, _help) in enumerate(_BUILTINS):
    DEFAULT_COMMANDS.register(_name, _factory, help=_help, order=_order)

#: Backwards-compatible ``(name, factory)`` view of the registry.
COMMANDS = DEFAULT_COMMANDS.pairs()

__all__ = [
    "COMMANDS",
    "apply",
    "destroy",
    "doctor",
    "init",
    "limits",
    "output",
    "plan",
    "plugins",
    "prune",
    "quota",
    "render",
    "validate",
]
