"""Default (GCP) Typer application.

The commands themselves are provider-agnostic; see
:func:`python_tofu.core.cli.app.build_app` to bind a different provider.
"""

from __future__ import annotations

from python_tofu import __version__
from python_tofu.core.cli.app import build_app
from python_tofu.providers.gcp import GCP

app = build_app(GCP, version=__version__)
