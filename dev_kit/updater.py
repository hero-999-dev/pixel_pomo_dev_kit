"""Updates from the kit's releases, the Art Kit's way.

* `check()` asks GitHub for the latest release of the kit's repository —
  public, so no token — and says whether it is newer than the running one.
* `download()` fetches this machine's zip, `stage()` unpacks the new program
  and writes a small script that waits for the kit to close, swaps the two
  and starts the new one. A running program cannot overwrite itself, hence
  the hand-off.

**Nothing here touches the artist's files.** They are in `Files`, beside the
program, and the swap moves the program and nothing else.

Two things the Art Kit's artists asked for after living with its updater, and
which this one starts with:

* after an update there is ONE program in the folder, the new one. The old one
  is kept for a way back, but out of sight, in `Files/updates/` — not as a
  second program beside the first (Art Kit v3.0 draft, item 1);
* a Mac updates itself too. The kit downloads the zip itself, so macOS does
  not quarantine it, and the new .app opens without Gatekeeper asking again.
  (Written from Apple's documented behaviour; not yet run on a Mac.)
"""
import json
import logging
import os
import platform
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from dev_kit import paths
from dev_kit.version import REPO, VERSION, parse

log = logging.getLogger("dev_kit")

API_ENV = "DEVKIT_UPDATE_API"   # a test points this at a server of its own
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
USER_AGENT = f"PixelPomoDevKit/{VERSION}"
EXE_NAME = "PixelPomoDevKit.exe"
APP_NAME = "PixelPomoDevKit.app"


def asset_name():
    """This machine's download, by the name the release workflow gives it."""
    if sys.platform.startswith("win"):
        return "PixelPomoDevKit-windows.zip"
    if sys.platform == "darwin":
        chip = "apple-silicon" if platform.machine() == "arm64" else "intel"
        return f"PixelPomoDevKit-macos-{chip}.zip"
    return None


# A release's text is what changed in it and then how to install it
# (release_notes.py). The UPDATE panel is for someone who has the kit: it shows
# what comes before this line, or before the install guide's first heading in
# a release written before the line was.
_NOT_NEWS = ("<!-- how to install -->", "## Install on ")


def whats_new(body):
    """The part of a release's text that says what changed."""
    text = body or ""
    for mark in _NOT_NEWS:
        at = text.find(mark)
        if at >= 0:
            text = text[:at]
    lines = [line for line in text.strip().splitlines()
             if not line.startswith("## What is new in ")]
    # the panel draws plain text: a mark for bold would show as two stars
    return "\n".join(lines).strip().replace("**", "")


class Release:
    def __init__(self, data):
        self.tag = str(data.get("tag_name", ""))
        self.version = parse(self.tag)
        self.url = data.get("html_url", RELEASES_PAGE)
        self.notes = whats_new(data.get("body"))
        self.assets = {a.get("name"): a.get("browser_download_url")
                       for a in data.get("assets", []) if a.get("name")}

    @property
    def is_newer(self):
        return self.version > parse(VERSION)


def _open(req, timeout):
    """`urlopen` with a certificate store that is always there: a frozen Mac
    build has none of its own, and every HTTPS request failed until certifi
    shipped inside the Art Kit (#v2.9.0)."""
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        context = None
    return urllib.request.urlopen(req, timeout=timeout, context=context)


