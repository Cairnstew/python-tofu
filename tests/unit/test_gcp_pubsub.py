from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tofu.providers.gcp import (
    CloudRunService,
    DeadLetter,
    GcpProvider,
    GcpStack,
    PubSubSubscription,
    PubSubTopic,
    RetryPolicy,
    ServiceAccount,
)
from python_tofu.providers.gcp import prune as gcp_prune
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _topic(**overrides: object) -> PubSubTopic:
    values: dict[str, object] = {"project": PROJECT, "name": "jobs"}
    values.update(overrides)
    return PubSubTopic(**values)  # type: ignore[arg-type]


def _subscription(**overrides: object) -> PubSubSubscription:
    values: dict[str, object] = {"project": PROJECT, "name": "jobs-sub", "topic": "jobs"}
    values.update(overrides)
    return PubSubSubscription(**values)  # type: ignore[arg-type]


def _stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "provider": GcpProvider(project=PROJECT, region="us-central1"),
        "pubsub_topics": [_topic()],
        "pubsub_subscriptions": [_subscription()],
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


def _main(stack: GcpStack) -> str:
    return " ".join(GcpRenderer(".tofu").render_text(stack)["main.tf"].split())


# ── topics ────────────────────────────────────────────────────────────
def test_topic_renders_with_retention() -> None:
    text = _main(_stack(pubsub_topics=[_topic(message_retention_duration="600s")]))

    assert 'resource "google_pubsub_topic" "topic_jobs"' in text
    assert 'name = "jobs"' in text
    assert 'message_retention_duration = "600s"' in text


@pytest.mark.parametrize(
    "value",
    ["599s", "31d", "2678401s"],
)
def test_topic_rejects_out_of_range_retention(value: str) -> None:
    with pytest.raises(ValidationError, match="retention"):
        _topic(message_retention_duration=value)


# ── subscriptions ─────────────────────────────────────────────────────
def test_pull_subscription_defaults_to_declared_topic() -> None:
    text = _main(_stack())

    assert 'resource "google_pubsub_subscription" "sub_jobs_sub"' in text
    assert "topic = google_pubsub_topic.topic_jobs.id" in text
    assert "ack_deadline_seconds = 10" in text
    assert 'ttl = "2678400s"' in text
    assert "push_config" not in text
    assert "filter" not in text
    assert 'data "google_project"' not in text


def test_subscription_opts_into_ordering_and_exactly_once() -> None:
    text = _main(
        _stack(
            pubsub_subscriptions=[
                _subscription(enable_message_ordering=True, enable_exactly_once_delivery=True)
            ]
        )
    )

    assert "enable_message_ordering = true" in text
    assert "enable_exactly_once_delivery = true" in text


def test_subscription_renders_filter_and_retry() -> None:
    text = _main(
        _stack(
            pubsub_subscriptions=[
                _subscription(
                    filter='attributes.kind="keep"',
                    retry=RetryPolicy(minimum_backoff="5s", maximum_backoff="60s"),
                )
            ]
        )
    )

    assert 'filter = "attributes.kind=\\"keep\\""' in text
    assert "retry_policy" in text
    assert 'minimum_backoff = "5s"' in text
    assert 'maximum_backoff = "60s"' in text


def test_external_topic_resolves_to_full_path() -> None:
    text = _main(
        _stack(
            pubsub_topics=[],
            pubsub_subscriptions=[_subscription(topic="external-topic")],
            external_topics=["external-topic"],
        )
    )

    assert 'topic = "projects/demo-project/topics/external-topic"' in text


def test_external_topic_path_is_left_alone() -> None:
    text = _main(
        _stack(
            pubsub_topics=[],
            pubsub_subscriptions=[_subscription(topic="projects/other/topics/shared")],
            external_topics=["shared"],
        )
    )

    assert 'topic = "projects/other/topics/shared"' in text


# ── push ──────────────────────────────────────────────────────────────
def test_push_to_declared_service_wires_uri_and_identity() -> None:
    stack = _stack(
        service_accounts=[ServiceAccount(project=PROJECT, account_id="pubsub-push")],
        cloud_run_services=[
            CloudRunService(
                project=PROJECT,
                name="api",
                image="image",
                invoker_service_accounts=["pubsub-push"],
            )
        ],
        pubsub_subscriptions=[
            _subscription(
                name="jobs-push",
                push_service="api",
                push_service_account="pubsub-push",
            )
        ],
    )
    text = _main(stack)

    assert "push_config" in text
    assert "push_endpoint = google_cloud_run_v2_service.run_api.uri" in text
    assert "service_account_email = google_service_account.sa_pubsub_push.email" in text
    assert 'member = "serviceAccount:${google_service_account.sa_pubsub_push.email}"' in text


