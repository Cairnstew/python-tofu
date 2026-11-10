from __future__ import annotations

import pytest
from typer.testing import CliRunner

from python_tofu.core.cli.app import build_app
from python_tofu.core.exceptions import TofuError
from python_tofu.core.hcl import Block
from python_tofu.core.models import BaseStack
from python_tofu.core.provider import (
    Provider,
    available_providers,
    get_provider,
    register_provider,
)
from python_tofu.core.renderer import BaseRenderer
from python_tofu.providers.gcp import GCP, GcpRenderer, GcpStack


def test_gcp_is_registered_and_wired_to_core_types() -> None:
    assert "gcp" in available_providers()
    assert get_provider("gcp") is GCP
    assert GCP.stack_type is GcpStack
    assert GCP.renderer_type is GcpRenderer
    assert issubclass(GcpStack, BaseStack)
    assert issubclass(GcpRenderer, BaseRenderer)


def test_unknown_provider_raises() -> None:
    with pytest.raises(TofuError, match="unknown provider"):
        get_provider("not-a-provider")


class DummyStack(BaseStack):
    greeting: str = "hello"


class DummyRenderer(BaseRenderer[DummyStack]):
    def required_providers(self, stack: DummyStack) -> dict[str, dict[str, str]]:
        return {"dummy": {"source": "example/dummy", "version": "~> 1.0"}}

    def provider_blocks(self, stack: DummyStack) -> list[Block]:
        return [Block("provider", ("dummy",), ())]

    def resource_blocks(self, stack: DummyStack) -> list[Block]:
        return []


def test_core_renders_a_non_gcp_provider() -> None:
    files = DummyRenderer(".tofu").render_text(DummyStack())
    assert '"source" = "example/dummy"' in files["versions.tf"]
    assert 'provider "dummy" {}' in files["providers.tf"]
    assert files["main.tf"] == "# No resources declared in the stack.\n"


def test_cli_can_be_bound_to_another_provider() -> None:
    dummy = register_provider(
        Provider(
            name="dummy",
            display_name="Dummy",
            stack_type=DummyStack,
            renderer_type=DummyRenderer,
        )
    )
    app = build_app(dummy, version="9.9.9", name="dummy-tofu")

    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "dummy-tofu 9.9.9"
