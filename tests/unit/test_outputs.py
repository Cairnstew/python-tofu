from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tofu import Output, ref
from python_tofu.core.models import BaseStack
from python_tofu.providers.gcp import GcpProvider, GcpStack, PubSubTopic
from python_tofu.providers.gcp.renderer import GcpRenderer

PROJECT = "demo-project"


def _stack(**overrides: object) -> GcpStack:
    values: dict[str, object] = {
        "provider": GcpProvider(project=PROJECT, region="us-central1"),
        "pubsub_topics": [PubSubTopic(project=PROJECT, name="jobs")],
    }
    values.update(overrides)
    return GcpStack(**values)  # type: ignore[arg-type]


def _main(stack: GcpStack) -> str:
    return GcpRenderer(".tofu").render_text(stack)["main.tf"]


# ── ref ───────────────────────────────────────────────────────────────
def test_ref_wraps_an_expression_verbatim() -> None:
    expression = ref("  google_pubsub_topic.topic_jobs.id  ")

    assert expression.text == "google_pubsub_topic.topic_jobs.id"


@pytest.mark.parametrize("value", ["", "   "])
def test_ref_rejects_empty_expressions(value: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ref(value)


# ── rendering ─────────────────────────────────────────────────────────
def test_outputs_render_after_resources() -> None:
    stack = _stack(
        outputs=[
            Output("topic", ref("google_pubsub_topic.topic_jobs.id")),
            Output("project", PROJECT, description="Default project"),
        ]
    )

    text = _main(stack)

    assert 'output "topic"' in text
    assert "value = google_pubsub_topic.topic_jobs.id" in text
    assert 'output "project"' in text
    assert 'description = "Default project"' in text
    assert text.index('output "topic"') > text.index('resource "google_pubsub_topic"')
    assert text.index('output "project"') > text.index('output "topic"')


def test_outputs_render_deterministically() -> None:
    stack = _stack(
        outputs=[
            Output("a", ref("google_pubsub_topic.topic_jobs.id")),
            Output("b", ref("google_pubsub_topic.topic_jobs.name")),
        ]
    )

    first = _main(stack)
    restacked = _stack(
        outputs=[
            Output("a", ref("google_pubsub_topic.topic_jobs.id")),
            Output("b", ref("google_pubsub_topic.topic_jobs.name")),
        ]
    )

    assert first == _main(restacked)


def test_sensitive_output_renders_flag() -> None:
    text = _main(_stack(outputs=[Output("token", "secret", sensitive=True)]))

    assert 'output "token"' in text
    assert "sensitive = true" in text


def test_plain_output_is_not_marked_sensitive() -> None:
    text = _main(_stack(outputs=[Output("count", 3)]))

    assert "value = 3" in text
    assert "sensitive" not in text


def test_stack_without_outputs_renders_no_output_blocks() -> None:
    text = _main(_stack())

    assert "output " not in text
    assert 'resource "google_pubsub_topic"' in text


def test_outputs_only_stack_renders_without_resources() -> None:
    renderer = GcpRenderer(".tofu")
    stack = GcpStack(
        provider=GcpProvider(project=PROJECT),
        outputs=[Output("project", PROJECT)],
    )

    text = renderer.render_text(stack)["main.tf"]

    assert 'output "project"' in text
    assert "No resources declared" not in text


# ── validation ────────────────────────────────────────────────────────
def test_duplicate_output_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate output names: bucket"):
        _stack(
            outputs=[
                Output("bucket", "a"),
                Output("bucket", "b"),
            ]
        )


@pytest.mark.parametrize("name", ["2fast", "with space", "with.dot", ""])
def test_output_name_must_be_an_identifier(name: str) -> None:
    with pytest.raises(ValidationError, match="not an HCL identifier"):
        Output(name, "value")


def test_output_description_must_be_single_line() -> None:
    with pytest.raises(ValidationError, match="single line"):
        Output("topic", "value", description="two\nlines")


def test_outputs_are_available_on_every_stack() -> None:
    stack = BaseStack(outputs=[Output("topic", "value")])

    assert stack.outputs[0].name == "topic"
