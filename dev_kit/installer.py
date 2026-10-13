"""Setting the kit up: one folder, chosen by the artist, with a suggestion.

The download is the program itself. Started from anywhere that is not an
install (Downloads, a zip, a USB stick), it does not open the kit — it asks
where the kit should live, copies itself there, makes a desktop shortcut on
Windows, and starts the installed copy. From then on the artist's files are in
`Files` inside that folder (see `paths.py`), and a newer download started the
same way offers to update the installed kit in place, files untouched.

| | suggested |
|---|---|
| Windows | `C:\\Program Files\\PixelPomoDevKit` |
| macOS | `/Applications/PixelPomoDevKit` (or `~/Applications/...` where that is not writable) |

Both are where programs go on that system. On Windows that folder belongs to
the system, so the kit's own folder in it takes the one permission question
every installer asks (`open_as_admin`): the program starts itself once more,
with that permission, to do two things and stop - make the folder, and give
the artist's account the right to write in it, because `Files` is in it and an
update replaces the program in it. The copying is then done by the setup
itself, as the artist, where its progress can be shown. A folder the account
can already write (`D:\\Tools`, the Desktop) is installed into with no question
at all.

The setup window never waits blind. Installing runs on a thread of its own and
the page asks `progress` how far it is: a bar, the step in words, and - while
Windows' question is unanswered - where to look for it. That question can open
BEHIND the window, as a shield flashing on the taskbar; v0.1.1 asked it for no
window in particular, showed three dots, and could only be ended from Task
Manager. It is now asked for the setup window, the page says what it is
waiting for, and closing the window ends the setup whatever it is waiting on.

On a Mac the folder is deliberately NOT Documents, Desktop or Downloads: those
three are the ones macOS asks permission for, and the Art Kit's artists met
that question on first save. A folder under Applications is never asked about.
"""
import argparse
import base64
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from dev_kit import paths
from dev_kit.version import VERSION, parse

log = logging.getLogger("dev_kit")

SHORTCUT_NAME = "Pixel Pomo Dev Kit"
SETUP_TITLE = "Pixel Pomo Dev Kit Setup"
# The program started with this as its first word is the half of an install
# that Windows gave permission to: it makes the kit's folder, opens it to the
# artist's account, and stops.
OPEN_FLAG = "--open-folder"
# ...and how many seconds that may take once permission is given. It is a
# second or two of work behind the program unpacking itself.
PERMITTED_LIMIT = 120
_CANCELLED = 1223   # ERROR_CANCELLED: the permission question was answered "no"


class Refused(Exception):
    """A folder the kit cannot be installed in, said for the artist."""


# ---- where --------------------------------------------------------------------

def default_dir():
    if sys.platform.startswith("win"):
        # ProgramW6432 is the real one even where a 32-bit process is shown
        # "Program Files (x86)" under the plain name
        programs = (os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles")
                    or (os.environ.get("SystemDrive") or "C:") + "\\Program Files")
        return Path(programs) / paths.NAME
    if sys.platform == "darwin":
        shared = Path("/Applications")
        base = shared if os.access(shared, os.W_OK) else Path.home() / "Applications"
        return base / paths.NAME
    return Path.home() / paths.NAME


def target_for(chosen):
    """The folder the kit goes in, for a folder the artist picked. The kit
    always gets a folder of its own, named after it: picking `D:\\Tools`
    installs into `D:\\Tools\\PixelPomoDevKit`, never loose among what is
    already in `D:\\Tools`."""
    text = str(chosen or "").strip().strip('"')
    if not text:
        raise Refused("Choose a folder for the Dev Kit.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise Refused(f"'{text}' is not a full path — it has to start at a drive "
                      f"or at the top folder.")
    return path if path.name.lower() == paths.NAME.lower() else path / paths.NAME


def record_path():
    return paths.per_user_dir() / "install.json"


