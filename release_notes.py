#!/usr/bin/env python3
"""The text of a release: what changed in it, then how to install it.

    python release_notes.py v0.1.4 > notes.md

What changed comes first because the kit's UPDATE panel shows the top of this
text under WHAT CHANGED (`updater.whats_new` cuts it at the line below), and
because someone who already has the kit opens the release page for that. How
to install is `INSTALL.md`, whole: it is the first thing someone who does not
have the kit needs, on the page the download is on.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# What follows this line in a release's text is not about what changed.
DIVIDER = "<!-- how to install -->"


def changes(tag, text=None):
    """The lines under `## <tag>` in CHANGES.md ("" if it has none)."""
    text = (HERE / "CHANGES.md").read_text(encoding="utf-8") if text is None else text
    wanted = "v" + tag.lstrip("vV")
    found = re.search(rf"^## {re.escape(wanted)}[ \t]*\n(.*?)(?=^## |\Z)", text,
                      re.MULTILINE | re.DOTALL)
    return found.group(1).strip() if found else ""


def notes(tag):
    new = changes(tag)
    install = (HERE / "INSTALL.md").read_text(encoding="utf-8").strip()
    head = f"## What is new in {'v' + tag.lstrip('vV')}\n\n{new}\n\n" if new else ""
    return f"{head}{DIVIDER}\n\n{install}\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.write(notes(sys.argv[1]))
