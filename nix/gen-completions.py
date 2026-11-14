"""Generate shell completions from Typer's own templates.

Typer's ``--show-completion`` flag detects the *current* shell, so a Nix build
cannot ask for bash, zsh and fish in one pass. This calls the same helper the
CLI calls, with the vendored Typer version pinned by ``uv.lock``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from typer._completion_shared import get_completion_script

PROG = "python-tofu"
COMPLETE_VAR = "_PYTHON_TOFU_COMPLETE"

TARGETS = {
    "bash": "share/bash-completion/completions/python-tofu",
    "zsh": "share/zsh/site-functions/_python-tofu",
    "fish": "share/fish/vendor_completions.d/python-tofu.fish",
}


def main(out_dir: str) -> None:
    root = Path(out_dir)
    for shell, relative in TARGETS.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        script = get_completion_script(prog_name=PROG, complete_var=COMPLETE_VAR, shell=shell)
        target.write_text(script + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
