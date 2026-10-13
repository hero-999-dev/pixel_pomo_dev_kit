"""Setting the kit up: where it goes, what an install writes, and what a
download does when the kit is already installed."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

from dev_kit import app, installer, paths
from dev_kit.version import VERSION


class InstallCase(unittest.TestCase):
    """A machine made of temp folders: a download, a per-user folder, and
    somewhere to install."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.download = self.root / "Downloads" / "PixelPomoDevKit.exe"
        self.download.parent.mkdir()
        self.download.write_bytes(b"MZ the program, this build")
        self.user = self.root / "user"
        self.target = self.root / "C" / paths.NAME
        for patch in (
            mock.patch.object(paths, "per_user_dir", lambda: self.user),
            mock.patch.object(paths, "program_path", lambda: self.program),
            mock.patch.object(paths, "frozen", lambda: True),
            mock.patch.object(installer, "make_shortcut", self.shortcut),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop(paths.DATA_ENV, None)
        self.program = self.download      # what is "running"
        self.shortcuts = []

    def shortcut(self, program, folder=None):
        self.shortcuts.append(program)
        return program.with_suffix(".lnk")


class Where(InstallCase):
    def test_windows_is_offered_the_folder_programs_are_installed_in(self):
        def offered():
            return PureWindowsPath(str(installer.default_dir()))
        with mock.patch.object(sys, "platform", "win32"):
            # a 32-bit process is shown the x86 folder under the plain name
            with mock.patch.dict(os.environ, {"ProgramW6432": "C:\\Program Files",
                                              "ProgramFiles": "C:\\Program Files (x86)"}):
                self.assertEqual(offered(),
                                 PureWindowsPath("C:\\Program Files\\PixelPomoDevKit"))
            with mock.patch.dict(os.environ, {"SystemDrive": "D:"}):
                os.environ.pop("ProgramW6432", None)
                os.environ.pop("ProgramFiles", None)
                self.assertEqual(offered(),
                                 PureWindowsPath("D:\\Program Files\\PixelPomoDevKit"))

    def test_a_mac_is_offered_applications_never_documents(self):
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch.object(os, "access", lambda path, mode: True):
                self.assertEqual(installer.default_dir().as_posix(),
                                 "/Applications/PixelPomoDevKit")
            # not an admin: the user's own Applications, which is never asked about either
            with mock.patch.object(os, "access", lambda path, mode: False):
                offered = installer.default_dir()
                self.assertEqual(offered.parts[-2:], ("Applications", "PixelPomoDevKit"))
                self.assertNotIn("Documents", offered.parts)

    def test_the_kit_always_gets_a_folder_of_its_own(self):
        tools = self.root / "Tools"
        self.assertEqual(installer.target_for(tools), tools / "PixelPomoDevKit")
        # already named for it: used as it is, in any letter case
        self.assertEqual(installer.target_for(self.target), self.target)
        lower = self.root / "pixelpomodevkit"
        self.assertEqual(installer.target_for(lower), lower)
        self.assertEqual(installer.target_for(f'  "{tools}"  '), tools / "PixelPomoDevKit")

    def test_what_is_not_a_folder_to_install_in_is_refused(self):
        for bad in ("", "   ", "relative\\folder", "PixelPomoDevKit"):
            with self.assertRaises(installer.Refused, msg=bad):
                installer.target_for(bad)


class Installing(InstallCase):
    def test_an_install_is_the_program_a_marker_and_an_empty_files_folder(self):
        program = installer.install(self.target)
        self.assertEqual(program, self.target / "PixelPomoDevKit.exe")
        self.assertEqual(program.read_bytes(), self.download.read_bytes())
        self.assertTrue((self.target / paths.FILES).is_dir())
        marker = json.loads((self.target / paths.MARKER).read_text())
        self.assertEqual(marker["version"], VERSION)
        self.assertEqual(marker["build"], installer.fingerprint(self.download))
        # the download is left where it was
        self.assertTrue(self.download.is_file())
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ["Files", "PixelPomoDevKit.exe", "devkit-install.json"])

    def test_the_account_remembers_where(self):
        self.assertIsNone(installer.recorded())
        installer.install(self.target)
        self.assertEqual(installer.recorded(), self.target)
        # ...until the folder is gone
        (self.target / paths.MARKER).unlink()
        self.assertIsNone(installer.recorded())

    def test_windows_gets_a_desktop_shortcut_unless_it_is_declined(self):
        with mock.patch.object(sys, "platform", "win32"):
            program = installer.install(self.target)
            self.assertEqual(self.shortcuts, [program])
            installer.install(self.target, shortcut=False)
            self.assertEqual(self.shortcuts, [program])
        with mock.patch.object(sys, "platform", "darwin"):
            installer.install(self.target)
            self.assertEqual(self.shortcuts, [program])

    def test_installing_over_an_install_keeps_every_file_the_artist_added(self):
        installer.install(self.target)
        kept = self.target / paths.FILES / "library" / "x_rose" / "rose.png"
        kept.parent.mkdir(parents=True)
        kept.write_bytes(b"the artist's")
        (self.target / paths.FILES / "state.json").write_text("{}")
        self.download.write_bytes(b"MZ the program, a newer build")
        program = installer.install(self.target)
        self.assertEqual(program.read_bytes(), b"MZ the program, a newer build")
        self.assertEqual(kept.read_bytes(), b"the artist's")
        self.assertEqual((self.target / paths.FILES / "state.json").read_text(), "{}")
        self.assertEqual(json.loads((self.target / paths.MARKER).read_text())["build"],
                         installer.fingerprint(self.download))

    def test_a_folder_that_cannot_be_written_is_said_in_words(self):
        blocker = self.root / "afile"
        blocker.write_text("not a folder")
        with self.assertRaisesRegex(installer.Refused, "cannot write"):
            installer.install(blocker / paths.NAME)

    def test_a_kit_that_is_open_cannot_be_replaced_and_says_so(self):
        installer.install(self.target)
        with mock.patch.object(os, "replace", side_effect=PermissionError("in use")):
            with self.assertRaisesRegex(installer.Refused, "is open. Close it"):
                installer.install(self.target)
        # nothing half-copied is left beside the program
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ["Files", "PixelPomoDevKit.exe", "devkit-install.json"])

    def test_a_mac_app_is_copied_whole(self):
        app = self.root / "Downloads" / "PixelPomoDevKit.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        (app / "Contents" / "MacOS" / "PixelPomoDevKit").write_bytes(b"\xcf\xfa mach-o")
        (app / "Contents" / "Info.plist").write_text("<plist/>")
        self.program = app
        program = installer.install(self.target)
        self.assertEqual(program, self.target / "PixelPomoDevKit.app")
        self.assertEqual((program / "Contents" / "MacOS" / "PixelPomoDevKit").read_bytes(),
                         b"\xcf\xfa mach-o")
        # again, over itself: the old bundle is replaced, not merged into
        (app / "Contents" / "Info.plist").unlink()
        installer.install(self.target)
        self.assertFalse((program / "Contents" / "Info.plist").exists())
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ["Files", "PixelPomoDevKit.app", "devkit-install.json"])
        with self.assertRaisesRegex(installer.Refused, "inside the Dev Kit itself"):
            installer.install(app / "Contents" / paths.NAME)


