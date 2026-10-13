"""One version string for the launcher, the page it serves, and the build.

The release tag is `v` + this string; `updater.py` compares it with the latest
release of REPO.
"""
VERSION = "0.1.1"

# Where releases are published. Named after the Art Kit's
# (hero-999-dev/pixel_pomo_art_kit); the repository does not exist until the
# kit is pushed, and until then UPDATE says there is nothing to check.
REPO = "hero-999-dev/pixel_pomo_dev_kit"


def parse(text):
    """'v0.1.1' / '0.1.1' -> (0, 1, 1). Anything unparseable -> (0,)."""
    text = str(text).strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        digits = ""
        for ch in piece:
            if not ch.isdigit():
                break   # "0-rc1" -> 0: leading digits only
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)