def test_push_to_explicit_endpoint_keeps_literal_url() -> None:
    text = _main(
        _stack(pubsub_subscriptions=[_subscription(push_endpoint="https://example.test/hook")])
    )

    assert 'push_endpoint = "https://example.test/hook"' in text
    assert "oidc_token" not in text


def test_exactly_once_with_push_is_rejected() -> None:
    with pytest.raises(ValidationError, match="pull subscriptions only"):
        _subscription(
            push_endpoint="https://example.test/hook",
            enable_exactly_once_delivery=True,
        )


# ── dead-letter ───────────────────────────────────────────────────────
def test_dead_letter_adds_policy_and_publisher_grant() -> None:
    stack = _stack(
        pubsub_topics=[_topic(name="jobs"), _topic(name="jobs-dlq")],
        pubsub_subscriptions=[
            _subscription(dead_letter=DeadLetter(topic="jobs-dlq", max_delivery_attempts=10))
        ],
    )
    text = _main(stack)

    assert "dead_letter_policy" in text
    assert "dead_letter_topic = google_pubsub_topic.topic_jobs_dlq.id" in text
    assert "max_delivery_attempts = 10" in text
    assert 'resource "google_pubsub_topic_iam_member" "dlq_publisher_demo_project_jobs_dlq"' in text
    assert 'role = "roles/pubsub.publisher"' in text
    assert "service-${data.google_project.project_demo_project.number}" in text
    assert text.count('data "google_project" "project_demo_project"') == 1


def test_shared_dead_letter_topic_grants_once() -> None:
    stack = _stack(
        pubsub_topics=[_topic(name="jobs"), _topic(name="jobs-dlq")],
        pubsub_subscriptions=[
            _subscription(name="one", dead_letter=DeadLetter(topic="jobs-dlq")),
            _subscription(name="two", dead_letter=DeadLetter(topic="jobs-dlq")),
        ],
    )
    text = _main(stack)

    assert text.count('resource "google_pubsub_topic_iam_member"') == 1
    assert text.count('data "google_project"') == 1


def test_dead_letter_cannot_target_own_topic() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        _subscription(dead_letter=DeadLetter(topic="jobs"))


# ── validation ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "bad name", "Pub/Sub names"),
        ("expiration_ttl", "", "expiration_ttl"),
        ("expiration_ttl", "3600s", "at least 86400s"),
        ("message_retention_duration", "999999s", "between 10 minutes and 7 days"),
        ("ack_deadline_seconds", 601, "less than or equal to 600"),
    ],
)
def test_subscription_rejects_invalid_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _subscription(**{field: value})


def test_filter_is_limited_to_256_bytes() -> None:
    with pytest.raises(ValidationError, match="256 bytes"):
        _subscription(filter="a" * 257)


def test_push_audience_requires_identity() -> None:
    with pytest.raises(ValidationError, match="push_audience requires"):
        _subscription(push_service="api", push_audience="https://api")


def test_push_identity_requires_a_target() -> None:
    with pytest.raises(ValidationError, match="requires push_endpoint or push_service"):
        _subscription(push_service_account="push@demo-project.iam.gserviceaccount.com")


def test_retry_backoff_order_is_validated() -> None:
    with pytest.raises(ValidationError, match="minimum_backoff"):
        RetryPolicy(minimum_backoff="120s", maximum_backoff="60s")


def test_unknown_topic_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown topics"):
        _stack(pubsub_topics=[], pubsub_subscriptions=[_subscription()])


def test_unknown_dead_letter_topic_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown dead-letter topics"):
        _stack(pubsub_subscriptions=[_subscription(dead_letter=DeadLetter(topic="missing-dlq"))])


def test_unknown_push_service_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown Cloud Run services"):
        _stack(
            pubsub_subscriptions=[
                _subscription(push_service="missing", push_service_account="a@b.c")
            ]
        )


def test_unknown_service_account_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown service accounts"):
        _stack(
            pubsub_subscriptions=[
                _subscription(
                    push_endpoint="https://example.test/hook",
                    push_service_account="not-declared",
                )
            ]
        )


def test_duplicate_topic_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate Pub/Sub topic names"):
        _stack(pubsub_topics=[_topic(), _topic()])