class SystemFolders(InstallCase):
    """Installing where programs go on Windows: the folder is the system's,
    so it is made, and opened to the artist, by the program started again
    with permission. The copying is the setup's own."""

    def setUp(self):
        super().setUp()
        self.asked = []      # every command put to the permission question
        self.answer = "yes"
        for patch in (
            mock.patch.object(installer, "needs_admin", lambda target: True),
            mock.patch.object(installer, "_run_with_permission", self.permission),
            mock.patch.object(installer, "_setup_window", lambda: 4242),
            mock.patch.object(installer, "account_sid", lambda: "S-1-5-21-1-2-3-1001"),
            mock.patch.object(installer, "allow", self.allow),
            mock.patch.object(app, "_log_to", lambda folder, name: None),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.allowed = []

    def allow(self, folder, sid):
        self.allowed.append((Path(folder), sid))

    def permission(self, command, cwd=None, window=None):
        self.asked.append((command, window))
        if self.answer == "no":
            return None
        if self.answer == "nothing":
            return 1
        if self.answer == "never":
            raise TimeoutError
        # what the program does when it is started with that command
        return app.main(command[command.index(installer.OPEN_FLAG):])

    def test_the_program_is_started_again_only_to_make_and_open_the_folder(self):
        told = []
        program = installer.install(self.target,
                                    tell=lambda step, fraction=None: told.append(step))
        self.assertEqual(len(self.asked), 1)
        command, window = self.asked[0]
        flag = command.index(installer.OPEN_FLAG)
        self.assertEqual(command[flag + 1], str(self.target))
        self.assertEqual(command[command.index("--for") + 1], "S-1-5-21-1-2-3-1001")
        # the question is put for the setup window, so that it opens in front
        self.assertEqual(window, 4242)
        # the folder was opened to the artist's account, once
        self.assertEqual(self.allowed, [(self.target, "S-1-5-21-1-2-3-1001")])
        # and the kit was then put in it by the setup itself, after the question
        self.assertEqual(program, self.target / "PixelPomoDevKit.exe")
        self.assertEqual(program.read_bytes(), self.download.read_bytes())
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ["Files", "PixelPomoDevKit.exe", "devkit-install.json"])
        self.assertEqual(told[0], "permission")
        self.assertLess(told.index("permission"), told.index("copying"))
        self.assertEqual(installer.recorded(), self.target)
        # the note of how it went is not left lying in the temp folder
        report = command[command.index("--report") + 1]
        self.assertFalse(Path(report).exists())

    def test_the_permitted_half_copies_nothing_and_never_opens_the_kit(self):
        report = self.root / "report.json"
        with mock.patch.object(installer, "decide",
                               side_effect=AssertionError("it went on to the kit")):
            code = app.main([installer.OPEN_FLAG, str(self.target), "--for",
                             "S-1-5-21-1-2-3-1001", "--report", str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text()), {"ok": True})
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(self.allowed, [(self.target, "S-1-5-21-1-2-3-1001")])
        self.assertIsNone(installer.recorded())
        self.assertEqual(self.shortcuts, [])
        # a folder that cannot be made is reported, not raised
        blocker = self.root / "afile"
        blocker.write_text("not a folder")
        code = app.main([installer.OPEN_FLAG, str(blocker / "x"), "--report", str(report)])
        self.assertEqual(code, 1)
        self.assertIn("could not be made", json.loads(report.read_text())["error"])

    def test_the_shortcut_is_made_by_the_artist_not_by_the_permitted_half(self):
        with mock.patch.object(sys, "platform", "win32"):
            program = installer.install(self.target)
        self.assertEqual(self.shortcuts, [program])

    def test_no_to_the_question_installs_nothing_and_says_what_to_do(self):
        self.answer = "no"
        with self.assertRaisesRegex(installer.Refused, "the answer was no"):
            installer.install(self.target)
        self.assertFalse(self.target.exists())
        self.assertIsNone(installer.recorded())
        self.assertEqual(self.shortcuts, [])

    def test_what_went_wrong_with_permission_is_said_in_its_own_words(self):
        def refuse(folder, sid):
            raise installer.Refused("Windows would not open it to your account (no).")
        with mock.patch.object(installer, "allow", refuse):
            with self.assertRaisesRegex(installer.Refused, "would not open it"):
                installer.install(self.target)
        self.assertIsNone(installer.recorded())

    def test_a_permitted_half_that_says_nothing_is_a_failure(self):
        self.answer = "nothing"
        with self.assertRaisesRegex(installer.Refused, "did not finish"):
            installer.install(self.target)
        self.assertIsNone(installer.recorded())

    def test_a_permitted_half_that_never_ends_is_given_up_on(self):
        self.answer = "never"
        with self.assertRaisesRegex(installer.Refused, "was not ready after"),                 self.assertLogs("dev_kit", level="ERROR"):
            installer.install(self.target)
        self.assertIsNone(installer.recorded())

    def test_a_question_windows_cannot_ask_is_a_refusal_not_a_crash(self):
        with mock.patch.object(installer, "_run_with_permission",
                               side_effect=OSError(5, "Access is denied")):
            with self.assertRaisesRegex(installer.Refused, "could not ask"):
                installer.install(self.target)

    def test_a_folder_still_closed_to_the_artist_afterwards_is_refused(self):
        with mock.patch.object(installer, "_writable",
                               side_effect=installer.Refused("cannot write")):
            with self.assertRaisesRegex(installer.Refused, "cannot write"):
                installer.install(self.target)
        self.assertIsNone(installer.recorded())


