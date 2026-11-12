from __future__ import annotations

import json
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from python_tofu.core.cli import registry as registry_module
from python_tofu.core.cli.app import build_app
from python_tofu.core.cli.registry import (
    COMMAND_GROUP,
    PROVIDER_GROUP,
    CommandRegistry,
    CommandSpec,
    discover_plugins,
    plugins_disabled,
)
from python_tofu.core.exceptions import TofuError
from python_tofu.providers.gcp import GCP


def _echo_app(provider: Any) -> typer.Typer:
    app = typer.Typer()

    @app.callback(invoke_without_command=True)
    def echo() -> None:
        typer.echo(f"hello from {provider.name}")

    return app


class _EntryPoint:
    def __init__(self, name: str, value: object) -> None:
        self.name = name
        self._value = value

    def load(self) -> object:
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


def test_registry_orders_commands_and_treats_a_repeat_as_a_no_op() -> None:
    registry = CommandRegistry()
    registry.register("later", _echo_app, order=20)
    first = registry.register("first", _echo_app, order=10)

    assert registry.names() == ("first", "later")
    assert registry.get("first") is first
    assert registry.register("first", _echo_app) is first


def test_registry_rejects_conflicting_names_and_aliases() -> None:
    registry = CommandRegistry()
    registry.register("taken", _echo_app)

    with pytest.raises(TofuError, match="already registered"):
        registry.register("taken", lambda provider: typer.Typer())
    with pytest.raises(TofuError, match="alias"):
        registry.register("other", _echo_app, aliases=("taken",))
    with pytest.raises(TofuError, match="alias itself"):
        registry.register("self", _echo_app, aliases=("self",))


def test_build_app_accepts_a_custom_registry_and_renders_aliases() -> None:
    registry = CommandRegistry()
    registry.register("hello", _echo_app, aliases=("hi",))
    app = build_app(GCP, version="0.0.0", commands=registry, plugins=False)

    runner = CliRunner()
    for name in ("hello", "hi"):
        result = runner.invoke(app, [name])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "hello from gcp"


def test_discovery_registers_providers_and_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = CommandRegistry()
    entries = {
        PROVIDER_GROUP: [
            _EntryPoint("direct", GCP),
            _EntryPoint("factory", lambda: GCP),
        ],
        COMMAND_GROUP: [_EntryPoint("hello", CommandSpec("hello", _echo_app))],
    }
    monkeypatch.setattr(registry_module, "_entry_points", lambda group: entries.get(group, []))
    monkeypatch.setattr(registry_module, "register_provider", lambda provider: provider)

    report = discover_plugins(registry)

    assert report.providers == ("gcp",)
    assert report.commands == ("hello",)
    assert report.errors == ()
    assert registry.get("hello").factory is _echo_app
    assert registry.last_report is report


def test_discovery_records_failures_without_aborting(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = CommandRegistry()
    entries = {
        PROVIDER_GROUP: [_EntryPoint("broken", RuntimeError("boom"))],
        COMMAND_GROUP: [
            _EntryPoint("bad", object()),
            _EntryPoint("hello", CommandSpec("hello", _echo_app)),
        ],
    }
    monkeypatch.setattr(registry_module, "_entry_points", lambda group: entries.get(group, []))

    report = discover_plugins(registry)

    assert registry.names() == ("hello",)
    assert len(report.errors) == 2
    assert "boom" in report.errors[0]
    assert "expected CommandSpec" in report.errors[1]


def test_build_app_can_skip_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(registry: CommandRegistry) -> None:
        raise AssertionError("discovery should be skipped")

    monkeypatch.setattr("python_tofu.core.cli.app.discover_plugins", fail)
    app = build_app(GCP, version="0.0.0", plugins=False)
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0, result.output


def test_plugins_env_disables_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHON_TOFU_NO_PLUGINS", "1")

    def fail(registry: CommandRegistry) -> None:
        raise AssertionError("discovery should be skipped")

    monkeypatch.setattr("python_tofu.core.cli.app.discover_plugins", fail)

    assert plugins_disabled() is True
    app = build_app(GCP, version="0.0.0")
    assert CliRunner().invoke(app, ["--version"]).exit_code == 0


def test_register_command_decorator_uses_the_default_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CommandRegistry()
    monkeypatch.setattr(registry_module, "DEFAULT_COMMANDS", registry)

    decorated = registry_module.register_command("hello", order=1)(_echo_app)

    assert decorated is _echo_app
    assert registry.names() == ("hello",)


def test_plugins_command_reports_commands_and_provider() -> None:
    from python_tofu.cli.main import app

    result = CliRunner().invoke(app, ["plugins", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["active_provider"] == "gcp"
    assert "render" in payload["commands"]
    assert "plugins" in payload["commands"]
    assert payload["errors"] == []
