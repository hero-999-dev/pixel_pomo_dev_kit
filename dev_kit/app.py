"""Start the kit: set it up if this is a download, else serve the page, open
its window, and stop when it closes.

The window is the kit's own (`window.run_native_window`). Everything here
about a browser's process and the page "going quiet" is for the machine where
that is not possible and the page has to open in a browser instead.
"""
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request

from dev_kit import installer, paths, updater, window
from dev_kit.library import Library
from dev_kit.server import APP, KitServer
from dev_kit.version import VERSION

log = logging.getLogger("dev_kit")

# The kit asks for the same port every run and takes the next one if it is
# busy. A fixed port is what lets a second start find the first one's window
# instead of opening a second kit on the same files.
PORTS = range(8791, 8800)

# The page says "I am open" every 10 s. A browser slows a hidden window's
# timers to one a minute, so a kit that has merely been minimised still gets a
# word in well inside this.
QUIET_LIMIT = 150.0
# ...and how long to wait for the first word before deciding nothing opened.
FIRST_WORD_LIMIT = 300.0
# After our window's process ends, how long the page has to speak up before
# the window is taken to be closed. Two of its 10 s words, and a little.
HANDOFF_GRACE = 25.0


def alert(text):
    """Tell the artist something went wrong. The program has no console."""
    log.error(text)
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Pixel Pomo Dev Kit", 0x10)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["osascript", "-e",
                            f'display alert "Pixel Pomo Dev Kit" message {json.dumps(text)}'],
                           check=False)
        else:
            print(text, file=sys.stderr)
    except Exception:  # noqa: BLE001 - reporting a failure must not be one
        pass