class Progress(InstallCase):
    """The setup window is told how the install is going, and is never left
    waiting on one answer at the end."""

    def finished(self, api, limit=20.0):
        end = time.monotonic() + limit
        while time.monotonic() < end:
            state = api.progress()
            if not state.get("running"):
                return state
            time.sleep(0.01)
        self.fail(f"still installing after {limit} s: {api.progress()}")

    def test_before_anything_is_pressed_nothing_is_running(self):
        self.assertEqual(installer._SetupApi(None).progress(), {"running": False})

    def test_install_answers_at_once_and_progress_says_when_it_is_done(self):
        api = installer._SetupApi(None)
        self.assertEqual(api.install(str(self.root / "Tools"), True), {"started": True})
        state = self.finished(api)
        target = self.root / "Tools" / paths.NAME
        self.assertEqual((state["done"], state["fraction"], state["target"], state["files"]),
                         (True, 1.0, str(target), str(target / paths.FILES)))
        self.assertNotIn("error", state)
        self.assertEqual(api._program, target / "PixelPomoDevKit.exe")
        self.assertTrue(api._program.is_file())

    def test_each_step_is_shown_in_words_as_it_starts(self):
        gates = [threading.Event() for _ in range(4)]
        reached = [threading.Event() for _ in range(4)]

        def slow_install(target, shortcut=True, tell=None, **kw):
            for index, (step, fraction) in enumerate(
                    [("permission", None), ("copying", 0.5), ("finishing", None),
                     ("shortcut", None)]):
                tell(step, fraction)
                reached[index].set()
                gates[index].wait(10)
            return Path(target) / "PixelPomoDevKit.exe"

        api = installer._SetupApi(None)
        seen = []
        with mock.patch.object(installer, "install", slow_install):
            api.install(str(self.target), True)
            for index in range(4):
                self.assertTrue(reached[index].wait(10))
                seen.append(api.progress())
                gates[index].set()
            last = self.finished(api)
        self.assertEqual([s["step"] for s in seen],
                         ["permission", "copying", "finishing", "shortcut"])
        self.assertTrue(all(s["running"] for s in seen))
        # waiting on Windows cannot say how far it is, and says where to look
        self.assertTrue(seen[0]["busy"])
        self.assertIn("answer Yes", seen[0]["text"])
        self.assertIn("taskbar", seen[0]["hint"])
        # copying can: half of the file is half of copying's share of the bar
        self.assertFalse(seen[1]["busy"])
        self.assertEqual(seen[1]["hint"], "")
        self.assertAlmostEqual(seen[1]["fraction"], 0.10 + 0.75 * 0.5)
        # the bar only ever moves forward
        fractions = [s["fraction"] for s in seen] + [last["fraction"]]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(last["fraction"], 1.0)

    def test_a_refusal_is_shown_and_the_button_can_be_pressed_again(self):
        blocker = self.root / "afile"
        blocker.write_text("not a folder")
        api = installer._SetupApi(None)
        api.install(str(blocker), True)
        state = self.finished(api)
        self.assertIn("cannot write", state["error"])
        self.assertNotIn("done", state)
        self.assertIsNone(api._program)
        # the next try starts clean: no error left over from the last
        api.install(str(self.target), True)
        state = self.finished(api)
        self.assertNotIn("error", state)
        self.assertTrue(state["done"])

    def test_what_nobody_expected_is_still_an_answer(self):
        api = installer._SetupApi(None)
        with mock.patch.object(installer, "install", side_effect=RuntimeError("boom")), \
                self.assertLogs("dev_kit", level="ERROR"):
            api.install(str(self.target), True)
            state = self.finished(api)
        self.assertIn("did not finish: boom", state["error"])

    def test_a_folder_that_is_not_one_is_refused_before_anything_starts(self):
        api = installer._SetupApi(None)
        self.assertIn("Choose a folder", api.install("", True)["error"])
        self.assertEqual(api.progress(), {"running": False})

    def test_a_second_press_does_not_start_a_second_install(self):
        gate, started = threading.Event(), []

        def slow_install(target, shortcut=True, tell=None, **kw):
            started.append(target)
            gate.wait(10)
            return Path(target) / "PixelPomoDevKit.exe"

        api = installer._SetupApi(None)
        with mock.patch.object(installer, "install", slow_install):
            api.install(str(self.target), True)
            self.assertEqual(api.install(str(self.target), True), {"started": True})
            gate.set()
            self.finished(api)
        self.assertEqual(len(started), 1)

    def test_the_work_does_not_keep_the_program_alive(self):
        # closing the setup while Windows' question is unanswered must end it
        gate, threads = threading.Event(), []

        def slow_install(target, shortcut=True, tell=None, **kw):
            threads.append(threading.current_thread())
            gate.wait(10)
            return Path(target) / "PixelPomoDevKit.exe"

        api = installer._SetupApi(None)
        with mock.patch.object(installer, "install", slow_install):
            api.install(str(self.target), True)
            while not threads:
                time.sleep(0.01)
            self.assertTrue(threads[0].daemon)
            gate.set()
            self.finished(api)

    def test_the_copy_says_how_far_it_is(self):
        self.download.write_bytes(b"MZ" + b"\0" * (3 * (1 << 20) + 100))
        told = []
        installer.install(self.target, shortcut=False,
                          tell=lambda step, fraction=None: told.append((step, fraction)))
        copying = [fraction for step, fraction in told if step == "copying"]
        self.assertEqual((copying[0], copying[-1]), (0.0, 1.0))
        self.assertEqual(copying, sorted(copying))
        self.assertGreaterEqual(len(copying), 4)       # megabyte by megabyte
        self.assertEqual([step for step, _ in told if step != "copying"], ["finishing"])
        self.assertEqual((self.target / "PixelPomoDevKit.exe").read_bytes(),
                         self.download.read_bytes())

    def test_a_mac_app_is_counted_across_all_its_files(self):
        app_bundle = self.root / "Downloads" / "PixelPomoDevKit.app"
        (app_bundle / "Contents" / "MacOS").mkdir(parents=True)
        (app_bundle / "Contents" / "MacOS" / "PixelPomoDevKit").write_bytes(b"x" * 3000)
        (app_bundle / "Contents" / "Info.plist").write_bytes(b"y" * 1000)
        self.program = app_bundle
        told = []
        installer.install(self.target,
                          tell=lambda step, fraction=None: told.append((step, fraction)))
        copying = [fraction for step, fraction in told if step == "copying"]
        self.assertEqual(copying, sorted(copying))
        self.assertEqual(copying[-1], 1.0)
        self.assertIn(0.25, copying + [1 - c for c in copying])   # one file of the two

    def test_windows_is_told_about_the_shortcut_step(self):
        told = []
        with mock.patch.object(sys, "platform", "win32"):
            installer.install(self.target,
                              tell=lambda step, fraction=None: told.append(step))
        self.assertEqual(told[-1], "shortcut")
        self.assertEqual(set(told) - set(installer._STEPS), set())

    def test_every_step_has_words_and_a_place_on_the_bar(self):
        last = 0.0
        for step in ("permission", "copying", "finishing", "shortcut"):
            text, hint, start, end = installer._STEPS[step]
            self.assertTrue(text)
            self.assertLessEqual(last, start)
            self.assertLessEqual(start, end)
            self.assertLess(end, 1.0)
            last = end