def check(timeout=8, opener=None):
    """The latest release, or raises (URLError, ValueError, OSError)."""
    req = urllib.request.Request(
        os.environ.get(API_ENV) or API,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with (opener or _open)(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the release list was not what was expected")
    return Release(data)


def download(url, dest, progress=None, opener=None, timeout=30):
    """Fetch `url` to `dest`, calling `progress(done, total)` as it goes.
    Written beside itself first, so an interrupted download never leaves a
    half zip under the real name."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_name(dest.name + ".part")
    with (opener or _open)(req, timeout=timeout) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    os.replace(tmp, dest)
    return dest


def can_self_update():
    """Only the installed program can swap itself."""
    return paths.installed() and asset_name() is not None


def stage(zip_path, program, keep_dir, pid=None, old_version=VERSION):
    """Unpack the new program beside the running one and write the hand-off
    script. Returns the script. Raises ValueError if the zip has no program
    in it."""
    program, keep_dir = Path(program), Path(keep_dir)
    keep_dir.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    if program.suffix == ".app":
        return _stage_mac(zip_path, program, keep_dir, pid, old_version)
    new = program.with_name(program.stem + ".new" + program.suffix)
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(EXE_NAME.lower())]
        if not names:
            raise ValueError(f"{Path(zip_path).name} has no {EXE_NAME} in it")
        with zf.open(names[0]) as src, open(new, "wb") as dst:
            shutil.copyfileobj(src, dst)
    script = keep_dir / "update.cmd"
    kept = keep_dir / f"{program.stem}-{old_version}{program.suffix}"
    script.write_text(_windows_handoff(program, new, kept, pid), encoding="ascii")
    return script


def _windows_handoff(program, new, kept, pid):
    """Wait for `pid` to exit, put the old program away in `kept`, move the
    new one into its place, start it, and remove this script. Plain cmd, so
    it runs on any Windows with nothing installed."""
    return "\r\n".join([
        "@echo off",
        # No setlocal: the wipes below have to reach `start`. The PyInstaller
        # bootloader tells its child where it unpacked itself through
        # _MEIPASS* / _PYI_*; this script inherits them from the OLD kit, and
        # the NEW kit would trust them and look for its files in a temp
        # folder the old one deleted on exit (Art Kit #v2.7.0).
        "for /f \"tokens=1 delims==\" %%V in ('set _MEI 2^>NUL') do set \"%%V=\"",
        "for /f \"tokens=1 delims==\" %%V in ('set _PYI 2^>NUL') do set \"%%V=\"",
        f"set PID={pid}",
        ":wait",
        'tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >NUL",
        "  goto wait",
        ")",
        # the old kit deletes its temp folder on the way out; let it finish
        "timeout /t 2 /nobreak >NUL",
        # one way back is kept, and only one
        f'del /f /q "{kept.parent}\\{program.stem}-*{program.suffix}" >NUL 2>NUL',
        f'move /y "{program}" "{kept}" >NUL',
        f'move /y "{new}" "{program}" >NUL',
        # if the move failed the old program is still in `kept`: put it back
        f'if not exist "{program}" move /y "{kept}" "{program}" >NUL',
        "timeout /t 1 /nobreak >NUL",
        f'start "" /D "{program.parent}" "{program}"',
        '(goto) 2>nul & del "%~f0"',
        "",
    ])


def _stage_mac(zip_path, app, keep_dir, pid, old_version):
    fresh = keep_dir / "new"
    shutil.rmtree(fresh, ignore_errors=True)
    # ditto, not zipfile: it keeps the bundle's symlinks and executable bits
    subprocess.run(["ditto", "-x", "-k", str(zip_path), str(fresh)], check=True)
    found = sorted(fresh.rglob(APP_NAME))
    if not found:
        raise ValueError(f"{Path(zip_path).name} has no {APP_NAME} in it")
    script = keep_dir / "update.sh"
    kept = keep_dir / f"{app.stem}-{old_version}.app"
    script.write_text(_mac_handoff(app, found[0], kept, fresh, pid), encoding="utf-8")
    script.chmod(0o755)
    return script


def _mac_handoff(app, new, kept, fresh, pid):
    def q(path):
        return "'" + str(path).replace("'", "'\\''") + "'"
    return "\n".join([
        "#!/bin/sh",
        f"while kill -0 {pid} 2>/dev/null; do sleep 1; done",
        "sleep 1",
        f"rm -rf {q(kept.parent)}/{app.stem}-*.app",
        f"mv {q(app)} {q(kept)}",
        f"mv {q(new)} {q(app)} || mv {q(kept)} {q(app)}",
        # the kit fetched the zip itself, so nothing should be quarantined;
        # this is for the Mac that marked it anyway
        f"xattr -dr com.apple.quarantine {q(app)} 2>/dev/null",
        f"rm -rf {q(fresh)}",
        f"open {q(app)}",
        'rm -f "$0"',
        "",
    ])


def launch_handoff(script):
    """Start the hand-off script so that it outlives this process.

    Windows: CREATE_NO_WINDOW, not DETACHED_PROCESS — a detached cmd has no
    console at all and `tasklist | find` then blocks for ever on the pipe
    (the Art Kit's first dry run). A hidden console shows the artist nothing
    and gives the tools what they need."""
    script = Path(script)
    env = paths.clean_environment()
    if script.suffix == ".cmd":
        flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=flags,
                         close_fds=True, cwd=str(script.parent), env=env)
    else:
        subprocess.Popen(["/bin/sh", str(script)], close_fds=True, env=env,
                         cwd=str(script.parent), start_new_session=True)


def _why(exc):
    """A failed check, in words meant for the artist."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "No version of the Dev Kit has been published yet."
        return f"The release page answered {exc.code}."
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "The release page could not be reached. Is this machine online?"
    return f"The release page sent something unexpected ({exc})."


class Updates:
    """What the page's UPDATE button talks to. One check or one update at a
    time; `status()` is what the page shows."""

    def __init__(self, data_dir, on_ready=None, check=check, download=download):
        self.keep_dir = Path(data_dir) / "updates"
        self.on_ready = on_ready      # called with the hand-off script
        self._check, self._download = check, download
        self._lock = threading.Lock()
        self._release = None
        self._state = {"state": "idle", "version": VERSION, "latest": "",
                       "notes": "", "progress": 0.0, "message": "",
                       "canUpdate": can_self_update(), "page": RELEASES_PAGE}

    def status(self):
        with self._lock:
            return dict(self._state)

    def _set(self, **changes):
        with self._lock:
            self._state.update(changes)

    def check(self):
        """Ask for the latest release. Blocks; the page waits for the answer."""
        with self._lock:
            if self._state["state"] in ("downloading", "ready"):
                return dict(self._state)   # an update is already on its way
        self._set(state="checking", message="")
        try:
            release = self._check()
        except Exception as exc:  # noqa: BLE001 - every failure is an answer
            log.info("update check failed: %r", exc)
            self._set(state="failed", message=_why(exc))
            return self.status()
        self._release = release
        self._set(state="available" if release.is_newer else "none",
                  latest=release.tag.lstrip("vV"), notes=release.notes[:4000],
                  page=release.url)
        return self.status()

    def apply(self):
        """Download and stage the update in the background."""
        release = self._release
        if release is None or not release.is_newer:
            raise ValueError("There is no newer version to install.")
        if not can_self_update():
            raise ValueError("Only the installed Dev Kit can update itself. "
                             f"The new version is at {release.url}")
        url = release.assets.get(asset_name())
        if not url:
            raise ValueError(f"{release.tag} has no download for this machine "
                             f"({asset_name()}). It is at {release.url}")
        with self._lock:
            if self._state["state"] in ("downloading", "ready"):
                return dict(self._state)
            self._state.update(state="downloading", progress=0.0, message="")
        threading.Thread(target=self._run, args=(release, url), daemon=True).start()
        return self.status()

    def _run(self, release, url):
        try:
            zip_path = self._download(
                url, self.keep_dir / asset_name(),
                progress=lambda done, total: self._set(
                    progress=done / total if total else 0.0))
            script = stage(zip_path, paths.program_path(), self.keep_dir)
            Path(zip_path).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            log.exception("the update failed")
            self._set(state="failed", message=f"The update did not install: {exc}")
            return
        log.info("update to %s staged: %s", release.tag, script)
        self._set(state="ready", progress=1.0)
        if self.on_ready:
            self.on_ready(script)