# ── prune discovery ───────────────────────────────────────────────────
TOPICS = [
    {"name": "projects/demo-project/topics/declared-jobs"},
    {"name": "projects/demo-project/topics/stray-jobs", "messageRetentionDuration": "600s"},
]

SUBSCRIPTIONS = [
    {
        "name": "projects/demo-project/subscriptions/declared-sub",
        "topic": "projects/demo-project/topics/declared-jobs",
        "ackDeadlineSeconds": 10,
    },
    {
        "name": "projects/demo-project/subscriptions/stray-sub",
        "topic": "projects/demo-project/topics/stray-jobs",
        "ackDeadlineSeconds": 30,
        "messageRetentionDuration": "1200s",
        "expirationPolicy": {"ttl": "2678400s"},
        "filter": 'attributes.kind="keep"',
        "deadLetterPolicy": {
            "deadLetterTopic": "projects/demo-project/topics/stray-dlq",
            "maxDeliveryAttempts": 7,
        },
        "pushConfig": {
            "pushEndpoint": "https://example.test/hook",
            "oidcToken": {"serviceAccountEmail": "push@demo-project.iam.gserviceaccount.com"},
        },
    },
]


@pytest.fixture
def pubsub_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gcp_prune, "access_token", lambda stack: "token")
    monkeypatch.setattr(gcp_prune, "list_buckets", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "list_service_accounts", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "list_services", lambda project, token: [])
    monkeypatch.setattr(gcp_prune, "list_topics", lambda project, token: TOPICS)
    monkeypatch.setattr(gcp_prune, "list_subscriptions", lambda project, token: SUBSCRIPTIONS)


def test_prune_discovers_undeclared_topics_and_subscriptions(
    pubsub_inventory: None,
) -> None:
    stack = _stack(
        pubsub_topics=[_topic(name="declared-jobs")],
        pubsub_subscriptions=[_subscription(name="declared-sub", topic="declared-jobs")],
    )
    plan = gcp_prune.discover(stack, ("subscriptions", "topics"))

    by_section = {
        section: [resource.description for resource in group]
        for section, group in plan.by_section(("subscriptions", "topics"))
    }
    assert by_section == {
        "subscriptions": ["subscription stray-sub"],
        "topics": ["topic stray-jobs"],
    }

    subscription = next(r for r in plan.resources if r.section == "subscriptions")
    assert subscription.import_id == "projects/demo-project/subscriptions/stray-sub"
    assert subscription.address == "google_pubsub_subscription.sub_stray_sub"
    text = GcpRenderer(".tofu").render_text(
        _stack(
            pubsub_topics=[_topic(name="stray-jobs"), _topic(name="stray-dlq")],
            pubsub_subscriptions=[subscription_model()],
        )
    )["main.tf"]
    assert "dead_letter_policy" in text

    topic = next(r for r in plan.resources if r.section == "topics")
    assert topic.import_id == "projects/demo-project/topics/stray-jobs"


def subscription_model() -> PubSubSubscription:
    return PubSubSubscription(
        project=PROJECT,
        name="stray-sub",
        topic="stray-jobs",
        ack_deadline_seconds=30,
        message_retention_duration="1200s",
        filter='attributes.kind="keep"',
        dead_letter=DeadLetter(topic="stray-dlq"),
        push_endpoint="https://example.test/hook",
        push_service_account="push@demo-project.iam.gserviceaccount.com",
    )


def test_prune_reconstructs_live_subscription_fields() -> None:
    model = gcp_prune._subscription_model(PROJECT, SUBSCRIPTIONS[1])

    assert model.ack_deadline_seconds == 30
    assert model.message_retention_duration == "1200s"
    assert model.filter == 'attributes.kind="keep"'
    assert model.dead_letter is not None
    assert model.dead_letter.max_delivery_attempts == 7
    assert model.push_endpoint == "https://example.test/hook"
    assert model.push_service_account == "push@demo-project.iam.gserviceaccount.com"
    assert model.expiration_ttl == "2678400s"


def test_sections_prune_subscriptions_before_topics() -> None:
    from python_tofu.providers.gcp.models import GCP_PRUNE_SECTIONS

    assert GCP_PRUNE_SECTIONS.index("subscriptions") < GCP_PRUNE_SECTIONS.index("topics")


def test_prune_warns_when_topics_are_selected_without_subscriptions(
    pubsub_inventory: None,
) -> None:
    plan = gcp_prune.discover(_stack(), ("topics",))

    assert any("without subscriptions" in warning for warning in plan.warnings)