class Permission(InstallCase):
    def test_only_windows_has_folders_that_need_the_question(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertFalse(installer.needs_admin("/Applications/PixelPomoDevKit"))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows permissions")
    def test_a_folder_is_asked_about_by_trying_the_nearest_one_that_exists(self):
        deep = self.root / "not" / "there" / "yet"
        self.assertFalse(installer.needs_admin(deep))
        self.assertFalse((self.root / "not").exists())      # looking makes nothing
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".")],
                         [])                                # and leaves nothing
        tried = []

        def closed(path, flags, *more):
            tried.append(Path(path).parent)
            raise PermissionError(13, "Access is denied")
        with mock.patch.object(installer.os, "open", closed):
            self.assertTrue(installer.needs_admin(deep))
        self.assertEqual(tried, [self.root])                # once, not again and again
        # a drive that is not there is not a question of permission
        with mock.patch.object(installer.os, "open",
                               side_effect=FileNotFoundError(2, "gone")):
            self.assertFalse(installer.needs_admin(deep))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows permissions")
    def test_a_folder_windows_really_closes_is_answered_and_at_once(self):
        # Not a stand-in: a folder this account is denied by Windows itself,
        # as Program Files is. The answer has to come, and soon - v0.1.2's
        # never did, on the Python the release is built with.
        import subprocess
        closed = self.root / "closed"
        closed.mkdir()
        sid = installer.account_sid()
        denied = subprocess.run(["icacls", str(closed), "/deny", f"*{sid}:(WD,AD)"],
                                capture_output=True, text=True)
        self.assertEqual(denied.returncode, 0, denied.stdout + denied.stderr)
        self.addCleanup(subprocess.run, ["icacls", str(closed), "/remove:d", f"*{sid}"],
                        capture_output=True)
        answers = []
        asking = threading.Thread(
            target=lambda: answers.append(installer.needs_admin(closed / paths.NAME)),
            daemon=True)
        started = time.monotonic()
        asking.start()
        asking.join(15)
        self.assertFalse(asking.is_alive(), "needs_admin is still trying after 15 s")
        self.assertEqual(answers, [True])
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(list(closed.iterdir()), [])
        # and the same folder, opened again, is no longer a question
        subprocess.run(["icacls", str(closed), "/remove:d", f"*{sid}"], capture_output=True)
        self.assertFalse(installer.needs_admin(closed / paths.NAME))
        self.assertEqual(list(closed.iterdir()), [])

    def test_nothing_here_hands_a_closed_folder_to_tempfile(self):
        # see needs_admin: tempfile retries "access denied" without end
        import inspect
        source = inspect.getsource(installer)
        for call in ("TemporaryFile(", "mkstemp(", "mkdtemp(", "TemporaryDirectory("):
            self.assertNotIn("tempfile." + call, source)

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows permissions")
    def test_this_account_has_a_name_windows_knows_it_by(self):
        self.assertRegex(installer.account_sid(), r"^S-1-5-21(-\d+)+$")

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows permissions")
    def test_a_folder_is_really_opened_to_an_account(self):
        import subprocess
        self.target.mkdir(parents=True)
        installer.allow(self.target, installer.account_sid())
        listed = subprocess.run(["icacls", str(self.target)], capture_output=True,
                                text=True).stdout
        self.assertIn("(OI)(CI)(M)", listed)

    def test_an_account_with_no_name_falls_back_to_the_users_group(self):
        ran = []

        def run(command, **kw):
            ran.append(command)
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(installer.subprocess, "run", run):
            installer.allow(self.target, "")
            installer.allow(self.target, "everyone; & calc")
        self.assertEqual([c[-1] for c in ran], ["*S-1-5-32-545:(OI)(CI)M"] * 2)

    def test_a_grant_windows_refuses_is_a_refusal(self):
        with mock.patch.object(installer.subprocess, "run",
                               lambda command, **kw: mock.Mock(
                                   returncode=5, stdout="", stderr="Access is denied.")):
            with self.assertRaisesRegex(installer.Refused, "Access is denied"):
                installer.allow(self.target, "S-1-5-21-1-2-3-1001")


