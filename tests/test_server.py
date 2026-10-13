"""The launcher's server, asked the way the page asks it."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from dev_kit.library import Library
from dev_kit.server import APP, KitServer
from dev_kit.version import VERSION
from tests.test_library import block, png, vox


class ServerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.web = root / "web"
        (self.web / "assets").mkdir(parents=True)
        (self.web / "index.html").write_text("<title>kit</title>")
        (self.web / "main.dart.js").write_text("void 0")
        (self.web / "assets" / "a.wasm").write_bytes(b"\0asm")
        (root / "secret.txt").write_text("not for the page")
        self.opened = []
        self.server = KitServer(Library(root / "data"), self.web,
                                on_open_folder=lambda folder: self.opened.append(folder) or True)
        self.server.serve_in_background()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, method, path, body=None, headers=None):
        """-> (status, content type, body)."""
        request = urllib.request.Request(self.server.url.rstrip("/") + path, data=body,
                                         method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get("Content-Type"), e.read()

    def json(self, method, path, body=None, headers=None):
        status, _, raw = self.ask(method, path, body, headers)
        return status, json.loads(raw)


class Page(ServerCase):
    def test_the_page_and_its_files_are_served_with_their_types(self):
        self.assertEqual(self.ask("GET", "/")[:2], (200, "text/html; charset=utf-8"))
        self.assertEqual(self.ask("GET", "/main.dart.js")[1], "text/javascript; charset=utf-8")
        # a browser will not compile wasm served as anything else
        self.assertEqual(self.ask("GET", "/assets/a.wasm")[1], "application/wasm")
        self.assertEqual(self.ask("GET", "/nothing.js")[0], 404)

    def test_nothing_outside_the_page_is_served(self):
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt",
                     "/..%5csecret.txt"):
            self.assertEqual(self.ask("GET", path)[0], 404, path)

    def test_the_page_is_never_cached(self):
        request = urllib.request.Request(self.server.url)
        with urllib.request.urlopen(request, timeout=10) as r:
            self.assertEqual(r.headers.get("Cache-Control"), "no-store")

    def test_hello_says_who_is_answering_and_notes_the_page_is_open(self):
        self.assertIsNone(self.server.last_seen)
        status, body = self.json("GET", "/api/hello")
        self.assertEqual((status, body["app"], body["version"]), (200, APP, VERSION))
        self.assertTrue(body["dataDir"].endswith("data"))
        # for the panel behind the version number: where the kit is, what kind
        # of start this is, and whether there is anything in the trash
        self.assertEqual((body["build"], body["trash"]), ("source", 0))
        self.assertTrue(Path(body["programDir"]).is_dir())
        self.assertIsNotNone(self.server.last_seen)


class Strangers(ServerCase):
    def test_another_sites_script_cannot_touch_the_library(self):
        status, body = self.json("POST", "/api/import/sprite?name=x", png(16, 16),
                                 {"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.server.library.items(), [])
        self.assertEqual(self.json("POST", "/api/trash/x_rose", None,
                                   {"Origin": "null"})[0], 403)
        self.assertEqual(self.json("DELETE", "/api/trash", None,
                                   {"Origin": "http://evil.example"})[0], 403)

    def test_a_foreign_name_pointed_here_is_turned_away(self):
        self.assertEqual(self.ask("GET", "/api/library", None,
                                  {"Host": "evil.example"})[0], 403)

    def test_the_kits_own_page_is_let_in(self):
        origin = f"http://127.0.0.1:{self.server.port}"
        self.assertEqual(self.json("POST", "/api/import/sprite?name=x", png(16, 16),
                                   {"Origin": origin})[0], 200)


class Imports(ServerCase):
    def test_a_sprite_goes_in_and_comes_back(self):
        data = png(256, 304)
        status, item = self.json(
            "POST", "/api/import/sprite?file=flower%20x%200.png&name=Blue%20Rose&kind=sprite"
                    "&category=flowers", data)
        self.assertEqual((status, item["id"], item["name"]), (200, "x_blue_rose", "Blue Rose"))
        self.assertEqual(self.json("GET", "/api/library")[1]["items"], [item])
        # served under the artist's own file name, spaces and all
        self.assertEqual(item["file"], "flower x 0.png")
        self.assertEqual(self.ask("GET", "/library/x_blue_rose/flower%20x%200.png"),
                         (200, "image/png", data))

    def test_a_vox_is_inspected_previewed_then_converted(self):
        data = vox(block(16, 16, 16), block(32, 32, 2))
        status, body = self.json("POST", "/api/inspect/vox?file=two.vox", data)
        self.assertEqual((status, len(body["models"])), (200, 2))
        status, mesh = self.json("POST", "/api/preview/vox?file=two.vox&model=1", data)
        self.assertEqual((status, mesh["tiles"], len(mesh["boxes"])), (200, 2.0, 32 * 32))
        self.assertEqual(self.json("GET", "/api/library")[1]["items"], [])
        status, item = self.json(
            "POST", "/api/import/vox?file=two.vox&name=Deck&model=1&turn=100&wide=4&long=6"
                    "&category=inner", data)
        self.assertEqual((status, item["id"], item["category"], item["tilesWide"],
                          item["turn"], item["size"]),
                         (200, "house_x_deck", "inner", 4.0, 100, "fit"))
        status, kind, raw = self.ask("GET", "/library/house_x_deck/mesh.json")
        self.assertEqual((status, kind), (200, "application/json"))
        self.assertEqual(len(json.loads(raw)["boxes"]), item["boxes"])
        self.assertEqual(json.loads(raw)["turn"], 10)

    def test_a_refusal_reaches_the_page_in_words(self):
        status, body = self.json("POST", "/api/import/vox?file=notes.vox&name=x", b"hello there")
        self.assertEqual(status, 400)
        self.assertIn("notes.vox is not a MagicaVoxel", body["error"])
        status, body = self.json("POST", "/api/import/vox?file=a.vox&turn=sideways",
                                 vox(block(1, 1, 1)))
        self.assertEqual((status, body["error"]), (400, "'turn' has to be a whole number."))
        status, body = self.json("POST", "/api/import/vox?file=a.vox&wide=big&long=2",
                                 vox(block(1, 1, 1)))
        self.assertEqual((status, body["error"]), (400, "'wide' has to be a number."))

    def test_the_server_still_answers_after_a_refusal(self):
        # a refused upload must not leave its body in the way of the next request
        for _ in range(3):
            self.assertEqual(self.ask("POST", "/api/import/sprite?name=x", b"junk" * 5000)[0], 400)
            self.assertEqual(self.ask("GET", "/api/hello")[0], 200)

    def test_a_librarys_other_files_are_not_served(self):
        item = self.json("POST", "/api/import/vox?name=a&file=a.vox", vox(block(1, 1, 1)))[1]
        for name in ("meta.json", "a.vox", "..%2f..%2fstate.json"):
            self.assertEqual(self.ask("GET", f"/library/{item['id']}/{name}")[0], 404, name)


class Changing(ServerCase):
    def test_an_added_model_is_inspected_previewed_and_changed(self):
        data = vox(block(8, 4, 4), block(16, 16, 16))
        item = self.json("POST", "/api/import/vox?name=Shed&file=two.vox", data)[1]
        status, body = self.json("GET", f"/api/inspect/item/{item['id']}")
        self.assertEqual((status, [m["x"] for m in body["models"]]), (200, [8, 16]))
        status, mesh = self.json("GET", f"/api/preview/item/{item['id']}?model=1")
        self.assertEqual((status, mesh["tiles"]), (200, 1.0))
        status, changed = self.json(
            "POST", f"/api/change/{item['id']}?name=Barn&model=1&turn=45&size=fit&wide=3&long=3"
                    "&category=inner")
        self.assertEqual((status, changed["id"], changed["name"], changed["turn"],
                          changed["tilesWide"], changed["category"]),
                         (200, item["id"], "Barn", 45, 3.0, "inner"))
        self.assertEqual(self.json("GET", "/api/library")[1]["items"], [changed])

    def test_a_refused_change_says_why(self):
        item = self.json("POST", "/api/import/vox?name=a&file=a.vox", vox(block(2, 2, 2)))[1]
        status, body = self.json("POST", f"/api/change/{item['id']}?turn=999")
        self.assertEqual(status, 400)
        self.assertIn("turn", body["error"])
        self.assertEqual(self.json("POST", "/api/change/house_x_nothing?name=x")[0], 400)
        self.assertEqual(self.json("GET", "/api/inspect/item/..")[0], 400)


class Trash(ServerCase):
    def test_off_the_shelf_back_again_and_gone_for_good(self):
        item = self.json("POST", "/api/import/sprite?name=Gone&file=g.png", png(16, 16))[1]
        status, thrown = self.json("POST", f"/api/trash/{item['id']}")
        self.assertEqual((status, thrown["trashKey"]), (200, item["id"]))
        self.assertEqual(self.json("GET", "/api/library")[1]["items"], [])
        self.assertEqual(self.ask("GET", f"/library/{item['id']}/g.png")[0], 404)
        self.assertEqual([t["trashKey"] for t in self.json("GET", "/api/trash")[1]["items"]],
                         [item["id"]])
        self.assertEqual(self.json("GET", "/api/hello")[1]["trash"], 1)
        # nothing is deleted by taking it off the shelf
        self.assertTrue((self.server.library.bin / item["id"] / "g.png").is_file())

        self.assertEqual(self.json("POST", f"/api/restore/{item['id']}")[0], 200)
        self.assertEqual(self.json("GET", "/api/library")[1]["items"], [item])

        self.json("POST", f"/api/trash/{item['id']}")
        self.assertEqual(self.json("DELETE", f"/api/trash/{item['id']}")[0], 200)
        self.assertEqual(self.json("GET", "/api/trash")[1]["items"], [])
        self.assertFalse((self.server.library.bin / item["id"]).exists())

    def test_what_is_not_there_is_refused(self):
        self.assertEqual(self.json("POST", "/api/trash/x_nothing")[0], 400)
        self.assertEqual(self.json("POST", "/api/trash/..")[0], 400)
        self.assertEqual(self.json("POST", "/api/restore/x_nothing")[0], 400)
        self.assertEqual(self.json("DELETE", "/api/trash/x_nothing")[0], 400)

    def test_what_is_on_the_shelf_cannot_be_deleted(self):
        item = self.json("POST", "/api/import/sprite?name=Kept", png(16, 16))[1]
        self.assertEqual(self.json("DELETE", f"/api/trash/{item['id']}")[0], 400)
        self.assertEqual(self.json("DELETE", f"/api/library/{item['id']}")[0], 404)
        self.assertEqual(self.json("GET", "/api/library")[1]["items"], [item])

    def test_emptying_the_trash(self):
        kept = self.json("POST", "/api/import/sprite?name=Kept", png(16, 16))[1]
        for name in ("a", "b"):
            item = self.json("POST", f"/api/import/sprite?name={name}", png(16, 16))[1]
            self.json("POST", f"/api/trash/{item['id']}")
        self.assertEqual(self.json("DELETE", "/api/trash"), (200, {"deleted": 2}))
        self.assertEqual(self.json("GET", "/api/trash")[1]["items"], [])
        self.assertEqual(self.json("GET", "/api/library")[1]["items"], [kept])


class FakeUpdates:
    def __init__(self):
        self.state = {"state": "idle", "version": VERSION, "latest": ""}
        self.refuse = None

    def status(self):
        return dict(self.state)

    def check(self):
        self.state.update(state="available", latest="9.9.9")
        return self.status()

    def apply(self):
        if self.refuse:
            raise ValueError(self.refuse)
        self.state["state"] = "downloading"
        return self.status()


class Updating(ServerCase):
    def test_the_page_asks_checks_and_applies(self):
        self.server.updates = FakeUpdates()
        self.assertEqual(self.json("GET", "/api/update")[1]["state"], "idle")
        self.assertEqual(self.json("POST", "/api/update/check")[1]["latest"], "9.9.9")
        self.assertEqual(self.json("POST", "/api/update/apply")[1]["state"], "downloading")

    def test_an_update_that_cannot_be_installed_says_why(self):
        self.server.updates = FakeUpdates()
        self.server.updates.refuse = "Only the installed Dev Kit can update itself."
        status, body = self.json("POST", "/api/update/apply")
        self.assertEqual((status, body["error"]),
                         (400, "Only the installed Dev Kit can update itself."))

    def test_a_kit_with_no_updater_says_so(self):
        self.assertEqual(self.json("GET", "/api/update")[0], 404)
        self.assertEqual(self.json("POST", "/api/update/check")[0], 404)


class State(ServerCase):
    def test_the_garden_is_saved_and_read_back(self):
        self.assertEqual(self.ask("GET", "/api/state")[0], 404)
        saved = json.dumps({"garden": "cols:4\nrows:8\n0:gul~0", "view": "mobile"}).encode()
        self.assertEqual(self.json("PUT", "/api/state", saved)[0], 200)
        self.assertEqual(self.ask("GET", "/api/state")[2], saved)
        self.assertEqual(self.json("PUT", "/api/state", b"not json")[0], 400)
        self.assertEqual(self.ask("GET", "/api/state")[2], saved)

    def test_open_folder_shows_the_folder_asked_for(self):
        library = self.server.library
        item = self.json("POST", "/api/import/sprite?name=Rose", png(16, 16))[1]
        self.assertEqual(self.json("POST", "/api/open-folder")[0], 200)
        self.assertEqual(self.json("POST", "/api/open-folder?which=trash")[0], 200)
        self.assertEqual(self.json("POST", "/api/open-folder?which=program")[0], 200)
        self.assertEqual(self.json("POST", f"/api/open-folder?which=item&id={item['id']}")[0], 200)
        from dev_kit import paths
        self.assertEqual(self.opened, [library.data, library.bin, paths.program_dir(),
                                       library.root / item["id"]])
        self.assertEqual(self.json("POST", "/api/open-folder?which=item&id=..")[0], 400)

    def test_what_the_page_trips_over_reaches_the_log(self):
        with self.assertLogs("dev_kit", level="WARNING") as seen:
            self.assertEqual(self.json("POST", "/api/log", b"RangeError: index 4")[0], 200)
        self.assertIn("page: RangeError: index 4", seen.output[0])
        # bounded: a page stuck in a loop cannot fill the disk
        self.server.page_complaints = 200
        with self.assertNoLogs("dev_kit", level="WARNING"):
            self.assertEqual(self.json("POST", "/api/log", b"again")[0], 200)

    def test_what_the_kit_has_no_word_for(self):
        self.assertEqual(self.json("GET", "/api/everything")[0], 404)
        self.assertEqual(self.json("POST", "/index.html", b"x")[0], 405)


if __name__ == "__main__":
    unittest.main()