def recorded():
    """The folder the kit was installed in on this account, if the program is
    still there."""
    try:
        folder = Path(json.loads(record_path().read_text(encoding="utf-8"))["dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return folder if (folder / paths.MARKER).is_file() else None


def marker_of(folder):
    try:
        marker = json.loads((Path(folder) / paths.MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return marker if isinstance(marker, dict) else {}


def program_in(folder, source=None):
    """The installed program's path in `folder`."""
    return Path(folder) / Path(source or paths.program_path()).name


def fingerprint(program):
    """Which build a program is: two builds of one version differ here."""
    program = Path(program)
    if program.suffix == ".app":
        inner = program / "Contents" / "MacOS" / program.stem
        program = inner if inner.is_file() else program
    try:
        digest = hashlib.sha1()
        with open(program, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return ""


def decide():
    """What a start should do: ("run", None) — open the kit; ("open", program)
    — this is a download and the same kit is already installed, open that;
    ("setup", folder or None) — ask where to install, `folder` being an
    older install to update."""
    if not paths.frozen() or os.environ.get(paths.DATA_ENV) or paths.installed():
        return "run", None
    existing = recorded()
    if existing is None:
        return "setup", None
    marker = marker_of(existing)
    theirs, ours = parse(marker.get("version", "0")), parse(VERSION)
    program = program_in(existing)
    same_build = marker.get("build") == fingerprint(paths.program_path())
    if program.exists() and (theirs > ours or (theirs == ours and same_build)):
        return "open", program
    return "setup", existing


# ---- installing -----------------------------------------------------------------

def _writable(target):
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".devkit-write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise Refused(f"The kit cannot write in {target} ({exc.strerror or exc}). "
                      f"Choose another folder.") from None


def _size(path):
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*")
                   if f.is_file() and not f.is_symlink())
    return path.stat().st_size


def _copy_program(source, program, tell=None):
    """Copy the program, saying how far it is: `tell(fraction)`, 0 to 1."""
    fresh = program.with_name(program.name + ".installing")
    total, done = max(_size(source), 1), 0

    def copy(src, dst):
        nonlocal done
        with open(src, "rb") as read, open(dst, "wb") as write:
            for block in iter(lambda: read.read(1 << 20), b""):
                write.write(block)
                done += len(block)
                if tell:
                    tell(min(done / total, 1.0))
        shutil.copystat(src, dst)
        return dst

    try:
        if source.is_dir():   # a Mac .app
            shutil.rmtree(fresh, ignore_errors=True)
            shutil.copytree(source, fresh, symlinks=True, copy_function=copy)
            old = program.with_name(program.name + ".replaced")
            shutil.rmtree(old, ignore_errors=True)
            if program.exists():
                os.replace(program, old)
            os.replace(fresh, program)
            shutil.rmtree(old, ignore_errors=True)
        else:
            copy(source, fresh)
            os.replace(fresh, program)
    except PermissionError:
        raise Refused(f"The Dev Kit in {program.parent} is open. Close it, then "
                      f"press the button again.") from None
    except OSError as exc:
        raise Refused(f"The kit could not be copied to {program.parent} "
                      f"({exc.strerror or exc}).") from None
    finally:
        if fresh.is_dir():
            shutil.rmtree(fresh, ignore_errors=True)
        else:
            fresh.unlink(missing_ok=True)


def write_marker(folder, program):
    """Say that `folder` is an install of this version, holding `program`."""
    marker = {"version": VERSION, "build": fingerprint(program),
              "installed": time.time()}
    (Path(folder) / paths.MARKER).write_text(json.dumps(marker, indent=1),
                                             encoding="utf-8")


def place(target, source=None, tell=None):
    """The part of an install that writes in the install folder: the program,
    the marker that says "this folder is an install", and an empty `Files` if
    there is none. Never touches what is in `Files`. Returns the program.
    `tell(step, fraction)` is told what is being done."""
    tell = tell or (lambda step, fraction=None: None)
    source = Path(source or paths.program_path())
    target = Path(target)
    _writable(target)
    program = target / source.name
    tell("copying", 0.0)
    if source.resolve() != program.resolve():
        _copy_program(source, program, lambda fraction: tell("copying", fraction))
    tell("finishing")
    (target / paths.FILES).mkdir(exist_ok=True)
    write_marker(target, program)
    return program


def needs_admin(target):
    """Would Windows refuse this account the kit's folder at `target`? Asked
    of the nearest folder that exists, by trying: Windows' own "is it
    writable" looks at a file's read-only tick, not at who may write.

    ONE try, made here. `tempfile` must not be given this job: told "access
    denied" in a folder that exists, Python 3.12's takes it for a name that
    is taken and tries another - two thousand million times. v0.1.2 as
    released (built with 3.12) sat at "Starting... 0%" for exactly that
    reason, while the same code built with 3.14 on the machine it was written
    on answered at once.
    """
    if not sys.platform.startswith("win"):
        return False
    folder = Path(target)
    while not folder.is_dir():
        if folder.parent == folder:
            return False
        folder = folder.parent
    probe = folder / f".devkit-probe-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        handle = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except PermissionError:
        return True
    except OSError:
        return False
    os.close(handle)
    try:
        probe.unlink()
    except OSError:
        pass
    return False


def account_sid():
    """This account, as Windows names it for permissions ("" if it will not
    say). Asked for before the permission question, because the answer to
    that may be another person's password and so another account."""
    try:
        done = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        row = next(csv.reader(done.stdout.strip().splitlines()))
    except (OSError, subprocess.SubprocessError, StopIteration, csv.Error):
        return ""
    return row[-1] if row and _SID.fullmatch(row[-1]) else ""


_SID = re.compile(r"S-1-\d+(-\d+)+")
_USERS = "S-1-5-32-545"   # the machine's Users group, in any language


def allow(folder, sid):
    """Give an account the right to change what is in `folder` — the kit's
    own folder, never anything above it."""
    sid = sid if _SID.fullmatch(sid or "") else _USERS
    try:
        done = subprocess.run(
            ["icacls", str(folder), "/grant", f"*{sid}:(OI)(CI)M"],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f"Windows would not open {folder} to your account ({exc}).") from None
    if done.returncode != 0:
        raise Refused(f"Windows would not open {folder} to your account "
                      f"({(done.stderr or done.stdout).strip()[:200]}).")


def open_folder_from_command(args):
    """The program started as `PixelPomoDevKit.exe --open-folder <folder> ...`,
    with Windows' permission: make the kit's folder, open it to the artist's
    account, write down how it went, and stop. No window, no kit, and no
    copying: once the folder is the artist's to write, the setup that asked
    does the rest itself, where its progress can be seen."""
    ap = argparse.ArgumentParser(prog=paths.NAME + " " + OPEN_FLAG)
    ap.add_argument("target")
    ap.add_argument("--for", dest="sid", default="")
    ap.add_argument("--report")
    asked = ap.parse_args(args)
    try:
        target = Path(asked.target)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Refused(f"The folder {target} could not be made "
                          f"({exc.strerror or exc}).") from None
        allow(target, asked.sid)
        answer = {"ok": True}
    except Refused as exc:
        answer = {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - whoever waits must get an answer
        log.exception("opening the kit's folder failed")
        answer = {"error": f"The install did not finish: {exc}"}
    log.info("%s %s: %s", OPEN_FLAG, asked.target, answer)
    if asked.report:
        try:
            Path(asked.report).write_text(json.dumps(answer), encoding="utf-8")
        except OSError:
            pass
    return 0 if answer.get("ok") else 1


def _own_command():
    """How to start this program again."""
    if paths.frozen():
        return [sys.executable]
    return [sys.executable, "-m", "dev_kit"]


def _setup_window():
    """The setup window's handle, so that Windows puts its question in front
    of it. A question asked for no window in particular can open BEHIND
    everything, as a shield flashing on the taskbar - which is how v0.1.1's
    setup came to sit at "INSTALLING..." for ever."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        window = user32.FindWindowW(None, SETUP_TITLE)
        if window:
            user32.SetForegroundWindow(window)
        return window
    except (OSError, AttributeError):
        return None


def _run_with_permission(command, cwd=None, window=None, limit=PERMITTED_LIMIT,
                         verb="runas"):
    """Start `command` through Windows' permission question and wait for it.
    Returns its exit code; None when the question was answered "no"; raises
    TimeoutError when it was allowed and then did not finish in `limit`
    seconds. How long the QUESTION stays unanswered is not limited here:
    that is the artist reading it.

    `verb` is "runas" - with permission. "open" starts the same command the
    same way without asking, which is how everything here except the
    question itself is tried on a machine with nobody to answer it."""
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long

    info = Info()
    info.cbSize = ctypes.sizeof(Info)
    info.fMask = 0x40 | 0x100   # keep the process handle; finish before returning
    info.hwnd = window
    info.lpVerb = verb
    info.lpFile = command[0]
    info.lpParameters = subprocess.list2cmdline(command[1:])
    info.lpDirectory = str(cwd) if cwd else None
    info.nShow = 0
    # The shell does this through COM, which wants this thread set up for it.
    # 0 and 1 are "done" and "was already": both are ours to undo.
    com = ole32.CoInitializeEx(None, 0x2 | 0x4) in (0, 1)
    # The new process is given this one's environment. Without PyInstaller's
    # own variables in it, so that it unpacks itself (see clean_environment).
    hidden = {k: os.environ.pop(k) for k in list(os.environ)
              if k.startswith("_MEIPASS") or k.startswith("_PYI_")}
    try:
        started = shell32.ShellExecuteExW(ctypes.byref(info))
        error = ctypes.get_last_error()
    finally:
        os.environ.update(hidden)
        if com:
            ole32.CoUninitialize()
    if not started:
        if error == _CANCELLED:
            return None
        raise OSError(error, ctypes.FormatError(error).strip())
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(limit * 1000)) == 0x102:
            raise TimeoutError
        code = wintypes.DWORD(1)
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def open_as_admin(target):
    """Make the kit's folder in a place that belongs to the system, and open
    it to this account: Windows asks for permission, and the program, started
    again with it, does `open_folder_from_command`. Nothing is copied yet."""
    report = Path(tempfile.gettempdir()) / f"devkit-setup-{os.getpid()}.json"
    report.unlink(missing_ok=True)
    command = _own_command() + [OPEN_FLAG, str(target), "--for", account_sid(),
                                "--report", str(report)]
    log.info("asking Windows for permission to install in %s", target)
    try:
        code = _run_with_permission(
            command, cwd=None if paths.frozen() else paths.source_root(),
            window=_setup_window())
    except TimeoutError:
        log.error("the permitted half did not finish")
        raise Refused(f"Windows gave permission, but the folder {target} was not "
                      f"ready after {PERMITTED_LIMIT} seconds. Press the button "
                      f"again, or choose another folder.") from None
    except OSError as exc:
        raise Refused(f"Windows could not ask for permission to install in "
                      f"{target} ({exc.strerror or exc}). Choose another folder.") from None
    log.info("the permission question ended with %s", code)
    if code is None:
        raise Refused(f"Windows asked for permission to install in {target} and "
                      f"the answer was no. Press the button again, or choose "
                      f"another folder.")
    try:
        answer = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        answer = {}
    finally:
        report.unlink(missing_ok=True)
    if not answer.get("ok"):
        raise Refused(answer.get("error")
                      or f"The install in {target} did not finish (code {code}).")


def install(target, shortcut=True, source=None, tell=None):
    """Put the running program in `target` and return the installed program.

    Where the folder is the system's, Windows is asked once to make it and
    open it to this account (`open_as_admin`); everything else — the copy
    (`place`), the note of where the kit is, the Desktop shortcut — is done
    here, as the artist. `tell(step, fraction=None)` hears each step as it
    starts: "permission", "copying" (with how far), "finishing", "shortcut".
    """
    tell = tell or (lambda step, fraction=None: None)
    source = Path(source or paths.program_path())
    target = Path(target)
    if source.suffix == ".app" and source in [target, *target.parents]:
        raise Refused("That folder is inside the Dev Kit itself.")
    if needs_admin(target):
        tell("permission")
        open_as_admin(target)
    program = place(target, source, tell)
    try:
        record_path().parent.mkdir(parents=True, exist_ok=True)
        record_path().write_text(json.dumps({"dir": str(target)}), encoding="utf-8")
    except OSError:
        log.warning("could not note the install folder in %s", record_path())
    if shortcut and sys.platform.startswith("win"):
        tell("shortcut")
        made = make_shortcut(program)
        log.info("desktop shortcut: %s", made or "not made")
    log.info("installed %s in %s", VERSION, target)
    return program


def refresh_marker():
    """Bring the install's marker up to date with the program that is
    running. An update swaps the program and nothing else, so the marker is
    still the old version's until the new kit's first start says otherwise —
    and a download started later is compared against what it says."""
    if not paths.installed():
        return False
    folder = paths.program_dir()
    marker = marker_of(folder)
    if marker.get("version") == VERSION:
        return False
    marker.update(version=VERSION, build=fingerprint(paths.program_path()),
                  updated=time.time())
    try:
        (folder / paths.MARKER).write_text(json.dumps(marker, indent=1), encoding="utf-8")
    except OSError:
        log.warning("could not bring %s up to date", folder / paths.MARKER)
        return False
    return True


def make_shortcut(program, folder=None):
    """A shortcut to `program` on the artist's Desktop (or in `folder`).
    Returns its path, or None if Windows would not make one — which is not a
    reason to fail an install.

    Through PowerShell's WScript.Shell, which every Windows 10 and 11 has: the
    Desktop is asked for by name, so a Desktop that OneDrive moved is found.
    """
    script = (
        "$d = if ($env:DEVKIT_LNK_DIR) { $env:DEVKIT_LNK_DIR } "
        "else { [Environment]::GetFolderPath('Desktop') }; "
        "$p = Join-Path $d ($env:DEVKIT_LNK_NAME + '.lnk'); "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p); "
        "$s.TargetPath = $env:DEVKIT_LNK_TARGET; "
        "$s.WorkingDirectory = (Split-Path $env:DEVKIT_LNK_TARGET); "
        "$s.IconLocation = $env:DEVKIT_LNK_TARGET + ',0'; "
        "$s.Description = 'Pixel Pomo Dev Kit'; "
        "$s.Save(); Write-Output $p")
    env = {**paths.clean_environment(), "DEVKIT_LNK_TARGET": str(program),
           "DEVKIT_LNK_NAME": SHORTCUT_NAME,
           # DEVKIT_LNK_DIR set outside is for trying a whole install without
           # leaving a shortcut on the Desktop of whoever is trying it
           "DEVKIT_LNK_DIR": str(folder or os.environ.get("DEVKIT_LNK_DIR", ""))}
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-Command", script],
            env=env, capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    made = Path(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else None
    return made if done.returncode == 0 and made and made.is_file() else None


def launch(program):
    """Start the installed kit and let it outlive this process."""
    program = Path(program)
    env = paths.clean_environment()
    if program.suffix == ".app":
        subprocess.Popen(["open", "-n", str(program)], env=env, close_fds=True)
    else:
        subprocess.Popen([str(program)], env=env, close_fds=True,
                         cwd=str(program.parent))


# ---- asking -----------------------------------------------------------------------

class _SetupApi:
    """What the setup window's page can ask of the program. pywebview offers
    every public method to the page; everything else here is underscored."""

    def __init__(self, existing):
        self._existing = existing
        self._window = None
        self._program = None
        self._lock = threading.Lock()
        self._state = {"running": False}

    def facts(self):
        existing = self._existing
        return {
            "version": VERSION,
            "folder": str(existing or default_dir()),
            "existing": str(existing) if existing else "",
            "existingVersion": marker_of(existing).get("version", "") if existing else "",
            "windows": sys.platform.startswith("win"),
            "filesName": paths.FILES,
        }

    def resolve(self, text):
        """Where the kit would go for what is typed in the box."""
        try:
            target = target_for(text)
        except Refused as exc:
            return {"error": str(exc)}
        return {"target": str(target), "files": str(target / paths.FILES),
                "update": (target / paths.MARKER).is_file(),
                "admin": needs_admin(target)}

    def browse(self, start):
        import webview
        try:
            picked = self._window.create_file_dialog(
                webview.FileDialog.FOLDER, directory=str(start or ""))
        except Exception:  # noqa: BLE001 - a dialog that will not open picks nothing
            log.exception("the folder dialog failed")
            return ""
        return str(picked[0]) if picked else ""

    def install(self, text, shortcut):
        """Start installing and return at once: the page then asks
        `progress` how it is going. The work is on a thread of its own, one
        that does not keep the program alive - closing the setup window ends
        the setup, even while Windows' question is still unanswered."""
        try:
            target = target_for(text)
        except Refused as exc:
            return {"error": str(exc)}
        with self._lock:
            if self._state.get("running"):
                return {"started": True}
            self._state = {"running": True, "step": "", "fraction": 0.0,
                           "busy": True, "text": "Starting", "hint": ""}
        threading.Thread(target=self._install, args=(target, bool(shortcut)),
                         daemon=True, name="install").start()
        return {"started": True}

    def _tell(self, step, fraction=None):
        text, hint, start, end = _STEPS[step]
        with self._lock:
            self._state.update(
                step=step, text=text, hint=hint, busy=fraction is None,
                fraction=start + (end - start) * (fraction or 0.0))

    def _install(self, target, shortcut):
        try:
            program = install(target, shortcut=shortcut, tell=self._tell)
        except Refused as exc:
            outcome = {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - the page must get an answer
            log.exception("install failed")
            outcome = {"error": f"The install did not finish: {exc}"}
        else:
            self._program = program
            outcome = {"done": True, "fraction": 1.0, "text": "Installed",
                       "target": str(target), "files": str(target / paths.FILES)}
        with self._lock:
            self._state.update(outcome, running=False, busy=False, hint="")

    def progress(self):
        """How the install is going: `running`, the `step` and its `text`, a
        `hint` for a step that waits on the artist, `fraction` of the whole
        (0 to 1) and `busy` when the step cannot say how far it is - then,
        once, `done` with where the kit is, or `error`."""
        with self._lock:
            return dict(self._state)

    def close(self):
        if self._window is not None:
            self._window.destroy()


# What each step of an install says, and its share of the bar: (text, hint,
# from, to). Copying is the one step that knows how far it is.
_STEPS = {
    "permission": ("Waiting for Windows - answer Yes to its question",
                   "No question on the screen? It is waiting behind this window: "
                   "click the shield flashing on the taskbar.", 0.04, 0.04),
    "copying": ("Copying the Dev Kit", "", 0.10, 0.85),
    "finishing": ("Writing down the install", "", 0.88, 0.88),
    "shortcut": ("Putting a shortcut on the Desktop", "", 0.93, 0.93),
}


def _logo():
    path = paths.asset("icon.png")
    if path is None:
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def setup_page():
    return _PAGE.replace("{{LOGO}}", _logo())


def run_setup(existing=None):
    """Show the setup window. Returns the installed program, or None if the
    artist closed it without installing."""
    from dev_kit import window
    if not window.native_window_available():
        return _plain_setup(existing)
    import webview
    api = _SetupApi(existing)
    api._window = webview.create_window(
        SETUP_TITLE, html=setup_page(), js_api=api,
        width=760, height=685, resizable=False, background_color=window.BACKGROUND)
    icon = window.icon_path()
    webview.start(icon=str(icon) if icon else None)
    return api._program


def _plain_setup(existing):
    """Without a web view there is no window to draw: ask with the system's
    own yes/no box, and install where the kit suggests."""
    target = existing or default_dir()
    question = (f"Install Pixel Pomo Dev Kit {VERSION} in\n\n{target}\n\n"
                f"Your files will be kept in {target / paths.FILES}.")
    if sys.platform.startswith("win"):
        import ctypes
        if ctypes.windll.user32.MessageBoxW(None, question, "Pixel Pomo Dev Kit Setup",
                                            0x24) != 6:   # MB_YESNO | ICONQUESTION, IDYES
            return None
    try:
        return install(target)
    except Refused as exc:
        log.error("install refused: %s", exc)
        return None


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pixel Pomo Dev Kit Setup</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #161616; color: #f2f2f2;
         font: 14px/1.6 "Cascadia Mono", Consolas, Menlo, monospace; }
  main { padding: 28px 34px; }
  header { display: flex; align-items: center; gap: 16px; margin-bottom: 22px; }
  header img { width: 56px; height: 56px; image-rendering: pixelated; }
  h1 { font-size: 20px; margin: 0; letter-spacing: 1px; }
  .dim { color: #9a9a9a; }
  label { display: block; margin: 18px 0 6px; color: #9a9a9a; font-size: 12px;
          letter-spacing: 1px; }
  .row { display: flex; gap: 10px; }
  input[type=text] { flex: 1; background: #0e0e0e; color: #f2f2f2; padding: 10px 12px;
          border: 2px solid #5a5a5a; font: inherit; min-width: 0; }
  input[type=text]:focus { outline: none; border-color: #e5484d; }
  button { background: #242424; color: #f2f2f2; border: 2px solid #8a8a8a;
           padding: 10px 18px; font: inherit; letter-spacing: 1px; cursor: pointer; }
  button:hover { border-color: #f2f2f2; }
  button.main { background: #e5484d; border-color: #f2f2f2; color: #fff; }
  button:disabled { opacity: .45; cursor: default; }
  .box { margin-top: 16px; padding: 12px 14px; border: 2px solid #333; background: #1d1d1d; }
  .path { color: #7fd6a0; word-break: break-all; }
  .error { color: #ff7a7a; min-height: 22px; margin-top: 12px; }
  #progress { margin-top: 18px; }
  .bar { height: 16px; border: 2px solid #8a8a8a; background: #0e0e0e;
         overflow: hidden; position: relative; }
  .bar > div { height: 100%; width: 0; background: #e5484d; transition: width .15s linear; }
  .bar.busy > div { transition: none; background: repeating-linear-gradient(
         90deg, #e5484d 0 12px, #8f2a2e 12px 24px); background-size: 24px 100%;
         animation: march .5s linear infinite; }
  @keyframes march { to { background-position: 24px 0; } }
  #step { margin-top: 8px; display: flex; justify-content: space-between; gap: 12px; }
  #hint { margin-top: 4px; color: #f2c94c; min-height: 44px; }
  .check { display: flex; align-items: center; gap: 10px; margin-top: 16px; }
  .check input { width: 18px; height: 18px; accent-color: #e5484d; }
  footer { display: flex; gap: 10px; margin-top: 22px; }
  [hidden] { display: none !important; }
</style></head>
<body><main>
  <header>
    <img src="{{LOGO}}" alt="">
    <div><h1 id="title">PIXEL POMO DEV KIT</h1><div class="dim" id="sub"></div></div>
  </header>

  <section id="ask">
    <p id="intro"></p>
    <label for="folder">INSTALL IN</label>
    <div class="row">
      <input type="text" id="folder" spellcheck="false" autocomplete="off">
      <button type="button" id="browse">BROWSE...</button>
    </div>
    <div class="box">
      <div class="dim">The kit will be in</div><div class="path" id="target"></div>
      <div class="dim" style="margin-top:8px">Everything you add is kept in</div>
      <div class="path" id="files"></div>
      <div class="dim" style="margin-top:8px">An update replaces the program only. That folder is never touched.</div>
    </div>
    <div class="dim" id="admin" style="margin-top:10px" hidden>Windows will ask for permission once: this is where programs are installed.</div>
    <div class="check" id="shortcutRow">
      <input type="checkbox" id="shortcut" checked>
      <label for="shortcut" style="margin:0;color:#f2f2f2;font-size:14px;letter-spacing:0">Put a shortcut on the Desktop</label>
    </div>
    <div id="progress" hidden>
      <div class="bar" id="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"
           aria-labelledby="stepText"><div id="fill"></div></div>
      <div id="step"><span id="stepText"></span><span id="percent"></span></div>
      <div id="hint"></div>
    </div>
    <div class="error" id="error" role="alert"></div>
    <footer>
      <button type="button" class="main" id="install">INSTALL</button>
      <button type="button" id="cancel">CANCEL</button>
    </footer>
  </section>

  <section id="done" hidden>
    <p id="doneText"></p>
    <div class="box">
      <div class="dim">The kit is in</div><div class="path" id="doneTarget"></div>
      <div class="dim" style="margin-top:8px">Your files are kept in</div>
      <div class="path" id="doneFiles"></div>
    </div>
    <footer><button type="button" class="main" id="open">OPEN THE DEV KIT</button></footer>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
let api = null, updating = false, installing = false, wantsAdmin = false;

// While installing, the page asks how far it is instead of waiting for one
// answer at the end: the bar, the step in words, and what to do when the
// step is waiting on a question from Windows.
function show(p) {
  $('bar').classList.toggle('busy', !!p.busy);
  const percent = Math.round((p.fraction || 0) * 100);
  $('fill').style.width = Math.max(percent, p.busy ? 6 : 0) + '%';
  $('bar').setAttribute('aria-valuenow', percent);
  $('stepText').textContent = (p.text || '') + '...';
  $('percent').textContent = percent + '%';
  $('hint').textContent = p.hint || '';
}

function setInstalling(on) {
  installing = on;
  for (const id of ['folder', 'browse', 'shortcut']) $(id).disabled = on;
  $('progress').hidden = !on;
  // the two lines the bar takes the place of: both are about what is next,
  // and what is next has started
  $('shortcutRow').hidden = on || !windows;
  $('admin').hidden = on || !wantsAdmin;
  $('install').disabled = on;
  $('install').textContent = on ? (updating ? 'UPDATING...' : 'INSTALLING...')
                                : (updating ? 'UPDATE' : 'INSTALL');
}

async function watch() {
  let p;
  try { p = await api.progress(); } catch (e) { p = {running: true}; }
  if (p.error) { setInstalling(false); $('error').textContent = p.error; refresh(); return; }
  if (p.done) {
    show(p);
    $('ask').hidden = true; $('done').hidden = false;
    $('doneText').textContent = updating ? 'Updated. Everything you added is still there.'
                                         : 'Installed.';
    $('doneTarget').textContent = p.target; $('doneFiles').textContent = p.files;
    $('open').focus();
    return;
  }
  show(p);
  setTimeout(watch, 150);
}
let windows = false;

async function refresh() {
  const r = await api.resolve($('folder').value);
  $('error').textContent = r.error || '';
  $('target').textContent = r.target || '';
  $('files').textContent = r.files || '';
  if (installing) return;
  $('install').disabled = !!r.error;
  wantsAdmin = !!r.admin;
  $('admin').hidden = !wantsAdmin;
  updating = !!r.update;
  $('install').textContent = updating ? 'UPDATE' : 'INSTALL';
}

async function start() {
  api = window.pywebview.api;
  const f = await api.facts();
  $('sub').textContent = 'version ' + f.version + ' - setup';
  $('intro').textContent = f.existing
    ? 'Version ' + (f.existingVersion || 'older') + ' is installed. Updating it keeps everything you added.'
    : 'Choose where the Dev Kit lives. It gets one folder, and your files stay in it.';
  $('folder').value = f.folder;
  windows = !!f.windows;
  $('shortcutRow').hidden = !windows;
  $('folder').addEventListener('input', refresh);
  $('browse').addEventListener('click', async () => {
    const picked = await api.browse($('folder').value);
    if (picked) { $('folder').value = picked; refresh(); }
  });
  $('cancel').addEventListener('click', () => api.close());
  $('open').addEventListener('click', () => api.close());
  $('install').addEventListener('click', async () => {
    $('error').textContent = '';
    setInstalling(true);
    show({busy: true, fraction: 0, text: 'Starting'});
    const r = await api.install($('folder').value, $('shortcut').checked);
    if (r.error) { setInstalling(false); $('error').textContent = r.error; refresh(); return; }
    watch();
  });
  refresh();
}
window.addEventListener('pywebviewready', start);
</script></body></html>
"""
