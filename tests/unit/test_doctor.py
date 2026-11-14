from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from python_tofu.core.doctor import CheckResult, CheckStatus, DoctorReport
from python_tofu.providers.gcp import GcpProvider, GcpStack
from python_tofu.providers.gcp.apis import DEFAULT_APIS, STORAGE
from python_tofu.providers.gcp.cli import doctor as doctor_module
from python_tofu.providers.gcp.live import GoogleApiError
from python_tofu.providers.gcp.services import Service

PROJECT = "demo-project"
BUCKET = "demo-state"


# ── value objects ─────────────────────────────────────────────────────
def test_status_symbols() -> None:
    assert CheckStatus.OK.symbol == "✓"
    assert CheckStatus.FAIL.symbol == "✗"
    assert CheckStatus.UNKNOWN.symbol == "?"
    assert CheckStatus.SKIP.symbol == "-"


def test_report_exit_codes_and_json() -> None:
    ok = CheckResult("a", CheckStatus.OK, "fine")
    bad = CheckResult("b", CheckStatus.FAIL, "broken", fix="fix it")
    unknown = CheckResult("c", CheckStatus.UNKNOWN, "who knows")

    assert DoctorReport((ok,)).exit_code() == 0
    assert DoctorReport((ok, bad)).exit_code() == 1
    assert DoctorReport((ok, unknown)).exit_code() == 0
    assert DoctorReport((ok, unknown)).exit_code(fail_on_unknown=True) == 1

    payload = DoctorReport((ok, bad, unknown)).as_dict()
    assert payload["ok"] is False
    assert payload["failed"] == 1
    assert payload["unknown"] == 1
    assert payload["checks"][1]["fix"] == "fix it"


