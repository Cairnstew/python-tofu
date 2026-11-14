from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tofu.core.exceptions import RenderError
from python_tofu.providers.gcp import BillingBudget, GcpProvider, GcpStack
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"
ACCOUNT = "01ABCD-EFGH23-456789"


def _budget(**overrides: object) -> BillingBudget:
    values: dict[str, object] = {
        "billing_account": ACCOUNT,
        "display_name": "python-tofu guardrail",
        "amount": 5,
    }
    values.update(overrides)
    return BillingBudget(**values)  # type: ignore[arg-type]


def _stack(*budgets: BillingBudget) -> GcpStack:
    return GcpStack(provider=GcpProvider(project=PROJECT), billing_budgets=list(budgets))


def _main(stack: GcpStack) -> str:
    return " ".join(GcpRenderer(".tofu").render_text(stack)["main.tf"].split())


def test_budget_renders_alert_only_guardrail() -> None:
    text = _main(_stack(_budget()))

    assert 'resource "google_billing_budget" "budget_python_tofu_guardrail"' in text
    assert f'billing_account = "{ACCOUNT}"' in text
    assert 'display_name = "python-tofu guardrail"' in text
    assert 'currency_code = "USD"' in text
    assert 'units = "5"' in text
    assert "nanos" not in text
    assert "threshold_percent = 0.5" in text
    assert "threshold_percent = 0.9" in text
    assert "threshold_percent = 1.0" in text
    assert 'spend_basis = "CURRENT_SPEND"' in text
    # No notification target: the block is omitted so the provider default
    # (billing administrators) applies. An empty block fails validation.
    assert "all_updates_rule" not in text
    assert "depends_on = [google_project_service.api_billingbudgets_googleapis_com]" in text


def test_fractional_amount_uses_nanos() -> None:
    text = _main(_stack(_budget(amount=1.5)))

    assert 'units = "1"' in text
    assert "nanos = 500000000" in text


def test_project_filter_accepts_a_number_or_a_full_name() -> None:
    number = _main(_stack(_budget(project_filter="123456789")))
    full = _main(_stack(_budget(project_filter="projects/123456789")))

    assert 'projects = ["projects/123456789"]' in number
    assert 'projects = ["projects/123456789"]' in full


def test_project_filter_rejects_a_project_id() -> None:
    with pytest.raises(ValidationError, match="project number"):
        _budget(project_filter="demo-project")


def test_notification_settings_render() -> None:
    text = _main(
        _stack(
            _budget(
                pubsub_topic="projects/demo-project/topics/budget",
                notification_channels=["projects/demo-project/notificationChannels/1"],
                disable_default_recipients=True,
            )
        )
    )

    assert "all_updates_rule" in text
    assert 'pubsub_topic = "projects/demo-project/topics/budget"' in text
    assert "monitoring_notification_channels" in text
    assert "disable_default_iam_recipients = true" in text


def test_disabling_default_recipients_needs_a_target() -> None:
    with pytest.raises(ValidationError, match="disable_default_recipients"):
        _budget(disable_default_recipients=True)


def test_billing_account_prefix_is_stripped() -> None:
    budget = _budget(billing_account=f"billingAccounts/{ACCOUNT}")

    assert budget.billing_account == ACCOUNT


def test_duplicate_budget_display_names_collide() -> None:
    with pytest.raises(RenderError, match="duplicate resource address"):
        _main(_stack(_budget(), _budget(amount=10)))


def test_budget_requires_a_billing_account() -> None:
    with pytest.raises(ValidationError, match="billing_account"):
        BillingBudget.model_validate(
            {"display_name": "guardrail", "amount": 5}  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("amount", [0, -1, float("inf")])
def test_amount_must_be_a_positive_finite_number(amount: float) -> None:
    with pytest.raises(ValidationError, match="amount"):
        _budget(amount=amount)


@pytest.mark.parametrize("thresholds", [(), (0.0,), (1.5,), (0.5, 0.5)])
def test_thresholds_are_distinct_fractions(thresholds: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError, match="threshold"):
        _budget(thresholds=thresholds)
