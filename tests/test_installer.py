"""Setting the kit up: where it goes, what an install writes, and what a
download does when the kit is already installed."""
import json
import os
import sys
import tempfile
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
    so the copy is done by the program started again with permission."""

    def setUp(self):
        super().setUp()
        self.asked = []      # every command put to the permission question
        self.answer = "yes"
        for patch in (
            mock.patch.object(installer, "needs_admin", lambda target: True),
            mock.patch.object(installer, "_run_with_permission", self.permission),
            mock.patch.object(installer, "account_sid", lambda: "S-1-5-21-1-2-3-1001"),
            mock.patch.object(installer, "allow", self.allow),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.allowed = []

    def allow(self, folder, sid):
        self.allowed.append((Path(folder), sid))

    def permission(self, command, cwd=None):
        self.asked.append(command)
        if self.answer == "no":
            return None
        if self.answer == "nothing":
            return 1
        # what the program does when it is started with that command
        return app.main(command[command.index(installer.PLACE_FLAG):])

    def test_the_program_is_started_again_to_place_the_kit(self):
        with mock.patch.object(app, "_log_to", lambda folder, name: None):
            program = installer.install(self.target)
        self.assertEqual(len(self.asked), 1)
        command = self.asked[0]
        flag = command.index(installer.PLACE_FLAG)
        self.assertEqual(command[flag + 1], str(self.target))
        self.assertEqual(command[command.index("--source") + 1], str(self.download))
        self.assertEqual(command[command.index("--for") + 1], "S-1-5-21-1-2-3-1001")
        # the kit is there, and its folder was opened to the artist's account
        self.assertEqual(program, self.target / "PixelPomoDevKit.exe")
        self.assertEqual(program.read_bytes(), self.download.read_bytes())
        self.assertEqual(self.allowed, [(self.target, "S-1-5-21-1-2-3-1001")])
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ["Files", "PixelPomoDevKit.exe", "devkit-install.json"])
        # what is the artist's own was done as the artist, afterwards
        self.assertEqual(installer.recorded(), self.target)
        # the note of how it went is not left lying in the temp folder
        report = command[command.index("--report") + 1]
        self.assertFalse(Path(report).exists())

    def test_the_shortcut_is_made_by_the_artist_not_by_the_permitted_half(self):
        with mock.patch.object(app, "_log_to", lambda folder, name: None), \
                mock.patch.object(sys, "platform", "win32"):
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
        installer.place(self.target)
        with mock.patch.object(app, "_log_to", lambda folder, name: None), \
                mock.patch.object(os, "replace", side_effect=PermissionError("in use")):
            with self.assertRaisesRegex(installer.Refused, "is open. Close it"):
                installer.install(self.target)

    def test_a_permitted_half_that_says_nothing_is_a_failure(self):
        self.answer = "nothing"
        with self.assertRaisesRegex(installer.Refused, "did not finish"):
            installer.install(self.target)
        self.assertIsNone(installer.recorded())

    def test_a_question_windows_cannot_ask_is_a_refusal_not_a_crash(self):
        with mock.patch.object(installer, "_run_with_permission",
                               side_effect=OSError(5, "Access is denied")):
            with self.assertRaisesRegex(installer.Refused, "could not ask"):
                installer.install(self.target)

    def test_a_folder_still_closed_to_the_artist_afterwards_is_refused(self):
        with mock.patch.object(app, "_log_to", lambda folder, name: None), \
                mock.patch.object(installer, "_writable",
                                  side_effect=[None, installer.Refused("cannot write")]):
            with self.assertRaisesRegex(installer.Refused, "cannot write"):
                installer.install(self.target)

    def test_the_page_installs_through_the_same_question(self):
        self.answer = "no"
        refused = installer._SetupApi(None).install(str(self.target), True)
        self.assertIn("the answer was no", refused["error"])


class Permission(InstallCase):
    def test_only_windows_has_folders_that_need_the_question(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertFalse(installer.needs_admin("/Applications/PixelPomoDevKit"))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows permissions")
    def test_a_folder_is_asked_about_by_trying_the_nearest_one_that_exists(self):
        deep = self.root / "not" / "there" / "yet"
        self.assertFalse(installer.needs_admin(deep))
        self.assertFalse((self.root / "not").exists())      # looking makes nothing
        self.assertEqual(list(self.root.glob("tmp*")), [])  # and leaves nothing
        tried = []

        def closed(dir=None, **kw):
            tried.append(Path(dir))
            raise PermissionError(13, "Access is denied")
        with mock.patch.object(installer.tempfile, "TemporaryFile", closed):
            self.assertTrue(installer.needs_admin(deep))
        self.assertEqual(tried, [self.root])
        # a drive that is not there is not a question of permission
        with mock.patch.object(installer.tempfile, "TemporaryFile",
                               side_effect=FileNotFoundError(2, "gone")):
            self.assertFalse(installer.needs_admin(deep))

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

    def test_the_permitted_half_reports_and_never_opens_the_kit(self):
        report = self.root / "report.json"
        with mock.patch.object(installer, "allow", lambda folder, sid: None), \
                mock.patch.object(app, "_log_to", lambda folder, name: None), \
                mock.patch.object(installer, "decide",
                                  side_effect=AssertionError("it went on to the kit")):
            code = app.main([installer.PLACE_FLAG, str(self.target), "--source",
                             str(self.download), "--report", str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text()), {"ok": True})
        self.assertTrue((self.target / "PixelPomoDevKit.exe").is_file())
        # the artist's own things are not its business
        self.assertIsNone(installer.recorded())
        self.assertEqual(self.shortcuts, [])
        blocker = self.root / "afile"
        blocker.write_text("not a folder")
        with mock.patch.object(app, "_log_to", lambda folder, name: None):
            code = app.main([installer.PLACE_FLAG, str(blocker / "x"), "--source",
                             str(self.download), "--report", str(report)])
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(report.read_text()))


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

    def test_install_from_the_page(self):
        api = installer._SetupApi(None)
        answer = api.install(str(self.root / "Tools"), True)
        self.assertEqual(answer["ok"], True)
        self.assertEqual(api._program, self.root / "Tools" / paths.NAME / "PixelPomoDevKit.exe")
        self.assertTrue(api._program.is_file())
        refused = installer._SetupApi(None).install("", True)
        self.assertIn("Choose a folder", refused["error"])

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

    def test_only_the_asking_is_offered_to_the_page(self):
        # pywebview hands the page every public method of the object
        public = sorted(n for n in dir(installer._SetupApi) if not n.startswith("_"))
        self.assertEqual(public, ["browse", "close", "facts", "install", "resolve"])


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
