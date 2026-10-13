"""Starting, finding a kit that is already running, and knowing when to stop."""
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from dev_kit import app, paths, window
from dev_kit.library import Library
from dev_kit.server import KitServer


class Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


class FakeServer:
    last_seen = None


class FakeProcess:
    def __init__(self, ends_at):
        self.ends_at, self.clock = ends_at, None

    def poll(self):
        return 0 if self.clock() >= self.ends_at else None


class Timeline:
    """A clock the test moves: each `sleep` is one step of `step` seconds, and
    `events` maps a time to something that happens once it is reached."""

    def __init__(self, events=None, step=2.0, jumps=None):
        self.now, self.step = 0.0, step
        self.events = dict(events or {})
        self.jumps = dict(jumps or {})   # time -> seconds the machine slept

    def clock(self):
        return self.now

    def sleep(self, _):
        self.now += self.step
        for at in sorted(self.jumps):
            if self.now >= at:
                self.now += self.jumps.pop(at)
        for at in sorted(self.events):
            if self.now >= at:
                self.events.pop(at)()
        if self.now > 100000:
            raise AssertionError("never stopped")


def wait(server, process, timeline):
    if process is not None:
        process.clock = timeline.clock
    return app.wait_until_closed(server, process, sleep=timeline.sleep, clock=timeline.clock)


class Closing(unittest.TestCase):
    def test_closing_the_window_stops_the_kit(self):
        server, t = FakeServer(), Timeline()

        def speak():
            server.last_seen = t.now
        t.events = {10: speak, 20: speak, 30: speak}
        self.assertEqual(wait(server, FakeProcess(ends_at=34), t), "the window closed")
        # ...after the grace a handed-off window would have used to speak up
        self.assertAlmostEqual(t.now, 34 + app.HANDOFF_GRACE, delta=4)

    def test_a_window_handed_to_another_process_keeps_the_kit_alive(self):
        # the browser was already running: our process only passed the request
        # on and ended at once, but the page is open and goes on talking
        server, t = FakeServer(), Timeline()

        def speak():
            server.last_seen = t.now
        t.events = {at: speak for at in range(6, 400, 10)}
        self.assertEqual(wait(server, FakeProcess(ends_at=1), t), "the page went quiet")
        self.assertGreater(t.now, 396 + app.QUIET_LIMIT - 4)

    def test_a_browser_tab_is_known_only_by_its_silence(self):
        server, t = FakeServer(), Timeline()

        def speak():
            server.last_seen = t.now
        t.events = {10: speak, 20: speak}
        self.assertEqual(wait(server, None, t), "the page went quiet")
        self.assertAlmostEqual(t.now, 20 + app.QUIET_LIMIT, delta=4)

    def test_a_page_that_never_opens_is_given_up_on(self):
        t = Timeline()
        self.assertEqual(wait(FakeServer(), None, t), "the page never opened")
        self.assertAlmostEqual(t.now, app.FIRST_WORD_LIMIT, delta=4)

    def test_a_night_asleep_is_not_counted_as_silence(self):
        # the machine sleeps for eight hours with the kit open; on waking, the
        # page has said nothing for eight hours and must still be given time
        server, t = FakeServer(), Timeline(jumps={30: 8 * 3600})

        def speak():
            server.last_seen = t.now
        t.events = {10: speak, 20: speak, 8 * 3600 + 40: speak, 8 * 3600 + 50: speak}
        self.assertEqual(wait(server, None, t), "the page went quiet")
        self.assertAlmostEqual(t.now, 8 * 3600 + 50 + app.QUIET_LIMIT, delta=6)


class Restarting(unittest.TestCase):
    def test_an_update_that_is_ready_stops_the_wait_at_once(self):
        t = Timeline()
        server = FakeServer()
        server.last_seen = 0.0
        why = app.wait_until_closed(server, None, sleep=t.sleep, clock=t.clock,
                                    stopped=lambda: t.now >= 6)
        self.assertEqual(why, "the kit is restarting")
        self.assertLess(t.now, 10)


class Starting(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "web").mkdir()

    def kit(self, port=0):
        server = KitServer(Library(self.root / "data"), self.root / "web", port)
        server.serve_in_background()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_a_second_start_finds_the_kit_that_is_running(self):
        first = self.kit()
        self.assertTrue(app.running_kit(first.port))
        server, already = app.start_server(Library(self.root / "data2"), self.root / "web",
                                           [first.port])
        self.assertIsNone(server)
        self.assertEqual(already, first.url)

    def test_a_port_someone_else_holds_is_stepped_over(self):
        other = http.server.HTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        self.assertFalse(app.running_kit(other.server_address[1]))
        free = self.kit()
        free_port = free.port
        free.shutdown()
        free.server_close()
        server, already = app.start_server(Library(self.root / "data"), self.root / "web",
                                           [other.server_address[1], free_port])
        self.addCleanup(server.server_close)
        self.assertIsNone(already)
        self.assertEqual(server.port, free_port)

    def test_no_free_port_is_said_not_swallowed(self):
        other = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        self.addCleanup(other.server_close)
        with self.assertRaises(OSError):
            app.start_server(Library(self.root / "data"), self.root / "web",
                             [other.server_address[1]])


