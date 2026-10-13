#!/usr/bin/env python3
"""Bring a fresh checkout of the game up to what this kit is built against.

    python game_ahead.py [path to the game repo]      (default: ../App)

The kit compiles against the game's own engine, and now and then it needs
something the game has not published yet - at v0.1.1: a mesh's `turn`, the
ids of what an artist added, the daisy's two models and the chamomile.
`game-ahead.patch` is exactly that difference, for the three folders the kit
reads (`flutter/lib`, `flutter/assets`, `flutter/tools`), so that a release of
the kit does not have to wait for, or force, a release of the game.

Only CI runs this: on the machine the kit is developed on, the game beside it
already has these changes in its working tree.

Three outcomes, and only the last is a failure:
- the patch applies: it is applied;
- the game already has every change in it: nothing to do - the patch has
  served its purpose and can be deleted;
- neither: the game moved under the patch. Make it again (README, Building).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "game-ahead.patch"


def git(game, *args):
    return subprocess.run(["git", "-C", str(game), "apply", *args, str(PATCH)],
                          capture_output=True, text=True)


def main(argv):
    game = Path(argv[0]).resolve() if argv else HERE.parent / "App"
    if not PATCH.is_file() or not PATCH.stat().st_size:
        print("no game-ahead.patch: the kit builds against the game as published")
        return 0
    if not (game / "flutter" / "lib").is_dir():
        print(f"the game is not at {game}", file=sys.stderr)
        return 1
    if git(game, "--check").returncode == 0:
        done = git(game)
        if done.returncode != 0:
            print(done.stderr, file=sys.stderr)
            return 1
        print(f"applied {PATCH.name} to {game}")
        return 0
    if git(game, "--reverse", "--check").returncode == 0:
        print(f"the game already has everything in {PATCH.name}")
        return 0
    print(f"{PATCH.name} no longer fits the game at {game}:", file=sys.stderr)
    print(git(game, "--check").stderr, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