class Deciding(InstallCase):
    def run_installed(self):
        """Pretend the installed copy is what is running."""
        self.program = self.target / "PixelPomoDevKit.exe"

    def test_from_source_the_kit_just_runs(self):
        with mock.patch.object(paths, "frozen", lambda: False):
            self.assertEqual(installer.decide(), ("run", None))

    def test_a_pinned_data_folder_means_no_install_is_asked(self):
        with mock.patch.dict(os.environ, {paths.DATA_ENV: str(self.root / "pinned")}):
            self.assertEqual(installer.decide(), ("run", None))

    def test_a_first_download_asks_where_to_install(self):
        self.assertEqual(installer.decide(), ("setup", None))

    def test_the_installed_copy_runs(self):
        installer.install(self.target)
        self.run_installed()
        self.assertTrue(paths.installed())
        self.assertEqual(installer.decide(), ("run", None))
        self.assertEqual(paths.data_dir(), self.target / paths.FILES)

    def test_the_same_download_started_again_opens_the_installed_kit(self):
        program = installer.install(self.target)
        self.assertEqual(installer.decide(), ("open", program))

    def test_a_newer_download_offers_to_update_the_install(self):
        installer.install(self.target)
        marker = self.target / paths.MARKER
        marker.write_text(json.dumps({**json.loads(marker.read_text()), "version": "0.0.9"}))
        self.assertEqual(installer.decide(), ("setup", self.target))

    def test_another_build_of_the_same_version_offers_to_replace_it(self):
        installer.install(self.target)
        self.download.write_bytes(b"MZ the same version, built again")
        self.assertEqual(installer.decide(), ("setup", self.target))

    def test_an_older_download_opens_the_newer_kit_that_is_installed(self):
        program = installer.install(self.target)
        marker = self.target / paths.MARKER
        marker.write_text(json.dumps({**json.loads(marker.read_text()), "version": "99.0.0"}))
        self.download.write_bytes(b"MZ something older")
        self.assertEqual(installer.decide(), ("open", program))

    def test_after_an_update_the_install_says_which_version_it_now_is(self):
        # the updater swaps the program and leaves the marker as it was
        installer.install(self.target)
        marker = self.target / paths.MARKER
        installed = json.loads(marker.read_text())
        marker.write_text(json.dumps({**installed, "version": "0.0.9", "build": "old"}))
        self.run_installed()
        self.assertTrue(installer.refresh_marker())
        now = json.loads(marker.read_text())
        self.assertEqual((now["version"], now["build"], now["installed"]),
                         (VERSION, installer.fingerprint(self.program), installed["installed"]))
        # ...so the same version, downloaded again, opens the kit instead of
        # offering to "update" it
        self.program = self.download
        self.assertEqual(installer.decide(), ("open", self.target / "PixelPomoDevKit.exe"))
        # and a start with nothing to say changes nothing
        self.run_installed()
        self.assertFalse(installer.refresh_marker())

    def test_a_download_has_no_marker_to_refresh(self):
        self.assertFalse(installer.refresh_marker())

    def test_an_install_whose_program_is_gone_is_set_up_again(self):
        program = installer.install(self.target)
        program.unlink()
        self.assertEqual(installer.decide(), ("setup", self.target))