class NativeWindow(unittest.TestCase):
    def test_the_window_wears_the_kits_icon(self):
        icon = window.icon_path()
        self.assertIsNotNone(icon)
        self.assertEqual(icon.name, "icon.ico")
        # an .ico starts 00 00 01 00
        self.assertEqual(icon.read_bytes()[:4], b"\x00\x00\x01\x00")

    def test_the_browser_can_be_asked_for_instead(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"DEVKIT_WINDOW": "browser"}):
            self.assertFalse(window.native_window_available())
            # ...and nothing is shown: it says so and leaves it to the caller
            self.assertFalse(window.run_native_window("http://127.0.0.1:1/", "unused"))

    def test_a_machine_without_a_web_view_falls_back(self):
        # pywebview missing or broken is "no native window", never a crash
        import builtins
        from unittest import mock
        real = builtins.__import__

        def no_webview(name, *args, **kwargs):
            if name == "webview" or name.startswith("webview."):
                raise ImportError("no pywebview here")
            return real(name, *args, **kwargs)
        with mock.patch("builtins.__import__", no_webview):
            self.assertFalse(window.native_window_available())

    def test_with_no_kit_open_there_is_nothing_to_bring_forward(self):
        self.assertFalse(window.focus_existing_window())


class BrowserWindow(unittest.TestCase):
    def test_the_window_is_the_kits_own(self):
        command = window.app_window_command("browser.exe", "http://127.0.0.1:8791/", "C:\\data\\window")
        self.assertEqual(command[0], "browser.exe")
        self.assertIn("--app=http://127.0.0.1:8791/", command)
        # a profile of its own: nothing shared with the artist's browsing, and
        # a process that ends when the kit's window does
        self.assertIn("--user-data-dir=C:\\data\\window", command)
        self.assertIn("--no-first-run", command)
        self.assertIn("--disable-background-mode", command)

    def test_no_browser_is_an_answer_not_an_error(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"DEVKIT_BROWSER": "Z:\\no\\such\\browser.exe"}):
            self.assertIsNone(window.find_browser())
            self.assertIsNone(window.open_app_window("http://127.0.0.1:1/", "unused"))


class Paths(unittest.TestCase):
    def test_from_source_the_game_is_the_sibling_folder(self):
        tools = paths.tools_dir()
        self.assertEqual(tools.parts[-3:], ("App", "flutter", "tools"))
        self.assertTrue((tools / "vox_to_boxes.py").is_file())

    def test_the_data_folder_can_be_pinned(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {paths.DATA_ENV: "D:\\elsewhere"}):
            self.assertEqual(paths.data_dir(), Path("D:\\elsewhere"))
            self.assertEqual(paths.profile_dir(), Path("D:\\elsewhere") / "window")

    def test_from_source_the_files_are_in_the_checkout(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ):
            os.environ.pop(paths.DATA_ENV, None)
            self.assertEqual(paths.data_dir(), paths.source_root() / "_data")
            self.assertFalse(paths.installed())
            self.assertEqual(paths.legacy_data_dirs(), [])

    def test_installed_the_files_are_beside_the_program_and_the_cache_is_not(self):
        import os
        import sys
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve() / "PixelPomoDevKit"
            folder.mkdir()
            exe = folder / "PixelPomoDevKit.exe"
            exe.write_bytes(b"MZ")
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", str(exe)), \
                    mock.patch.object(sys, "platform", "win32"), \
                    mock.patch.dict(os.environ, {"LOCALAPPDATA": str(Path(tmp) / "local")}):
                os.environ.pop(paths.DATA_ENV, None)
                self.assertFalse(paths.installed())          # no marker: a download
                (folder / paths.MARKER).write_text("{}")
                self.assertTrue(paths.installed())
                self.assertEqual(paths.data_dir(), folder / "Files")
                # the web view's cache is the machine's business, not the artist's
                cache = paths.profile_dir()
                self.assertEqual(cache, Path(tmp) / "local" / "PixelPomoDevKit" / "window")
                self.assertNotIn(folder, cache.parents)
                # where v0.1.0 kept the files, to bring them over once
                self.assertEqual(paths.legacy_data_dirs(),
                                 [Path(tmp) / "local" / "PixelPomoDevKit"])

    def test_a_mac_program_is_the_app_not_the_binary_inside_it(self):
        import sys
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp).resolve() / "Kit" / "PixelPomoDevKit.app"
            binary = app_dir / "Contents" / "MacOS" / "PixelPomoDevKit"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"x")
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", str(binary)), \
                    mock.patch.object(sys, "platform", "darwin"):
                self.assertEqual(paths.program_path(), app_dir)
                self.assertEqual(paths.program_dir(), app_dir.parent)
                self.assertEqual(paths.legacy_data_dirs(), [])

    def test_a_kit_started_from_a_kit_does_not_inherit_its_unpack_folder(self):
        clean = paths.clean_environment({"PATH": "x", "_MEIPASS2": "C:\\t", "_PYI_ARCHIVE_FILE": "a",
                                         "DEVKIT_DATA": "kept"})
        self.assertEqual(clean, {"PATH": "x", "DEVKIT_DATA": "kept"})


if __name__ == "__main__":
    unittest.main()
