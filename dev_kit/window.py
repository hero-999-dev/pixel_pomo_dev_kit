"""The kit's window.

The kit is a program with a window of its own: its title, its icon in the
title bar and on the taskbar, closed with its own X. Inside that window is the
page (a Flutter web build), shown by the web view the system already has —
WebView2 on Windows, WKWebView on a Mac — through `pywebview`.

`run_native_window` is that window. The rest of this file is what happens on
a machine that cannot make one (a Windows without the WebView2 runtime): the
page opens in Edge or Chrome's *app mode* instead, and failing that as a tab
in the default browser. It works the same there; it just looks borrowed.
"""
import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from dev_kit import paths

log = logging.getLogger("dev_kit")

TITLE = "Pixel Pomo Dev Kit"
WINDOW_SIZE = (1280, 860)
MIN_SIZE = (960, 640)
BACKGROUND = "#161616"   # the game's DARK background, shown while the page loads


def icon_path():
    """The kit's icon as a file, for the window. (A frozen Windows program
    would get its own .exe icon anyway; from source this is what stops the
    window wearing Python's.)"""
    return paths.asset("icon.ico")


def native_window_available():
    """Can this machine show the page in a window of the kit's own?

    On Windows that takes the WebView2 runtime (part of Windows 11, and of any
    Windows 10 that has Edge up to date). Without it pywebview would fall back
    to the Internet Explorer engine, which cannot run the page at all — so
    that case is answered "no" here and handled by the browser instead.
    """
    if os.environ.get("DEVKIT_WINDOW") == "browser":
        return False
    try:
        import webview  # noqa: F401
        if sys.platform.startswith("win"):
            from webview.platforms import winforms
            if winforms.renderer != "edgechromium":
                log.info("no WebView2 runtime here (pywebview would use %s)", winforms.renderer)
                return False
    except Exception as exc:  # noqa: BLE001 - any failure means "use the browser"
        log.info("no native window on this machine: %r", exc)
        return False
    return True


def run_native_window(url, storage_dir):
    """Show the kit in its own window and return when the artist closes it.

    Must be called on the main thread (a rule of every window system). Returns
    False, having shown nothing, where a native window is not possible.
    """
    if not native_window_available():
        return False
    import webview
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    try:
        webview.create_window(TITLE, url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                              min_size=MIN_SIZE, background_color=BACKGROUND,
                              text_select=True)
        icon = icon_path()
        # not private: the web view's own cache lives in the kit's folder, in
        # one known place, instead of a new temp folder every start
        webview.start(private_mode=False, storage_path=str(storage_dir),
                      icon=str(icon) if icon else None)
    except Exception:  # noqa: BLE001
        log.exception("the native window failed")
        return False
    return True


def close_native_window():
    """Close the kit's window from another thread — which ends the program,
    as the artist's own X does. For an update that is ready to swap in."""
    try:
        import webview
        for open_window in list(webview.windows):
            open_window.destroy()
        return True
    except Exception:  # noqa: BLE001
        log.exception("the window would not close")
        return False


def focus_existing_window():
    """Bring the already-open kit to the front. True if there was one to bring.

    Windows only: a Mac does this by itself when a running app is opened again.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, TITLE)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE: un-minimise it
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- when there can be no native window --------------------------------------

def _candidates():
    if sys.platform.startswith("win"):
        roots = [os.environ.get(name) for name in
                 ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for tail in (r"Microsoft\Edge\Application\msedge.exe",
                     r"Google\Chrome\Application\chrome.exe",
                     r"BraveSoftware\Brave-Browser\Application\brave.exe"):
            for root in roots:
                if root:
                    yield Path(root) / tail
    elif sys.platform == "darwin":
        for folder in (Path("/Applications"), Path.home() / "Applications"):
            for app, binary in (("Google Chrome", "Google Chrome"),
                                ("Microsoft Edge", "Microsoft Edge"),
                                ("Brave Browser", "Brave Browser"),
                                ("Chromium", "Chromium")):
                yield folder / f"{app}.app" / "Contents" / "MacOS" / binary
    else:
        for name in ("google-chrome", "chromium", "chromium-browser",
                     "microsoft-edge", "brave-browser"):
            found = shutil.which(name)
            if found:
                yield Path(found)


def find_browser():
    """A Chromium that can open an app window, or None."""
    override = os.environ.get("DEVKIT_BROWSER")
    if override:
        return Path(override) if Path(override).is_file() else None
    for path in _candidates():
        if path.is_file():
            return path
    return None


def app_window_command(browser, url, profile_dir, extra=()):
    return [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        f"--window-size={WINDOW_SIZE[0]},{WINDOW_SIZE[1]}",
        "--no-first-run",
        "--no-default-browser-check",
        # Without this a fresh Edge profile keeps a process alive after its
        # last window closes, and the launcher would wait on it for ever.
        "--disable-background-mode",
        # the kit is one page in English with pixel fonts; none of these help
        "--disable-features=Translate,msEdgeTranslate,AutofillServerCommunication",
        "--disable-sync",
        *extra,
    ]


def open_app_window(url, profile_dir, extra=()):
    """Start a browser's app window on the kit. Returns its process, or None
    if there is no browser here that can do it (or it would not start)."""
    browser = find_browser()
    if browser is None:
        return None
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    try:
        return subprocess.Popen(app_window_command(browser, url, profile_dir, extra))
    except OSError:
        return None


def open_in_default_browser(url):
    try:
        return bool(webbrowser.open(url))
    except webbrowser.Error:
        return False
