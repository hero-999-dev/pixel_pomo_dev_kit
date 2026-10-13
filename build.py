#!/usr/bin/env python3
"""Build the Dev Kit. One recipe for this machine and for CI.

    python build.py            the page, then the program (dist/PixelPomoDevKit)
    python build.py --page     the page only - enough for `python -m dev_kit`
    python build.py --program  the program only, around the page as last built

On this machine (not in CI) the build ends by making `dist` an install, so the
program there opens the kit instead of its setup - see `install_in_place`.

Three steps, in the only order they work:

1. `sync_assets.py` copies the game's art into the Flutter project.
2. `flutter build web` compiles the page against the game's engine.
3. PyInstaller freezes the launcher with that page and the game's voxel
   converter inside it.

Flutter is taken from the FLUTTER environment variable, else from PATH.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE / "app"

FLUTTER_BUILD = [
    "build", "web", "--release",
    # CanvasKit from the build itself, not from a CDN: the kit has to open on
    # a machine with no connection.
    "--no-web-resources-cdn",
    # No service worker. It would cache the page in the window's profile, and
    # the next version of the kit would open as the previous one. (Flutter
    # calls the flag deprecated because the service worker itself is on its
    # way out; when the flag goes, so does the reason for it.)
    "--pwa-strategy=none",
    # the four voxel test models are in the kit's catalogue (see sync_assets)
    "--dart-define=TEST_MESHES=true",
]


def flutter():
    named = os.environ.get("FLUTTER")
    if named:
        return named
    found = shutil.which("flutter")
    if not found:
        sys.exit("Flutter was not found. Put it on PATH or set FLUTTER to flutter(.bat).")
    return found


def run(command, cwd):
    print("\n== " + " ".join(str(c) for c in command), flush=True)
    done = subprocess.run([str(c) for c in command], cwd=str(cwd))
    if done.returncode != 0:
        sys.exit(f"failed ({done.returncode}): {command[0]}")


def build_page():
    run([sys.executable, HERE / "sync_assets.py"], HERE)
    run([flutter(), "pub", "get"], APP)
    run([flutter(), *FLUTTER_BUILD], APP)
    if not (APP / "build" / "web" / "main.dart.js").is_file():
        sys.exit("flutter reported success but there is no main.dart.js")


def build_program():
    name = "PixelPomoDevKit"
    target = HERE / "dist" / (f"{name}.app" if sys.platform == "darwin"
                              else f"{name}.exe" if os.name == "nt" else name)
    # A running copy holds the file open; PyInstaller then fails deep in its
    # output, or worse, leaves the old file and the build looks like it worked.
    try:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    except OSError:
        sys.exit(f"{target} is in use - close the Dev Kit first.")
    run([sys.executable, "-m", "PyInstaller", "PixelPomoDevKit.spec",
         "--noconfirm", "--clean"], HERE)
    if not target.exists():
        sys.exit(f"PyInstaller reported success but {target} is not there")
    size = (sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            if target.is_dir() else target.stat().st_size)
    print(f"\n-> {target}  ({size / 1e6:.1f} MB)")
    if not os.environ.get("CI"):
        install_in_place(target)


def install_in_place(program):
    """Make `dist` an install of what was just built. It is where the kit is
    tried on this machine: the program there opens the kit, with its files in
    `dist/Files`, instead of asking where to be installed. (To see the setup,
    start a copy of the program from any other folder.) A rebuild replaces
    the program and leaves `dist/Files` alone, as an update does."""
    sys.path.insert(0, str(HERE))
    from dev_kit import installer, paths
    (program.parent / paths.FILES).mkdir(exist_ok=True)
    installer.write_marker(program.parent, program)
    print(f"   installed in place: files in {program.parent / paths.FILES}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--page", action="store_true", help="build the page only")
    ap.add_argument("--program", action="store_true",
                    help="the program only, around the page as last built")
    args = ap.parse_args()
    if not args.program:
        build_page()
    elif not (APP / "build" / "web" / "main.dart.js").is_file():
        sys.exit("there is no built page yet - run without --program first")
    if not args.page:
        build_program()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
