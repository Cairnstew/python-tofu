from __future__ import annotations

import pytest

from python_tofu.hcl import Attr, Block, HclError, Raw, attr, body, render, render_value


def test_strings_are_quoted_and_escaped() -> None:
    assert render_value('a"b') == '"a\\"b"'
    assert render_value("line\nbreak") == '"line\\nbreak"'


def test_scalars() -> None:
    assert render_value(True) == "true"
    assert render_value(False) == "false"
    assert render_value(3) == "3"
    assert render_value(1.5) == "1.5"


def test_collections() -> None:
    assert render_value(["a", "b"]) == '["a", "b"]'
    assert render_value({"source": "hashicorp/google"}) == '{ "source" = "hashicorp/google" }'
    assert render_value({"skip": None, "keep": 1}) == '{ "keep" = 1 }'


def test_sets_render_in_sorted_order() -> None:
    assert render_value({"b", "a"}) == '["a", "b"]'


def test_raw_expression_is_verbatim() -> None:
    assert render_value(Raw("google_storage_bucket.main.name")) == (
        "google_storage_bucket.main.name"
    )


def test_unsupported_type_raises() -> None:
    with pytest.raises(HclError):
        render_value(object())


def test_attr_skips_none() -> None:
    assert attr("optional", None) is None
    assert attr("present", "x") == Attr("present", "x")


def test_body_and_block_drop_none() -> None:
    rendered = render(
        Block(
            "provider",
            ("google",),
            body(
                attr("project", "demo-project"),
                attr("region", None),
            ),
        )
    )
    assert rendered == 'provider "google" {\n  project = "demo-project"\n}\n'


def test_attributes_are_aligned() -> None:
    rendered = render(
        Block(
            "provider",
            ("google",),
            body=(Attr("project", "p"), Attr("default_labels", {})),
        )
    )
    assert '  project        = "p"\n' in rendered
    assert "  default_labels = {}" in rendered


def test_empty_block_renders_inline() -> None:
    assert render(Block("terraform")) == "terraform {}\n"


def test_nested_block_ends_the_alignment_run() -> None:
    """`tofu fmt` aligns only consecutive attributes, so a block resets the run.

    Regression: one width for the whole body over-padded the attributes after a
    nested block, and `tofu fmt -check` rejected the rendered file.
    """

    rendered = render(
        Block(
            "resource",
            ("google_storage_bucket", "artifacts"),
            body=(
                Attr("name", "b"),
                Attr("location", "US"),
                Block("versioning", body=(Attr("enabled", True),)),
                Attr("depends_on", Raw("[google_project_service.api]")),
            ),
        )
    )

    assert '  name     = "b"\n  location = "US"\n' in rendered
    assert "\n  depends_on = [google_project_service.api]\n" in rendered


def test_nested_blocks_and_multiple_top_levels() -> None:
    rendered = render(
        Block(
            "terraform",
            body=(
                Attr("required_version", ">= 1.6.0"),
                Block(
                    "required_providers",
                    body=(
                        Attr(
                            "google",
                            {"source": "hashicorp/google", "version": "~> 6.0"},
                        ),
                    ),
                ),
            ),
        ),
        Block("provider", ("google",), body=(Attr("project", "demo-project"),)),
    )
    assert 'required_version = ">= 1.6.0"' in rendered
    assert 'google = { "source" = "hashicorp/google", "version" = "~> 6.0" }' in rendered
    assert rendered.count("\n\n") == 1