class SetupWindow(InstallCase):
    def test_the_page_is_told_what_it_needs_to_ask(self):
        api = installer._SetupApi(None)
        with mock.patch.object(installer, "default_dir", lambda: self.target):
            facts = api.facts()
        self.assertEqual((facts["version"], facts["folder"], facts["existing"]),
                         (VERSION, str(self.target), ""))

    def test_what_is_typed_is_answered_with_where_the_kit_would_go(self):
        api = installer._SetupApi(None)
        tools = self.root / "Tools"
        answer = api.resolve(str(tools))
        self.assertEqual(answer, {"target": str(tools / paths.NAME),
                                  "files": str(tools / paths.NAME / paths.FILES),
                                  "update": False, "admin": False})
        with mock.patch.object(installer, "needs_admin", lambda target: True):
            self.assertTrue(api.resolve(str(tools))["admin"])
        self.assertIn("error", api.resolve("not\\a\\full\\path"))
        installer.install(self.target)
        self.assertTrue(api.resolve(str(self.target))["update"])

    def test_an_update_is_introduced_as_one(self):
        installer.install(self.target)
        facts = installer._SetupApi(self.target).facts()
        self.assertEqual((facts["existing"], facts["existingVersion"], facts["folder"]),
                         (str(self.target), VERSION, str(self.target)))

    def test_the_page_carries_the_logo_and_no_outside_address(self):
        page = installer.setup_page()
        self.assertIn("data:image/png;base64,", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertIn("pywebviewready", page)

    def test_the_page_has_a_bar_and_asks_how_far_the_install_is(self):
        page = installer.setup_page()
        self.assertIn('role="progressbar"', page)
        self.assertIn("api.progress()", page)
        # the outcome comes from there too, not from install's own answer
        self.assertIn("p.target", page)

    def test_only_the_asking_is_offered_to_the_page(self):
        # pywebview hands the page every public method of the object
        public = sorted(n for n in dir(installer._SetupApi) if not n.startswith("_"))
        self.assertEqual(public, ["browse", "close", "facts", "install", "progress",
                                  "resolve"])


@unittest.skipUnless(sys.platform.startswith("win"), "Windows shortcuts")
class Shortcut(unittest.TestCase):
    def test_a_real_shortcut_points_at_the_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / "PixelPomoDevKit.exe"
            program.write_bytes(b"MZ")
            made = installer.make_shortcut(program, folder=tmp)
            self.assertIsNotNone(made)
            self.assertEqual(made.name, "Pixel Pomo Dev Kit.lnk")
            # a .lnk stores its target's path as UTF-16 somewhere inside
            raw = made.read_bytes()
            self.assertTrue(str(program).encode("utf-16-le") in raw
                            or str(program).encode("mbcs") in raw)


if __name__ == "__main__":
    unittest.main()