# ── GCP checks with a fake API ────────────────────────────────────────
def _stack(**overrides: Any) -> GcpStack:
    from python_tofu.providers.gcp import BackendConfig, StorageBucket

    values: dict[str, Any] = {
        "provider": GcpProvider(project=PROJECT),
        "buckets": [StorageBucket(project=PROJECT, name="demo-artifacts")],
        "backend": BackendConfig(kind="gcs", bucket=BUCKET),
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


class _Catalog:
    enabled_names: set[str] = set(DEFAULT_APIS)

    def __init__(self, project: str, *, token: str | None = None, **_: Any) -> None:
        self.project = project
        self._token = token

    def enabled(self, filter: str | None = None) -> tuple[Service, ...]:
        return tuple(Service(name=name, state="ENABLED") for name in sorted(self.enabled_names))


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Route fake GETs by URL; tests mutate ``state`` to simulate failures."""

    state: dict[str, Any] = {
        "project": {"lifecycleState": "ACTIVE", "name": "Demo"},
        "billing": {"billingEnabled": True, "billingAccountName": "billingAccounts/0123"},
        "bucket_missing": False,
        "lock": False,
        "billing_status": None,
        "project_status": None,
        "errors": [],
    }

    def fake_token(stack: GcpStack) -> str:
        return "token"

    def fake_get(
        url: str,
        token: str,
        params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if url == doctor_module.TOKENINFO:
            return {"email": "ci@demo-project.iam.gserviceaccount.com", "expires_in": "3600"}
        if url.endswith(f"/projects/{PROJECT}"):
            if state["project_status"]:
                raise GoogleApiError("not found", status=state["project_status"])
            return state["project"]
        if url.endswith(f"/projects/{PROJECT}/billingInfo"):
            if state["billing_status"]:
                raise GoogleApiError("denied", status=state["billing_status"])
            return state["billing"]
        if url == f"{doctor_module.STORAGE}/b/{BUCKET}":
            if state["bucket_missing"]:
                raise GoogleApiError("not found", status=404)
            return {"name": BUCKET}
        if url.startswith(f"{doctor_module.STORAGE}/b/{BUCKET}/o/"):
            if state["lock"]:
                return {"name": "lock"}
            raise GoogleApiError("not found", status=404)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(doctor_module.live, "access_token", fake_token)
    monkeypatch.setattr(doctor_module.live, "get_json", fake_get)
    monkeypatch.setattr(doctor_module, "ServiceCatalog", _Catalog)
    _Catalog.enabled_names = set(DEFAULT_APIS)
    return state


def test_all_checks_pass(api: dict[str, Any], tmp_path: Path) -> None:
    checks = doctor_module.run_checks(_stack(), tmp_path)

    statuses = {check.name: check.status for check in checks}
    assert statuses == {
        "credentials": CheckStatus.OK,
        "project": CheckStatus.OK,
        "billing": CheckStatus.OK,
        "APIs": CheckStatus.OK,
        "backend": CheckStatus.OK,
        "state lock": CheckStatus.OK,
    }
    assert "expires in 60m" in checks[0].message
    assert "prefix python-tofu/state" in checks[4].message


def test_credentials_identity_falls_back_to_the_key_file(
    api: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = tmp_path / "key.json"
    key.write_text(json.dumps({"client_email": "ci@demo.iam.gserviceaccount.com"}))
    monkeypatch.setattr(doctor_module, "_tokeninfo", lambda token: {})
    stack = _stack(provider=GcpProvider(project=PROJECT, credentials=str(key)))

    check, token = doctor_module.check_credentials(stack)

    assert token == "token"
    assert check.status is CheckStatus.OK
    assert "ci@demo.iam.gserviceaccount.com" in check.message


def test_missing_credentials_skips_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(stack: GcpStack) -> str:
        raise GoogleApiError("could not obtain Google credentials: no key")

    monkeypatch.setattr(doctor_module.live, "access_token", boom)

    checks = doctor_module.run_checks(_stack(), tmp_path)

    assert checks[0].status is CheckStatus.FAIL
    assert checks[0].fix == "gcloud auth application-default login"
    assert all(check.status is CheckStatus.UNKNOWN for check in checks[1:])
    assert "credentials unavailable" in checks[1].message


def test_non_active_project_fails(api: dict[str, Any], tmp_path: Path) -> None:
    api["project"] = {"lifecycleState": "SUSPENDED"}

    checks = {check.name: check for check in doctor_module.run_checks(_stack(), tmp_path)}

    assert checks["project"].status is CheckStatus.FAIL
    assert "SUSPENDED" in checks["project"].message


def test_missing_project_fails_with_fix(api: dict[str, Any], tmp_path: Path) -> None:
    api["project_status"] = 404

    checks = {check.name: check for check in doctor_module.run_checks(_stack(), tmp_path)}

    assert checks["project"].status is CheckStatus.FAIL
    assert "does not exist" in checks["project"].message
    assert checks["project"].fix


def test_disabled_billing_fails(api: dict[str, Any], tmp_path: Path) -> None:
    api["billing"] = {"billingEnabled": False}

    checks = {check.name: check for check in doctor_module.run_checks(_stack(), tmp_path)}

    assert checks["billing"].status is CheckStatus.FAIL
    assert "gcloud billing projects link" in (checks["billing"].fix or "")


def test_disabled_apis_are_listed(api: dict[str, Any], tmp_path: Path) -> None:
    _Catalog.enabled_names = set(DEFAULT_APIS) - {STORAGE}

    checks = {check.name: check for check in doctor_module.run_checks(_stack(), tmp_path)}

    assert checks["APIs"].status is CheckStatus.FAIL
    assert "storage.googleapis.com" in checks["APIs"].message
    assert "gcloud services enable storage.googleapis.com" in str(checks["APIs"].fix)


def test_missing_backend_bucket_fails(api: dict[str, Any], tmp_path: Path) -> None:
    api["bucket_missing"] = True

    checks = {check.name: check for check in doctor_module.run_checks(_stack(), tmp_path)}

    assert checks["backend"].status is CheckStatus.FAIL
    assert f"gs://{BUCKET} does not exist" in checks["backend"].message
    assert "gcloud storage buckets create" in str(checks["backend"].fix)


def test_present_state_lock_fails(api: dict[str, Any], tmp_path: Path) -> None:
    api["lock"] = True

    checks = {check.name: check for check in doctor_module.run_checks(_stack(), tmp_path)}

    assert checks["state lock"].status is CheckStatus.FAIL
    assert "another apply may be running" in checks["state lock"].message


def test_local_backend_reports_creatable_and_skips_lock(
    api: dict[str, Any], tmp_path: Path
) -> None:
    workdir = tmp_path / "nested" / "state"

    checks = {
        check.name: check
        for check in doctor_module.run_checks(_stack(backend=None, name="dev"), workdir)
    }

    assert checks["backend"].status is CheckStatus.OK
    assert "creatable" in checks["backend"].message
    assert checks["state lock"].status is CheckStatus.SKIP


def test_billing_permission_denied_is_unknown(api: dict[str, Any], tmp_path: Path) -> None:
    api["billing_status"] = 403

    checks = {check.name: check for check in doctor_module.run_checks(_stack(), tmp_path)}

    assert checks["billing"].status is CheckStatus.UNKNOWN
    assert "permission denied" in checks["billing"].message


# ── CLI ───────────────────────────────────────────────────────────────
def _write_config(path: Path, *, backend: bool = True) -> Path:
    backend_line = f'    backend=BackendConfig(kind="gcs", bucket="{BUCKET}"),\n' if backend else ""
    path.write_text(
        f"""\
from python_tofu import BackendConfig, GcpProvider, GcpStack, StorageBucket

stack = GcpStack(
    provider=GcpProvider(project="{PROJECT}"),
{backend_line}    buckets=[StorageBucket(project="{PROJECT}", name="demo-artifacts")],
)
""",
        encoding="utf-8",
    )
    return path


def test_cli_doctor_passes_and_renders_a_checklist(
    api: dict[str, Any],
    cli,
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")

    result = runner.invoke(cli, ["doctor", "--config", str(config)])

    assert result.exit_code == 0, result.output
    for name in ("credentials", "project", "billing", "APIs", "backend", "state lock"):
        assert name in result.output
    assert "No blocking problems found." in result.output


def test_cli_doctor_exits_1_on_failure(
    api: dict[str, Any],
    cli,
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")
    _Catalog.enabled_names = {"serviceusage.googleapis.com"}

    result = runner.invoke(cli, ["doctor", "--config", str(config)])

    assert result.exit_code == 1
    assert "fix: gcloud services enable" in result.output
    assert "Doctor found" in result.output


def test_cli_doctor_json(
    api: dict[str, Any],
    cli,
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")

    result = runner.invoke(cli, ["doctor", "--config", str(config), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert {check["name"] for check in payload["checks"]} >= {"credentials", "project"}


def test_cli_doctor_fail_on_unknown(
    api: dict[str, Any],
    cli,
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")
    api["billing_status"] = 403

    result = runner.invoke(cli, ["doctor", "--config", str(config)])

    assert result.exit_code == 0, result.output

    strict = runner.invoke(cli, ["doctor", "--config", str(config), "--fail-on-unknown"])

    assert strict.exit_code == 1


def test_cli_doctor_never_renders(
    api: dict[str, Any],
    cli,
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path / "infra.py")

    result = runner.invoke(cli, ["doctor", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".tofu").exists()
