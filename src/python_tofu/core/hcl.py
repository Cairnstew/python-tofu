"""A tiny, dependency-free HCL writer.

The models in :mod:`python_tofu.models` describe infrastructure as data. This
module turns that data into the small subset of HCL that OpenTofu needs:
attributes, nested blocks and literal expressions.

Keeping the writer in-tree (rather than pulling in a full HCL library) makes the
output deterministic and easy to unit-test. Only constructs we actually emit are
supported; anything else raises :class:`HclError` instead of silently producing
invalid Terraform.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable


class HclError(ValueError):
    """Raised when a value cannot be represented as HCL."""


@dataclass(frozen=True)
class Raw:
    """A verbatim HCL expression, e.g. ``google_storage_bucket.foo.name``."""

    text: str


def ref(expression: str) -> Raw:
    """Wrap a bare HCL expression, e.g. ``ref("google_storage_bucket.b.name")``.

    This is the public entry point to :class:`Raw`: it renders the expression
    verbatim instead of quoting it like a string literal. Use it for outputs,
    cross-resource references and anything else a model cannot type.
    """

    text = expression.strip()
    if not text:
        raise ValueError("ref() requires a non-empty HCL expression")
    return Raw(text)


@dataclass(frozen=True)
class Attr:
    """A ``name = value`` attribute."""

    name: str
    value: Any


@dataclass(frozen=True)
class Block:
    """A ``kind "label" { ... }`` block."""

    kind: str
    labels: tuple[str, ...] = ()
    body: tuple["Attr | Block", ...] = ()


def attr(name: str, value: Any) -> Attr | None:
    """Build an :class:`Attr`, returning ``None`` for :data:`None` values.

    Skipping ``None`` lets callers list optional attributes without branching.
    """

    if value is None:
        return None
    return Attr(name, value)


def block(kind: str, *labels: str, body: Iterable["Attr | Block | None"] = ()) -> Block:
    """Build a :class:`Block`, dropping ``None`` body items."""

    return Block(kind, tuple(labels), tuple(item for item in body if item is not None))


def body(*items: "Attr | Block | None") -> tuple["Attr | Block", ...]:
    """Collect body items and drop the ``None`` entries produced by :func:`attr`."""

    return tuple(item for item in items if item is not None)


def render_value(value: Any) -> str:
    """Render a Python value as an HCL literal."""

    if isinstance(value, Raw):
        return value.text
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # JSON string escaping is a superset of HCL's quoted-string escaping.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(render_value(item) for item in value) + "]"
    if isinstance(value, (set, frozenset)):
        # Sets are unordered; sorting keeps generated files stable.
        return "[" + ", ".join(render_value(item) for item in sorted(value, key=str)) + "]"
    if isinstance(value, dict):
        parts = [
            f"{json.dumps(str(key), ensure_ascii=False)} = {render_value(item)}"
            for key, item in value.items()
            if item is not None
        ]
        if not parts:
            return "{}"
        return "{ " + ", ".join(parts) + " }"
    raise HclError(f"cannot render {type(value).__name__!r} as HCL: {value!r}")


def _render_block(block: Block, indent: int) -> str:
    pad = "  " * indent
    header = " ".join([block.kind, *(json.dumps(label) for label in block.labels)])
    if not block.body:
        return f"{pad}{header} {{}}"

    lines = [f"{pad}{header} {{"]
    attribute_width = max(
        (len(item.name) for item in block.body if isinstance(item, Attr)),
        default=0,
    )
    for item in block.body:
        if isinstance(item, Block):
            lines.append(_render_block(item, indent + 1))
        else:
            name = item.name.ljust(attribute_width)
            lines.append(f"{pad}  {name} = {render_value(item.value)}")
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def render(*blocks: Block) -> str:
    """Render top-level blocks with blank lines between them, plus a final newline."""

    return "\n\n".join(_render_block(item, 0) for item in blocks) + "\n"
