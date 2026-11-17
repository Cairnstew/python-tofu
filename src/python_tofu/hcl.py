"""Backwards-compatible re-export of :mod:`python_tofu.core.hcl`."""

from python_tofu.core.hcl import (
    Attr,
    Block,
    HclError,
    Raw,
    attr,
    block,
    body,
    is_reference_template,
    ref,
    render,
    render_value,
)

__all__ = [
    "Attr",
    "Block",
    "HclError",
    "Raw",
    "attr",
    "block",
    "body",
    "is_reference_template",
    "ref",
    "render",
    "render_value",
]
