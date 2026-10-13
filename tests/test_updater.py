"""Updates: asking, downloading, and swapping the program without touching the
artist's files."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

from dev_kit import paths, updater
from dev_kit.version import VERSION, parse


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def release(tag, *assets):
    return {"tag_name": tag, "html_url": f"https://example.test/{tag}", "body": "notes",
            "assets": [{"name": name, "browser_download_url": f"https://example.test/{name}"}
                       for name in assets]}


def opener_for(data):
    seen = []

    def opener(req, timeout):
        seen.append(req)
        return FakeResponse(data if isinstance(data, bytes) else json.dumps(data).encode())
    opener.seen = seen
    return opener


class Versions(unittest.TestCase):
    def test_versions_compare_as_numbers(self):
        self.assertEqual(parse("v0.1.1"), (0, 1, 1))
        self.assertGreater(parse("0.10.0"), parse("0.9.9"))
        self.assertEqual(parse("1.2.0-rc1"), (1, 2, 0))
        self.assertEqual(parse("nonsense"), (0,))


class Checking(unittest.TestCase):
    def test_a_newer_release_is_newer_and_the_same_one_is_not(self):
        newer = updater.check(opener=opener_for(release("v99.0.0", "a.zip")))
        self.assertTrue(newer.is_newer)
        self.assertEqual(newer.assets, {"a.zip": "https://example.test/a.zip"})
        self.assertFalse(updater.check(opener=opener_for(release("v" + VERSION))).is_newer)
        self.assertFalse(updater.check(opener=opener_for(release("v0.0.1"))).is_newer)

    def test_it_asks_the_kits_own_repository_unless_pointed_elsewhere(self):
        opener = opener_for(release("v1.0.0"))
        updater.check(opener=opener)
        self.assertEqual(opener.seen[0].full_url,
                         "https://api.github.com/repos/hero-999-dev/pixel_pomo_dev_kit"
                         "/releases/latest")
        with mock.patch.dict(os.environ, {updater.API_ENV: "http://127.0.0.1:9/latest"}):
            updater.check(opener=opener)
        self.assertEqual(opener.seen[1].full_url, "http://127.0.0.1:9/latest")

    def test_an_answer_that_is_not_a_release_is_an_error(self):
        with self.assertRaises(ValueError):
            updater.check(opener=opener_for([1, 2, 3]))

    def test_each_machine_asks_for_its_own_download(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(updater.asset_name(), "PixelPomoDevKit-windows.zip")
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch("platform.machine", lambda: "arm64"):
                self.assertEqual(updater.asset_name(), "PixelPomoDevKit-macos-apple-silicon.zip")
            with mock.patch("platform.machine", lambda: "x86_64"):
                self.assertEqual(updater.asset_name(), "PixelPomoDevKit-macos-intel.zip")
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIsNone(updater.asset_name())


class Downloading(unittest.TestCase):
    def test_a_download_lands_whole_and_reports_its_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            steps = []
            dest = updater.download("https://example.test/a.zip", Path(tmp) / "sub" / "a.zip",
                                    progress=lambda done, total: steps.append((done, total)),
                                    opener=opener_for(b"x" * 1000))
            self.assertEqual(dest.read_bytes(), b"x" * 1000)
            self.assertEqual(steps[-1], (1000, 1000))
            self.assertEqual([p.name for p in dest.parent.iterdir()], ["a.zip"])

    def test_an_interrupted_download_leaves_no_zip_under_the_real_name(self):
        class Breaks(FakeResponse):
            def read(self, n=-1):
                raise OSError("the line dropped")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.zip"
            with self.assertRaises(OSError):
                updater.download("https://example.test/a.zip", dest,
                                 opener=lambda req, timeout: Breaks(b"abc"))
            self.assertFalse(dest.exists())


def program_zip(path, name="PixelPomoDevKit.exe", data=b"MZ new program"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name, data)
        zf.writestr("READ-ME-FIRST.txt", "hello")
    return path


class Staging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.install = Path(self._tmp.name) / "Pixel Pomo Kit"   # a space, on purpose
        self.files = self.install / "Files"
        self.files.mkdir(parents=True)
        self.program = self.install / "PixelPomoDevKit.exe"
        self.program.write_bytes(b"MZ old program")
        self.keep = self.files / "updates"

    def test_the_new_program_waits_beside_the_old_and_the_script_is_out_of_sight(self):
        script = updater.stage(program_zip(self.install / "u.zip"), self.program, self.keep,
                               pid=4242, old_version="0.1.1")
        self.assertEqual(script, self.keep / "update.cmd")
        self.assertEqual((self.install / "PixelPomoDevKit.new.exe").read_bytes(),
                         b"MZ new program")
        self.assertEqual(self.program.read_bytes(), b"MZ old program")   # not yet swapped
        text = script.read_text()
        self.assertIn("set PID=4242", text)
        # the old program is kept for a way back - in Files/updates, not beside the new one
        self.assertIn(str(self.keep / "PixelPomoDevKit-0.1.1.exe"), text)
        self.assertNotIn(".old.exe", text)
        # the new kit must not inherit the old one's unpack folder
        self.assertIn("set _MEI", text)
        self.assertIn("set _PYI", text)

    def test_a_zip_without_the_program_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no PixelPomoDevKit.exe"):
            updater.stage(program_zip(self.install / "u.zip", name="other.exe"),
                          self.program, self.keep)
        self.assertFalse((self.install / "PixelPomoDevKit.new.exe").exists())

    @unittest.skipUnless(sys.platform.startswith("win"), "the Windows hand-off")
    def test_the_hand_off_really_swaps_the_program_and_keeps_the_files(self):
        """Run the real script against a stand-in program: a .cmd named .exe
        cannot be started, so the "program" here is checked by its bytes and
        the relaunch line is taken out."""
        artists = self.files / "library" / "x_rose" / "rose.png"
        artists.parent.mkdir(parents=True)
        artists.write_bytes(b"the artist's file")
        (self.keep).mkdir()
        (self.keep / "PixelPomoDevKit-0.0.9.exe").write_bytes(b"an older way back")
        waited_for = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
        script = updater.stage(program_zip(self.install / "u.zip"), self.program, self.keep,
                               pid=waited_for.pid, old_version="0.1.1")
        text = script.read_text()
        script.write_text("\r\n".join(line for line in text.split("\r\n")
                                      if not line.startswith('start ""')))
        started = time.monotonic()
        done = subprocess.run(["cmd.exe", "/c", str(script)], capture_output=True,
                              timeout=60, env=paths.clean_environment())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertGreater(time.monotonic() - started, 3)       # it waited for the kit to go
        waited_for.wait()
        self.assertEqual(self.program.read_bytes(), b"MZ new program")
        self.assertEqual(sorted(p.name for p in self.install.iterdir()),
                         ["Files", "PixelPomoDevKit.exe", "u.zip"])   # ONE program
        # one way back, the latest; the script cleaned itself up
        self.assertEqual(sorted(p.name for p in self.keep.iterdir()),
                         ["PixelPomoDevKit-0.1.1.exe"])
        self.assertEqual((self.keep / "PixelPomoDevKit-0.1.1.exe").read_bytes(),
                         b"MZ old program")
        self.assertEqual(artists.read_bytes(), b"the artist's file")

    def test_a_mac_swaps_the_app_and_clears_any_quarantine(self):
        from pathlib import PurePosixPath as Mac
        keep = Mac("/Applications/PixelPomoDevKit/Files/updates")
        script_text = updater._mac_handoff(
            Mac("/Applications/PixelPomoDevKit/PixelPomoDevKit.app"),
            keep / "new" / "PixelPomoDevKit.app",
            keep / "PixelPomoDevKit-0.1.1.app", keep / "new", 77)
        lines = script_text.splitlines()
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertIn("kill -0 77", lines[1])
        self.assertTrue(any(line.startswith("xattr -dr com.apple.quarantine") for line in lines))
        self.assertTrue(any(line.startswith("open '") for line in lines))
        # a folder with a space or a quote in its name is still one argument
        quoted = updater._mac_handoff(Mac("/Apps/It's Mine/K.app"), Mac("/n/K.app"),
                                      Mac("/k/K-1.app"), Mac("/n"), 1)
        self.assertIn("'/Apps/It'\\''s Mine/K.app'", quoted)


class TheButton(unittest.TestCase):
    """`Updates` is what the page's UPDATE button talks to."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.install = Path(self._tmp.name)
        self.program = self.install / "PixelPomoDevKit.exe"
        self.program.write_bytes(b"MZ old")
        self.data = self.install / "Files"
        self.data.mkdir()
        self.ready = []
        for patch in (mock.patch.object(paths, "program_path", lambda: self.program),
                      mock.patch.object(updater, "can_self_update", lambda: self.can),
                      mock.patch.object(sys, "platform", "win32")):
            patch.start()
            self.addCleanup(patch.stop)
        self.can = True

    def updates(self, found, download=None):
        def check():
            if isinstance(found, Exception):
                raise found
            return updater.Release(found)
        return updater.Updates(self.data, on_ready=self.ready.append, check=check,
                               download=download or self.fake_download)

    def fake_download(self, url, dest, progress=None):
        progress(50, 100)
        dest.parent.mkdir(parents=True, exist_ok=True)
        return program_zip(dest)

    def wait_for(self, updates, *states):
        deadline = time.monotonic() + 10
        while updates.status()["state"] not in states:
            self.assertLess(time.monotonic(), deadline, updates.status())
            time.sleep(0.02)
        return updates.status()

    def test_nothing_newer(self):
        updates = self.updates(release("v" + VERSION))
        self.assertEqual(updates.status()["state"], "idle")
        status = updates.check()
        self.assertEqual((status["state"], status["latest"]), ("none", VERSION))
        with self.assertRaises(ValueError):
            updates.apply()

    def test_a_newer_version_is_downloaded_staged_and_handed_over(self):
        updates = self.updates(release("v99.0.0", "PixelPomoDevKit-windows.zip"))
        status = updates.check()
        self.assertEqual((status["state"], status["latest"], status["notes"]),
                         ("available", "99.0.0", "notes"))
        updates.apply()
        self.assertEqual(self.wait_for(updates, "ready", "failed")["state"], "ready")
        self.assertEqual(self.ready, [self.data / "updates" / "update.cmd"])
        self.assertTrue((self.install / "PixelPomoDevKit.new.exe").is_file())
        # the zip is not left lying in the artist's folder
        self.assertEqual(sorted(p.name for p in (self.data / "updates").iterdir()),
                         ["update.cmd"])

    def test_no_release_yet_is_said_plainly(self):
        gone = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b""))
        self.addCleanup(gone.close)
        status = self.updates(gone).check()
        self.assertEqual((status["state"], status["message"]),
                         ("failed", "No version of the Dev Kit has been published yet."))

    def test_being_offline_is_said_plainly(self):
        status = self.updates(urllib.error.URLError("no route")).check()
        self.assertEqual(status["state"], "failed")
        self.assertIn("could not be reached", status["message"])

    def test_a_release_without_this_machines_download_says_where_it_is(self):
        updates = self.updates(release("v99.0.0", "PixelPomoDevKit-macos-intel.zip"))
        updates.check()
        with self.assertRaisesRegex(ValueError, "no download for this machine"):
            updates.apply()

    def test_a_kit_that_is_not_installed_does_not_swap_itself(self):
        self.can = False
        updates = self.updates(release("v99.0.0", "PixelPomoDevKit-windows.zip"))
        updates.check()
        with self.assertRaisesRegex(ValueError, "Only the installed Dev Kit"):
            updates.apply()
        self.assertEqual(self.ready, [])

    def test_a_failed_download_is_an_answer_and_nothing_is_swapped(self):
        def broken(url, dest, progress=None):
            raise OSError("the line dropped")
        updates = self.updates(release("v99.0.0", "PixelPomoDevKit-windows.zip"), broken)
        updates.check()
        with self.assertLogs("dev_kit", level="ERROR"):
            updates.apply()
            status = self.wait_for(updates, "ready", "failed")
        self.assertEqual(status["state"], "failed")
        self.assertIn("the line dropped", status["message"])
        self.assertEqual(self.ready, [])
        self.assertEqual(self.program.read_bytes(), b"MZ old")


if __name__ == "__main__":
    unittest.main()
