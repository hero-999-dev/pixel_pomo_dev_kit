#!/usr/bin/env python3
"""Copy the game's art into the kit's Flutter project, ready to build.

    python sync_assets.py

The kit draws with the game's own engine, and that engine loads its sprites
and meshes from the asset bundle by fixed keys (`assets/objects/grass.png`...).
So the kit's build has to carry the same files under the same names. They are
not kept here — `app/assets/` is rewritten from the game by this script before
every build, which is what stops the kit ever showing a sprite the game no
longer ships.

Also copied: `App/flutter/test_assets/`, the four voxel test models. The game
keeps them out of its real builds; the kit carries them as its worked examples
of a .vox that came in well, and is built with TEST_MESHES so they are in its
catalogue.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GAME = HERE.parent / "App" / "flutter"
DEST = HERE / "app" / "assets"

# (folder in the game, folder in the kit, pattern)
COPIES = [
    ("assets/objects", "objects", "*.png"),
    ("assets/meshes", "meshes", "*.json"),
    ("test_assets/objects", "objects", "*.png"),
    ("test_assets/meshes", "meshes", "*.json"),
    ("assets/fonts", "fonts", "PressStart2P-Regular.ttf"),
    ("assets/icon", "icon", "app_icon.png"),
]


def main():
    if not (GAME / "assets" / "objects").is_dir():
        print(f"the game is not at {GAME} - DevKit and App have to be siblings",
              file=sys.stderr)
        return 1
    # from scratch every time, so a file the game dropped does not linger here
    shutil.rmtree(DEST, ignore_errors=True)
    copied = 0
    for src, dst, pattern in COPIES:
        target = DEST / dst
        target.mkdir(parents=True, exist_ok=True)
        files = sorted((GAME / src).glob(pattern))
        if not files:
            print(f"nothing matches {src}/{pattern} in the game", file=sys.stderr)
            return 1
        for path in files:
            if (target / path.name).exists():
                print(f"{path.name} is in the game twice ({src})", file=sys.stderr)
                return 1
            shutil.copy2(path, target / path.name)
            copied += 1
    print(f"copied {copied} files from the game into {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
