r"""Where the kit finds its own parts and keeps the artist's files.

The kit is installed into ONE folder the artist chose, and everything of
theirs is in it:

    C:\Program Files\PixelPomoDevKit\   (Mac: /Applications/PixelPomoDevKit/)
        PixelPomoDevKit.exe               (Mac: PixelPomoDevKit.app)
        devkit-install.json               "this folder is an install"
        Files\                            everything the artist added
            library\  trash\  state.json  devkit.log  updates\

An update replaces the program and nothing else: `Files` is never written by
an installer or an updater, only by the kit itself.

| | the artist's files |
|---|---|
| installed | `<the install folder>/Files/` |
| from source | `DevKit/_data/` |
| `DEVKIT_DATA` set | that folder, wherever the program is (no install asked) |

The window's own cache (the web view's profile) is not the artist's and is not
kept there: it goes in the per-user folder the system has for such things.
"""
import os
import subprocess
import sys
from pathlib import Path

DATA_ENV = "DEVKIT_DATA"
NAME = "PixelPomoDevKit"
MARKER = "devkit-install.json"
FILES = "Files"


def frozen():
    return getattr(sys, "frozen", False)


def source_root():
    """The DevKit folder, when running from source."""
    return Path(__file__).resolve().parent.parent


def bundle_dir():
    """Where PyInstaller unpacked what the build put inside the program."""
    return Path(getattr(sys, "_MEIPASS", source_root()))


def program_path():
    """The program as the artist sees it: the .exe, or on a Mac the .app."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
    return exe


def program_dir():
    """The folder the program sits in (from source: the DevKit folder)."""
    return program_path().parent if frozen() else source_root()


def installed():
    """Is the running program the installed copy?"""
    return frozen() and (program_dir() / MARKER).is_file()


def per_user_dir():
    """The system's per-user folder for this program: the window's cache and
    the note of where the kit was installed. Never the artist's files."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / NAME


def data_dir():
    override = os.environ.get(DATA_ENV)
    if override:
        return Path(override)
    if not frozen():
        return source_root() / "_data"
    return program_dir() / FILES


def profile_dir():
    """Where the window keeps its cache."""
    if os.environ.get(DATA_ENV) or not frozen():
        return data_dir() / "window"
    return per_user_dir() / "window"


def legacy_data_dirs():
    """Where v0.1.0 kept the artist's files. (It was never built for a Mac.)"""
    if frozen() and sys.platform.startswith("win"):
        return [per_user_dir()]
    return []


def web_dir():
    """The built page: inside the program when frozen, the Flutter build
    folder when running from source."""
    if frozen():
        return bundle_dir() / "web"
    return source_root() / "app" / "build" / "web"


def asset(name):
    """One of the kit's own pictures (icon.ico, icon.png), or None."""
    for folder in (bundle_dir(), source_root() / "assets"):
        if (folder / name).is_file():
            return folder / name
    return None


def tools_dir():
    """The game's converters. Read live from the game when running from
    source — DevKit and App are siblings, as ArtKit and App are — and from the
    copy the build bundled when frozen. `PIXEL_POMO_TOOLS` wins over both."""
    override = os.environ.get("PIXEL_POMO_TOOLS")
    if override:
        return Path(override)
    if frozen():
        return bundle_dir()
    return source_root().parent / "App" / "flutter" / "tools"


def clean_environment(environ=None):
    """The environment minus PyInstaller's bootloader variables, so a kit
    started from a frozen kit unpacks itself instead of reusing (and
    outliving) this one's temp folder. The Art Kit's lesson (#v2.7.0)."""
    environ = os.environ if environ is None else environ
    return {k: v for k, v in environ.items()
            if not (k.startswith("_MEIPASS") or k.startswith("_PYI_"))}


def open_in_file_manager(folder):
    """Show `folder` to the artist — Explorer, Finder, or xdg-open."""
    folder = str(folder)
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)  # noqa: S606 - a folder, not a command
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return True
    except OSError:
        return False
