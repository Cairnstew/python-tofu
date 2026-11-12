"""Provider-agnostic pruning of undeclared live resources.

A provider discovers resources that exist in the cloud but are not declared by
the stack (``PrunePlan``). This module turns that plan into a **scratch
OpenTofu root module**: each discovered resource is written as a ``resource``
block plus an ``import`` block, adopted into a throw-away local state, and then
destroyed by ``tofu destroy``. Deletion therefore runs through the provider's
own delete implementation instead of reimplementing cloud APIs here.

The scratch module lives under ``<workdir>/.python-tofu-prune/`` and never
touches the real state backend, so a failed prune cannot corrupt the stack's
state.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from python_tofu.core.exceptions import PruneError
from python_tofu.core.hcl import Attr, Block, Raw, body, render
from python_tofu.core.models import BaseStack
from python_tofu.core.renderer import BaseRenderer
from python_tofu.core.runner import TofuRunner


@dataclass(frozen=True)
class PrunableResource:
    """One live resource that is absent from the stack.

    ``block`` renders the resource configuration for the scratch module and
    ``import_id`` is the provider's import identifier, so adopting and deleting
    it needs no provider-specific logic in core.
    """

    section: str
    address: str
    import_id: str
    block: Block
    description: str = ""


@dataclass(frozen=True)
class PrunePlan:
    """Resources to delete, plus non-fatal discovery notes."""

    resources: tuple[PrunableResource, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.resources

    def by_section(self, order: Iterable[str]) -> list[tuple[str, tuple[PrunableResource, ...]]]:
        """Group resources by section, following ``order``."""

        groups: dict[str, list[PrunableResource]] = {}
        for resource in self.resources:
            groups.setdefault(resource.section, []).append(resource)
        ordered = list(order)
        for section in groups:
            if section not in ordered:
                ordered.append(section)
        return [(section, tuple(groups[section])) for section in ordered if section in groups]


def _import_block(resource: PrunableResource) -> Block:
    return Block(
        "import",
        body=body(
            Attr("to", Raw(resource.address)),
            Attr("id", resource.import_id),
        ),
    )


class Reaper:
    """Delete a :class:`PrunePlan` through a scratch OpenTofu module."""

    DIRECTORY = ".python-tofu-prune"

    def __init__(
        self,
        workdir: str | Path,
        renderer: BaseRenderer[Any],
        stack: BaseStack,
        binary: str = "tofu",
        on_command: Callable[[Sequence[str]], None] | None = None,
    ) -> None:
        self.workdir = Path(workdir)
        self.renderer = renderer
        self.stack = stack
        self.binary = binary
        self.on_command = on_command

    @property
    def scratch(self) -> Path:
        return self.workdir / self.DIRECTORY

    def _terraform_block(self) -> Block:
        required = self.renderer.required_providers(self.stack)
        required_block = None
        if required:
            required_block = Block(
                "required_providers",
                body=tuple(Attr(name, spec) for name, spec in required.items()),
            )
        # Deliberately no backend block: the scratch state must stay local.
        return Block(
            "terraform",
            body=body(
                Attr("required_version", self.stack.required_version),
                required_block,
            ),
        )

    def config_text(self, resources: Sequence[PrunableResource]) -> dict[str, str]:
        """Return the scratch module's files without writing them."""

        return {
            "versions.tf": render(self._terraform_block()),
            "providers.tf": render(*self.renderer.provider_blocks(self.stack)),
            "main.tf": render(
                *(resource.block for resource in resources),
                *(_import_block(resource) for resource in resources),
            ),
        }

    def _write(self, resources: Sequence[PrunableResource]) -> None:
        if self.scratch.exists():
            shutil.rmtree(self.scratch)
        self.scratch.mkdir(parents=True)
        for name, text in self.config_text(resources).items():
            (self.scratch / name).write_text(text, encoding="utf-8")
        (self.scratch / ".gitignore").write_text(
            ".terraform/\n*.tfstate\n*.tfstate.*\n", encoding="utf-8"
        )

    def reap(self, resources: Sequence[PrunableResource]) -> None:
        """Import then destroy ``resources``; raises :class:`PruneError` on failure."""

        if not resources:
            return
        self._write(resources)
        runner = TofuRunner(self.scratch, binary=self.binary)
        for action in ("init", "adopt", "destroy"):
            if action == "init":
                result = runner.init()
            elif action == "adopt":
                result = runner.apply(auto_approve=True)
            else:
                result = runner.destroy(auto_approve=True)
            if self.on_command is not None:
                self.on_command(result.args)
            if not result.ok:
                detail = result.stderr.strip() or result.stdout.strip()
                raise PruneError(
                    f"prune {action} failed in {self.scratch}: {detail or 'no output'}"
                )

        # Success: leave no state behind. On failure the directory is kept so
        # the operator can inspect the import/destroy output.
        shutil.rmtree(self.scratch, ignore_errors=True)


__all__ = ["PrunableResource", "PrunePlan", "Reaper"]