def running_kit(port):
    """Is a Dev Kit already answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hello", timeout=1.5) as r:
            return json.loads(r.read()).get("app") == APP
    except urllib.error.HTTPError as answered:
        answered.close()   # something is there, and it is not a kit
        return False
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_server(library, web_dir, ports=PORTS, updates=None):
    """(server, None) on a free port, or (None, url) when a kit is already
    running and the right thing to do is show its window."""
    for port in ports:
        try:
            return KitServer(library, web_dir, port, updates=updates), None
        except OSError:
            if running_kit(port):
                return None, f"http://127.0.0.1:{port}/"
    raise OSError(f"ports {ports[0]}-{ports[-1]} are all in use")


def wait_until_closed(server, process, sleep=time.sleep, clock=time.monotonic,
                      quiet_limit=QUIET_LIMIT, first_word_limit=FIRST_WORD_LIMIT,
                      handoff_grace=HANDOFF_GRACE, stopped=lambda: False):
    """Block until the kit's window is gone.

    With a window of our own that is when its process ends — unless the page
    goes on talking, which means the browser handed the window to a process it
    already had running and ours only delivered the request. The page's own
    silence counts as well: a default-browser tab has no process to watch, and
    a browser can outlive its last window. `stopped` is the kit deciding for
    itself: an update is staged and waiting for it to go.
    """
    started = last_tick = clock()
    gone_at = None   # when our window's process ended
    while True:
        sleep(2.0)
        if stopped():
            return "the kit is restarting"
        now = clock()
        if process is not None and process.poll() is not None:
            process, gone_at = None, now
        if now - last_tick > 30:
            # The machine slept: every timer here and in the page stood still
            # together. Give the page a fresh allowance instead of counting
            # the night against it.
            started = now
            if server.last_seen is not None:
                server.last_seen = now
            if gone_at is not None:
                gone_at = now
        last_tick = now
        seen = server.last_seen
        if gone_at is not None:
            if seen is not None and seen > gone_at:
                gone_at = None   # still talking: the window lives elsewhere
            elif now - gone_at > handoff_grace:
                return "the window closed"
        elif seen is None:
            if now - started > first_word_limit:
                return "the page never opened"
        elif now - seen > quiet_limit:
            return "the page went quiet"


def _log_to(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(folder / name), level=logging.INFO, force=True,
                        format="%(asctime)s %(levelname)s %(message)s")


def set_up(action, subject):
    """This program is a download, not the installed kit: open the installed
    one, or ask where to install."""
    _log_to(paths.per_user_dir(), "setup.log")
    log.info("Pixel Pomo Dev Kit %s started from %s: %s %s", VERSION,
             paths.program_path(), action, subject or "")
    if action == "open":
        installer.launch(subject)
        return 0
    try:
        program = installer.run_setup(subject)
    except Exception as exc:  # noqa: BLE001
        log.exception("setup failed")
        alert(f"The Dev Kit's setup could not open: {exc}")
        return 1
    if program is None:
        log.info("setup closed without installing")
        return 0
    installer.launch(program)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [installer.OPEN_FLAG]:
        # the half of an install that Windows gave permission to
        _log_to(paths.per_user_dir(), "setup.log")
        return installer.open_folder_from_command(argv[1:])

    action, subject = installer.decide()
    if action != "run":
        return set_up(action, subject)

    data = paths.data_dir()
    _log_to(data, "devkit.log")
    log.info("Pixel Pomo Dev Kit %s starting, files in %s", VERSION, data)
    if installer.refresh_marker():
        log.info("this is the first start of %s here", VERSION)

    web = paths.web_dir()
    if not (web / "index.html").is_file():
        alert(f"The Dev Kit's page is missing ({web}).\n\n"
              "From source, build it first: Terminal\\dev-kit.ps1 -Build")
        return 1

    # An update that is downloaded and staged: the script that will swap it
    # in once this process has gone, and the way to make it go.
    staged = {}
    restarting = threading.Event()

    def update_ready(script):
        staged["script"] = script
        restarting.set()
        # a moment for the page to say so before its window goes
        threading.Timer(1.5, window.close_native_window).start()

    try:
        library = Library(data)
        for old in paths.legacy_data_dirs():
            adopted = library.adopt(old)
            if adopted:
                log.info("brought %d items over from %s", adopted, old)
        port = os.environ.get("DEVKIT_PORT")
        server, already = start_server(
            library, web, [int(port)] if port else PORTS,
            updates=updater.Updates(data, on_ready=update_ready))
    except OSError as exc:
        alert(f"The Dev Kit could not start: {exc}")
        return 1

    profile = paths.profile_dir().with_name("browser")   # only without a native window
    if already:
        # A second double-click: bring the kit that is already running to the
        # front. (Its window may be a browser's, on a machine with no native
        # one - then open another on the same kit.)
        log.info("already running at %s", already)
        if window.focus_existing_window():
            log.info("brought its window to the front")
        else:
            log.info("it has no window of its own; opening a browser on it")
            if window.open_app_window(already, profile) is None:
                window.open_in_default_browser(already)
        return 0

    server.serve_in_background()
    log.info("serving %s at %s", web, server.url)

    def finish(why):
        log.info("stopping: %s", why)
        server.shutdown()
        script = staged.get("script")
        if script:
            log.info("handing over to %s", script)
            updater.launch_handoff(script)
        return 0

    if os.environ.get("DEVKIT_NO_WINDOW"):
        # for the tests and for looking at the page in another browser
        print(server.url, flush=True)
        try:
            while not restarting.wait(3600):
                pass
        except KeyboardInterrupt:
            return 0
        return finish("the kit is restarting")

    # The kit's own window. This call IS the program from here on: it returns
    # when the artist closes the window.
    if window.run_native_window(server.url, paths.profile_dir()):
        return finish("the window closed")

    log.info("no native window; opening the kit in a browser instead")
    process = window.open_app_window(server.url, profile)
    if process is None:
        log.info("no app-window browser found; using the default browser")
        if not window.open_in_default_browser(server.url):
            alert(f"The Dev Kit is running but no browser would open.\n\n"
                  f"Open this address yourself: {server.url}")
    why = wait_until_closed(server, process, stopped=restarting.is_set)
    if process is not None and process.poll() is None:
        process.terminate()   # ours alone: it runs on the kit's own profile
    return finish(why)
