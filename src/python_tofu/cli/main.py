"""Default (GCP) Typer application.

The commands themselves are provider-agnostic; see
:func:`python_tofu.core.cli.app.build_app` to bind a different provider.
"""

from __future__ import annotations

from python_tofu import __version__
from python_tofu.core.cli.app import build_app
from python_tofu.core.cli.registry import DEFAULT_COMMANDS
from python_tofu.providers.gcp import GCP
from python_tofu.providers.gcp.cli import apis

# ``apis`` is GCP-specific (Service Usage), so it is registered here rather
# than in the provider-agnostic core command list.
DEFAULT_COMMANDS.register(
    "apis",
    apis.create_app,
    help="List or resolve Google APIs via Service Usage.",
    order=9,
)

app = build_app(GCP, version=__version__)
