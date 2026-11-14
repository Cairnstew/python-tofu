from __future__ import annotations

from pathlib import Path

import pytest

from python_tofu.core import toolchain
from python_tofu.core.doctor import CheckStatus


def _fake_binary(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "tofu"
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture(autouse=True)
def _clear_mirror_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIX_TERRAFORM_PLUGIN_DIR", raising=False)
    monkeypatch.delenv("TF_PLUGIN_CACHE_DIR", raising=False)


# ── constraints ───────────────────────────────────────────────────────
def test_parse_version() -> None:
    assert toolchain.parse_version("1") == (1,)
    assert toolchain.parse_version("1.6") == (1, 6)
    assert toolchain.parse_version("1.12.1") == (1, 12, 1)
    assert toolchain.parse_version("1.12.1-beta") is None
    assert toolchain.parse_version("v1.12.1") is None


def test_satisfies_operators() -> None:
    cases = [
        ("1.12.1", ">= 1.6.0", True),
        ("1.5.0", ">= 1.6.0", False),
        ("2.0.0", ">= 1.6.0, < 2.0.0", False),
        ("1.9.0", ">= 1.6.0, < 2.0.0", True),
        ("7.33.0", "~> 7.0", True),
        ("8.0.0", "~> 7.0", False),
        ("7.0.5", "~> 7.0.0", True),
        ("7.1.0", "~> 7.0.0", False),
        ("1.6.0", "= 1.6.0", True),
    ]
    for version, constraint, expected in cases:
        parsed = toolchain.parse_constraints(constraint)
        assert parsed is not None, constraint
        assert toolchain.satisfies(version, parsed) is expected, (version, constraint)


def test_unparseable_constraint_is_unknown() -> None:
    assert toolchain.parse_constraints("") is None
    assert toolchain.parse_constraints(">= 1.6.0 || >= 2.0") is None


# ── binary ────────────────────────────────────────────────────────────
def test_binary_reads_json_version(tmp_path: Path) -> None:
    binary = _fake_binary(
        tmp_path,
        "printf '%s\\n' '{\"terraform_version\": \"1.12.1\"}'\n",
    )

    check = toolchain.check_binary(str(binary), ">= 1.6.0")

    assert check.status is CheckStatus.OK
    assert "1.12.1" in check.message


def test_binary_falls_back_to_text(tmp_path: Path) -> None:
    binary = _fake_binary(tmp_path, "echo 'OpenTofu v1.12.1'\necho 'on linux_amd64'\n")

    check = toolchain.check_binary(str(binary), "~> 1.12")

    assert check.status is CheckStatus.OK
    assert "1.12.1" in check.message


def test_binary_too_old_fails_with_fix(tmp_path: Path) -> None:
    binary = _fake_binary(
        tmp_path,
        "printf '%s\\n' '{\"terraform_version\": \"1.5.0\"}'\n",
    )

    check = toolchain.check_binary(str(binary), ">= 1.6.0")

    assert check.status is CheckStatus.FAIL
    assert "does not satisfy" in check.message
    assert "1.6.0" in str(check.fix)


def test_missing_binary_fails(tmp_path: Path) -> None:
    check = toolchain.check_binary(str(tmp_path / "absent"), ">= 1.6.0")

    assert check.status is CheckStatus.FAIL
    assert "not found" in check.message
    assert "PYTHON_TOFU_BINARY" in str(check.fix)


def test_unknown_constraint_is_unknown(tmp_path: Path) -> None:
    binary = _fake_binary(
        tmp_path,
        "printf '%s\\n' '{\"terraform_version\": \"1.12.1\"}'\n",
    )

    check = toolchain.check_binary(str(binary), ">= 1.6.0 || >= 2.0")

    assert check.status is CheckStatus.UNKNOWN


# ── provider mirror ───────────────────────────────────────────────────
def _mirror(root: Path, *versions: str) -> Path:
    base = root / "registry.opentofu.org" / "hashicorp" / "google"
    base.mkdir(parents=True)
    for version in versions:
        (base / version / "linux_amd64").mkdir(parents=True)
    return root


REQUIRED = {"google": {"source": "hashicorp/google", "version": "~> 7.0"}}


def test_provider_in_mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mirror = _mirror(tmp_path / "mirror", "7.33.0")
    monkeypatch.setenv("NIX_TERRAFORM_PLUGIN_DIR", str(mirror))

    check = toolchain.check_providers(REQUIRED)

    assert check.status is CheckStatus.OK
    assert "7.33.0" in check.message


def test_provider_in_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _mirror(tmp_path / "cache", "7.33.0")
    monkeypatch.setenv("TF_PLUGIN_CACHE_DIR", str(cache))

    assert toolchain.check_providers(REQUIRED).status is CheckStatus.OK


def test_provider_version_mismatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mirror = _mirror(tmp_path / "mirror", "6.50.0")
    monkeypatch.setenv("NIX_TERRAFORM_PLUGIN_DIR", str(mirror))

    check = toolchain.check_providers(REQUIRED)

    assert check.status is CheckStatus.FAIL
    assert "6.50.0" in check.message
    assert "~> 7.0" in check.message


def test_missing_mirror_root_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIX_TERRAFORM_PLUGIN_DIR", str(tmp_path / "absent"))

    check = toolchain.check_providers(REQUIRED)

    assert check.status is CheckStatus.FAIL
    assert "does not exist" in check.message


def test_no_mirror_is_skipped() -> None:
    check = toolchain.check_providers(REQUIRED)

    assert check.status is CheckStatus.SKIP


def test_no_required_providers_is_skipped() -> None:
    assert toolchain.check_providers({}).status is CheckStatus.SKIP


# ── workdir ───────────────────────────────────────────────────────────
def test_existing_workdir_is_ok(tmp_path: Path) -> None:
    assert toolchain.check_workdir(tmp_path).status is CheckStatus.OK


def test_missing_workdir_reports_creatable(tmp_path: Path) -> None:
    check = toolchain.check_workdir(tmp_path / "nested" / "state")

    assert check.status is CheckStatus.OK
    assert "creatable" in check.message


def test_file_as_workdir_fails(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("not a directory")

    check = toolchain.check_workdir(target)

    assert check.status is CheckStatus.FAIL
    assert "not a directory" in check.message
