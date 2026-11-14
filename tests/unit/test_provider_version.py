from __future__ import annotations

from pathlib import Path

import pytest

from python_tofu.providers.gcp.models import GcpProvider
from python_tofu.providers.gcp.renderer import GcpRenderer
from python_tofu.providers.gcp.stack import (
    DEFAULT_GOOGLE_PROVIDER_VERSION,
    PROVIDER_VERSION_ENV,
    GcpStack,
)


def _stack(**kwargs: object) -> GcpStack:
    return GcpStack(provider=GcpProvider(project="demo-project"), **kwargs)


def test_default_provider_version_is_the_literal_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PROVIDER_VERSION_ENV, raising=False)
    assert _stack().google_provider_version == DEFAULT_GOOGLE_PROVIDER_VERSION


def test_build_environment_overrides_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROVIDER_VERSION_ENV, "~> 9.0")
    assert _stack().google_provider_version == "~> 9.0"


def test_explicit_stack_value_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROVIDER_VERSION_ENV, "~> 9.0")
    stack = _stack(google_provider_version="~> 7.5")
    assert stack.google_provider_version == "~> 7.5"


def test_rendered_versions_file_uses_the_resolved_constraint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PROVIDER_VERSION_ENV, "~> 9.0")
    GcpRenderer(tmp_path).render(_stack())
    versions = (tmp_path / "versions.tf").read_text(encoding="utf-8")
    assert '"version" = "~> 9.0"' in versions
