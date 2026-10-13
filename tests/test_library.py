"""The library on disk: what is taken in, what is refused, and what it leaves."""
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from dev_kit.library import (MAX_BOXES, Library, Refused, converter, one_model,
                             png_size, safe_file_name, slug, vox_parts)


def chunk(cid, content=b"", children=b""):
    return cid + struct.pack("<ii", len(content), len(children)) + content + children


def vox(*models, palette=True):
    """A .vox file holding `models`, each (size, {(x, y, z): palette index})."""
    body = b""
    for size, voxels in models:
        body += chunk(b"SIZE", struct.pack("<iii", *size))
        body += chunk(b"XYZI", struct.pack("<i", len(voxels)) + b"".join(
            struct.pack("<BBBB", x, y, z, i) for (x, y, z), i in voxels.items()))
    if palette:
        body += chunk(b"RGBA", b"".join(struct.pack("<BBBB", k, 255 - k, 7, 255)
                                        for k in range(1, 256)) + b"\0\0\0\0")
    return b"VOX " + struct.pack("<i", 200) + chunk(b"MAIN", children=body)


def block(sx, sy, sz, index=3):
    return ((sx, sy, sz), {(x, y, z): index
                           for x in range(sx) for y in range(sy) for z in range(sz)})


def png(width, height):
    """A real, if blank, PNG of that size."""
    def part(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    rows = b"".join(b"\0" + b"\0\0\0\0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + part(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + part(b"IDAT", zlib.compress(rows)) + part(b"IEND", b""))


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        self.library = Library(self.data)

    def ids(self):
        return [item["id"] for item in self.library.items()]

    def mesh(self, item):
        return json.loads(self.library.file_path(item["id"], "mesh.json").read_text())


class Sprites(LibraryCase):
    def test_a_sprite_is_kept_as_it_was_picked_under_its_own_name(self):
        data = png(256, 304)
        item = self.library.import_sprite(data, "flower_gul_0.png", "My Rose")
        self.assertEqual(item["id"], "x_my_rose")
        self.assertEqual((item["kind"], item["category"]), ("sprite", "flowers"))
        self.assertEqual((item["width"], item["heightPx"]), (256, 304))
        self.assertEqual(item["source"], "flower_gul_0.png")
        # the kit's copy is the artist's file, findable by the name they gave it
        self.assertEqual((item["file"], item["original"]),
                         ("flower_gul_0.png", "flower_gul_0.png"))
        kept = self.library.root / "x_my_rose" / "flower_gul_0.png"
        self.assertEqual(kept.read_bytes(), data)
        self.assertEqual(self.library.file_path(item["id"], "flower_gul_0.png"), kept)
        self.assertEqual(self.library.items(), [item])

    def test_a_second_sprite_of_the_same_name_gets_its_own_id(self):
        first = self.library.import_sprite(png(16, 16), "a.png", "Rose")
        second = self.library.import_sprite(png(16, 16), "b.png", "Rose")
        self.assertEqual((first["id"], second["id"]), ("x_rose", "x_rose_2"))
        self.assertEqual(self.ids(), ["x_rose", "x_rose_2"])

    def test_a_ground_is_told_apart_by_its_id(self):
        item = self.library.import_sprite(png(256, 256), "floor.png", "Marble",
                                          kind="ground", category="outer")
        self.assertEqual(item["id"], "xroad_marble")

    def test_ids_are_safe_to_store_in_a_garden(self):
        # a garden line is `index:id`, and `+` and `~` mean something in it
        for name in ("Çiçek + 2", "a:b~c", "  ", "ROSE\n1", "日本"):
            self.assertRegex(slug(name), r"^[a-z0-9_]+$", name)

    def test_the_kept_copys_name_is_safe_to_write(self):
        self.assertEqual(safe_file_name("C:\\art\\My Rose.png", "x"), "My Rose.png")
        self.assertEqual(safe_file_name("../../etc/passwd", "x"), "passwd")
        self.assertEqual(safe_file_name('a<b>:"c|d?*.vox', "x"), "a_b___c_d__.vox")
        self.assertEqual(safe_file_name("çiçek 日本.png", "x"), "çiçek 日本.png")
        # never one of the kit's own files, never a Windows device, never empty
        self.assertEqual(safe_file_name("meta.json", "x"), "_meta.json")
        self.assertEqual(safe_file_name("MESH.JSON", "x"), "_MESH.JSON")
        self.assertEqual(safe_file_name("con.vox", "x"), "_con.vox")
        self.assertEqual(safe_file_name(" .. ", "sprite.png"), "sprite.png")
        self.assertLessEqual(len(safe_file_name("a" * 500 + ".png", "x")), 120)

    def test_what_is_not_a_png_is_refused(self):
        with self.assertRaisesRegex(Refused, "not a PNG"):
            self.library.import_sprite(b"hello", "notapng.png", "x")
        self.assertEqual(self.library.items(), [])

    def test_an_enormous_picture_is_refused(self):
        with self.assertRaisesRegex(Refused, "5000 x 16"):
            self.library.import_sprite(png(5000, 16)[:64], "wide.png", "x")

    def test_png_size_reads_the_header(self):
        self.assertEqual(png_size(png(12, 34)), (12, 34))


class Forest(LibraryCase):
    def test_a_forest_sprite_replaces_the_one_before_it_which_goes_to_the_trash(self):
        first = self.library.import_sprite(png(512, 512), "tree_07.png", "tree_07",
                                           kind="forest", target="tree_07")
        second = self.library.import_sprite(png(256, 256), "tree_07.png", "tree_07",
                                            kind="forest", target="tree_07")
        self.assertEqual(first["id"], "forest_tree_07")
        self.assertEqual(second["id"], "forest_tree_07")
        self.assertEqual([i["width"] for i in self.library.items()], [256])
        # replaced, not deleted
        self.assertEqual([i["width"] for i in self.library.trashed()], [512])

    def test_a_forest_sprite_must_name_one_the_game_has(self):
        for target in (None, "tree_7", "shrub_01", "tree_20", "rock_05"):
            with self.assertRaises(Refused, msg=target):
                self.library.import_sprite(png(16, 16), "t.png", "t",
                                           kind="forest", target=target)
        self.library.import_sprite(png(16, 16), "t.png", "t", kind="forest", target="rock_04")


class Voxels(LibraryCase):
    def test_a_model_becomes_the_games_box_mesh(self):
        data = vox(block(16, 16, 8))
        item = self.library.import_vox(data, "hut.vox", "Hut")
        self.assertEqual(item["id"], "house_x_hut")
        self.assertEqual((item["kind"], item["category"], item["file"]),
                         ("vox", "outer", "mesh.json"))
        self.assertEqual((item["tiles"], item["height"]), (1.0, 0.5))
        mesh = self.mesh(item)
        self.assertEqual(mesh["id"], "house_x_hut")
        self.assertEqual(len(mesh["boxes"]), item["boxes"])
        self.assertNotIn("turn", mesh)
        # the game's converter: one box per visible column, sealed ones dropped
        self.assertEqual(item["boxes"], 16 * 16)
        # the file the artist picked is kept beside the mesh made from it,
        # under the name they know it by
        self.assertEqual(item["original"], "hut.vox")
        self.assertEqual((self.library.root / item["id"] / "hut.vox").read_bytes(), data)

    def test_every_choice_made_is_written_down(self):
        data = vox(block(16, 16, 16), block(8, 4, 4))
        item = self.library.import_vox(data, "two.vox", "b", model=1, turn=30,
                                       wide=2, long=3, category="inner")
        self.assertEqual(
            {k: item[k] for k in ("model", "models", "modelSize", "turn", "size",
                                  "fitWide", "fitLong", "category", "source")},
            {"model": 1, "models": 2, "modelSize": [8, 4, 4], "turn": 30, "size": "fit",
             "fitWide": 2.0, "fitLong": 3.0, "category": "inner", "source": "two.vox"})
        plain = self.library.import_vox(data, "two.vox", "a")
        self.assertEqual((plain["size"], plain["fitWide"], plain["fitLong"], plain["turn"]),
                         ("original", None, None, 0))

    def test_original_size_is_sixteen_voxels_to_a_tile(self):
        item = self.library.import_vox(vox(block(32, 8, 4)), "a.vox", "a")
        self.assertEqual((item["tilesWide"], item["tilesLong"], item["height"]),
                         (2.0, 0.5, 0.25))

    def test_a_fit_is_as_large_as_goes_into_both_sides_and_keeps_the_shape(self):
        # 8 wide, 4 long: a 2 x 2 footprint is filled across and half used along
        item = self.library.import_vox(vox(block(8, 4, 4)), "a.vox", "a", wide=2, long=2)
        self.assertEqual((item["tilesWide"], item["tilesLong"], item["height"]),
                         (2.0, 1.0, 1.0))
        self.assertEqual(item["tiles"], 2.0)
        # ...and a 4 x 1 one is limited by its length
        item = self.library.import_vox(vox(block(8, 4, 4)), "a.vox", "b", wide=4, long=1)
        self.assertEqual((item["tilesWide"], item["tilesLong"]), (2.0, 1.0))
        # a fit can be any size the artist types, not three fixed ones
        item = self.library.import_vox(vox(block(8, 4, 4)), "a.vox", "c", wide=5.5, long=9)
        self.assertEqual((item["tilesWide"], item["tilesLong"]), (5.5, 2.75))

    def test_a_quarter_turn_is_written_into_the_boxes(self):
        data = vox(block(8, 4, 4))
        item = self.library.import_vox(data, "a.vox", "a", turn=90)
        # turned a quarter, its long side runs the other way
        self.assertEqual((item["tilesWide"], item["tilesLong"]), (0.25, 0.5))
        self.assertNotIn("turn", self.mesh(item))
        self.assertEqual(item["turn"], 90)

    def test_any_other_angle_rides_in_the_mesh(self):
        data = vox(block(8, 4, 4))
        item = self.library.import_vox(data, "a.vox", "a", turn=100)
        # 90 of it in the boxes, the other 10 for the game's painter to add
        self.assertEqual(self.mesh(item)["turn"], 10)
        self.assertEqual((item["tilesWide"], item["tilesLong"]), (0.25, 0.5))
        self.assertEqual(item["turn"], 100)
        self.assertEqual(self.mesh(self.library.import_vox(data, "a.vox", "b", turn=37))["turn"], 37)
        # a full turn is no turn
        full = self.library.import_vox(data, "a.vox", "c", turn=360)
        self.assertEqual(full["turn"], 0)
        self.assertNotIn("turn", self.mesh(full))

    def test_a_fit_is_measured_after_the_quarter_turn(self):
        # turned a quarter the model is 4 wide and 8 long; 1 x 4 then fits it whole
        item = self.library.import_vox(vox(block(8, 4, 4)), "a.vox", "a", turn=90,
                                       wide=1, long=4)
        self.assertEqual((item["tilesWide"], item["tilesLong"]), (1.0, 2.0))

    def test_inspect_lists_every_model_in_the_file(self):
        models = self.library.inspect_vox(vox(block(2, 3, 4), block(1, 1, 1)), "two.vox")
        self.assertEqual(models, [{"x": 2, "y": 3, "z": 4, "voxels": 24},
                                  {"x": 1, "y": 1, "z": 1, "voxels": 1}])

    def test_the_preview_is_the_model_as_it_is_in_the_file_and_saves_nothing(self):
        data = vox(block(16, 16, 16), block(32, 32, 1))
        mesh = self.library.preview_vox(data, "two.vox", 1)
        self.assertEqual((mesh["tiles"], len(mesh["boxes"])), (2.0, 32 * 32))
        self.assertEqual(self.library.items(), [])
        with self.assertRaisesRegex(Refused, "12100 boxes"):
            self.library.preview_vox(vox(block(110, 110, 1)), "slab.vox")

    def test_the_chosen_model_is_the_one_converted(self):
        data = vox(block(16, 16, 16), block(32, 32, 1))
        self.assertEqual(self.library.import_vox(data, "two.vox", "a", model=1)["tiles"], 2.0)
        with self.assertRaisesRegex(Refused, "no model 5"):
            self.library.import_vox(data, "two.vox", "b", model=5)

    def test_refusals_name_the_artists_file_not_a_scratch_one(self):
        with self.assertRaisesRegex(Refused, r"^notes\.vox is not a MagicaVoxel"):
            self.library.inspect_vox(b"just some text, long enough to read", "notes.vox")
        with self.assertRaisesRegex(Refused, r"^bare\.vox carries no palette"):
            self.library.import_vox(vox(block(1, 1, 1), palette=False), "bare.vox", "x")

    def test_a_file_cut_short_is_refused_not_crashed_on(self):
        data = vox(block(4, 4, 4))
        with self.assertRaises(Refused):
            self.library.inspect_vox(data[:14], "cut.vox")

    def test_a_refused_model_leaves_nothing_behind(self):
        with self.assertRaises(Refused):
            self.library.import_vox(b"nope", "bad.vox", "Bad")
        self.assertEqual(self.library.items(), [])
        self.assertEqual(list(self.library.root.iterdir()), [])
        # the scratch copy the converter read goes with the next start
        Library(self.data)
        self.assertFalse((self.data / "tmp").exists())

    def test_the_scratch_folder_does_not_grow(self):
        for n in range(1, 7):
            self.library.preview_vox(vox(block(n, 1, 1)), f"{n}.vox")
        self.assertLessEqual(len(list((self.data / "tmp").iterdir())), 3)

    def test_a_model_too_heavy_to_draw_is_refused(self):
        side = 110   # a 110x110 slab is 12100 columns, each one a box
        self.assertGreater(side * side, MAX_BOXES)
        with self.assertRaisesRegex(Refused, "12100 boxes"):
            self.library.import_vox(vox(block(side, side, 1)), "slab.vox", "Slab")
        self.assertEqual(self.library.items(), [])

    def test_wrong_settings_are_refused(self):
        data = vox(block(2, 2, 2))
        for bad in ({"turn": 400}, {"turn": -1}, {"turn": "left"},
                    {"wide": 100, "long": 1}, {"wide": 0.1, "long": 1},
                    {"wide": 2}, {"long": 2}, {"wide": float("nan"), "long": 1},
                    {"category": "attic"}, {"model": "first"}):
            with self.assertRaises(Refused, msg=bad):
                self.library.import_vox(data, "a.vox", "a", **bad)
        self.assertEqual(self.library.items(), [])


class OneModelOfMany(LibraryCase):
    """A scene file is cut down to the model asked for before the game's
    converter sees it, so eighty models are not read to convert one."""

    def test_the_cut_file_holds_that_model_and_the_palette_and_nothing_else(self):
        data = vox(block(2, 3, 4, index=5), block(1, 1, 1, index=9), block(6, 5, 4, index=7))
        cut, count = one_model(data, 1)
        self.assertEqual(count, 3)
        path = self.data / "cut.vox"
        path.write_bytes(cut)
        models, palette = converter().read_vox(str(path))
        whole_models, whole_palette = converter().read_vox(str(self.write(data)))
        self.assertEqual(models, [whole_models[1]])
        self.assertEqual(palette, whole_palette)

    def write(self, data):
        path = self.data / "whole.vox"
        path.write_bytes(data)
        return path

    def test_a_model_converted_from_the_cut_is_the_model_converted_from_the_whole(self):
        data = vox(block(8, 4, 4, index=5), block(3, 9, 2, index=9), block(6, 5, 4, index=7))
        whole = self.write(data)
        for model in range(3):
            for turn in (0, 90):
                ours = self.library.import_vox(data, "scene.vox", f"m{model}t{turn}",
                                               model=model, turn=turn)
                theirs = converter().convert(str(whole), ours["id"], model=model,
                                             turn=turn // 90)
                self.assertEqual(self.mesh(ours), theirs, (model, turn))
                self.assertEqual((ours["model"], ours["models"]), (model, 3))

    def test_the_list_of_models_comes_from_the_headers(self):
        data = vox(block(2, 3, 4), block(1, 1, 1))
        self.assertEqual(self.library.inspect_vox(data, "two.vox"),
                         [{"x": 2, "y": 3, "z": 4, "voxels": 24},
                          {"x": 1, "y": 1, "z": 1, "voxels": 1}])
        # ...and reading it wrote nothing to disk
        self.assertFalse((self.data / "tmp").exists())

    def test_what_cannot_be_cut_is_left_to_the_games_own_reader(self):
        good = vox(block(2, 2, 2))
        for bad in (b"", b"hello there, this is not a vox file",
                    good[:30],                               # cut short
                    vox(block(1, 1, 1), palette=False),      # no palette
                    good[:20] + chunk(b"XYZI", b"\0" * 8)):  # a model with no SIZE
            self.assertIsNone(vox_parts(bad))
            self.assertIsNone(one_model(bad, 0))
        self.assertIsNone(one_model(good, 1))
        self.assertIsNone(one_model(good, -1))
        # the refusal is still the game's, in the artist's file's name
        with self.assertRaisesRegex(Refused, r"^bare\.vox carries no palette"):
            self.library.import_vox(vox(block(1, 1, 1), palette=False), "bare.vox", "x")
        with self.assertRaisesRegex(Refused, "no model 7 — it holds 1"):
            self.library.import_vox(good, "one.vox", "x", model=7)


class Changing(LibraryCase):
    def test_a_model_is_made_again_from_the_kits_copy(self):
        data = vox(block(8, 4, 4), block(16, 16, 16))
        item = self.library.import_vox(data, "two.vox", "Shed")
        changed = self.library.change(item["id"], name="Barn", category="inner", model=1,
                                      turn=45, size="fit", wide=3, long=3)
        # the same thing on the shelf and in the garden, made differently
        self.assertEqual((changed["id"], changed["added"]), (item["id"], item["added"]))
        self.assertEqual((changed["name"], changed["category"], changed["model"],
                          changed["turn"], changed["size"], changed["tilesWide"]),
                         ("Barn", "inner", 1, 45, "fit", 3.0))
        self.assertEqual(self.mesh(changed)["turn"], 45)
        self.assertEqual(self.library.items(), [changed])
        # the artist's file is still the one they picked
        self.assertEqual((self.library.root / item["id"] / "two.vox").read_bytes(), data)

    def test_what_is_not_said_stays_as_it_was(self):
        item = self.library.import_vox(vox(block(8, 4, 4)), "a.vox", "a", turn=30,
                                       wide=2, long=2)
        changed = self.library.change(item["id"], name="b")
        self.assertEqual({k: changed[k] for k in ("turn", "size", "fitWide", "fitLong", "boxes")},
                         {k: item[k] for k in ("turn", "size", "fitWide", "fitLong", "boxes")})
        back = self.library.change(item["id"], size="original")
        self.assertEqual((back["size"], back["fitWide"], back["tilesWide"]),
                         ("original", None, 0.5))

    def test_a_fit_asked_for_without_its_sides_is_refused(self):
        item = self.library.import_vox(vox(block(8, 4, 4)), "a.vox", "a")
        with self.assertRaisesRegex(Refused, "both sides"):
            self.library.change(item["id"], size="fit")
        self.assertEqual(self.library.items(), [item])

    def test_a_refused_change_changes_nothing(self):
        item = self.library.import_vox(vox(block(8, 4, 4)), "a.vox", "a")
        for bad in ({"turn": 999}, {"model": 4}, {"category": "attic"}, {"size": "huge"}):
            with self.assertRaises(Refused, msg=bad):
                self.library.change(item["id"], **bad)
        self.assertEqual(self.library.items(), [item])

    def test_a_sprite_can_be_renamed_moved_and_laid_flat(self):
        item = self.library.import_sprite(png(16, 16), "a.png", "Rose")
        changed = self.library.change(item["id"], name="Tile", category="outer", kind="ground")
        self.assertEqual((changed["id"], changed["name"], changed["category"], changed["kind"]),
                         ("x_rose", "Tile", "outer", "ground"))
        with self.assertRaises(Refused):
            self.library.change(item["id"], kind="vox")
        tree = self.library.import_sprite(png(16, 16), "tree_01.png", "t", kind="forest",
                                          target="tree_01")
        with self.assertRaises(Refused):
            self.library.change(tree["id"], kind="sprite")

    def test_a_model_whose_copy_is_gone_says_so(self):
        item = self.library.import_vox(vox(block(2, 2, 2)), "a.vox", "a")
        (self.library.root / item["id"] / "a.vox").unlink()
        with self.assertRaisesRegex(Refused, "copy of a.vox is gone"):
            self.library.change(item["id"], turn=90)
        with self.assertRaises(Refused):
            self.library.change("house_x_nothing", name="x")


class Trash(LibraryCase):
    def test_taking_something_off_the_shelf_deletes_nothing(self):
        data = vox(block(2, 2, 2))
        item = self.library.import_vox(data, "a.vox", "a")
        thrown = self.library.trash(item["id"])
        self.assertEqual(self.library.items(), [])
        self.assertIsNone(self.library.file_path(item["id"], "mesh.json"))
        self.assertEqual([t["trashKey"] for t in self.library.trashed()], [thrown["trashKey"]])
        # the whole folder moved, the artist's file with it
        self.assertEqual((self.library.bin / thrown["trashKey"] / "a.vox").read_bytes(), data)
        with self.assertRaises(Refused):
            self.library.trash(item["id"])

    def test_it_comes_back_as_it_was(self):
        item = self.library.import_vox(vox(block(2, 2, 2)), "a.vox", "a", turn=20)
        key = self.library.trash(item["id"])["trashKey"]
        self.assertEqual(self.library.restore(key), item)
        self.assertEqual(self.library.items(), [item])
        self.assertEqual(self.library.trashed(), [])
        self.assertEqual(self.mesh(item)["turn"], 20)

    def test_an_id_in_the_trash_is_not_given_to_something_new(self):
        first = self.library.import_sprite(png(16, 16), "a.png", "Rose")
        key = self.library.trash(first["id"])["trashKey"]
        second = self.library.import_sprite(png(16, 16), "b.png", "Rose")
        self.assertNotEqual(second["id"], first["id"])
        self.library.restore(key)
        self.assertEqual(sorted(self.ids()), sorted([first["id"], second["id"]]))

    def test_a_forest_sprite_put_back_swaps_with_the_one_standing(self):
        self.library.import_sprite(png(512, 512), "old.png", "t", kind="forest", target="tree_07")
        self.library.import_sprite(png(256, 256), "new.png", "t", kind="forest", target="tree_07")
        key = self.library.trashed()[0]["trashKey"]
        self.library.restore(key)
        self.assertEqual([i["width"] for i in self.library.items()], [512])
        self.assertEqual([i["width"] for i in self.library.trashed()], [256])

    def test_the_same_thing_can_be_in_the_trash_twice(self):
        for size in (16, 32):
            self.library.import_sprite(png(size, size), "t.png", "t", kind="forest",
                                       target="bush_03")
            self.library.trash("forest_bush_03")
        self.assertEqual(sorted(t["trashKey"] for t in self.library.trashed()),
                         ["forest_bush_03", "forest_bush_03__2"])

    def test_deleting_is_from_the_trash_only_and_for_good(self):
        item = self.library.import_sprite(png(16, 16), "a.png", "a")
        with self.assertRaises(Refused):
            self.library.delete(item["id"])       # on the shelf: not deletable
        self.assertEqual(self.library.items(), [item])
        key = self.library.trash(item["id"])["trashKey"]
        self.library.delete(key)
        self.assertEqual(self.library.trashed(), [])
        self.assertFalse((self.library.bin / key).exists())
        for bad in (key, "..", "../library", ""):
            with self.assertRaises(Refused, msg=bad):
                self.library.delete(bad)

    def test_emptying_takes_everything_in_it_and_nothing_else(self):
        kept = self.library.import_sprite(png(16, 16), "a.png", "kept")
        for name in ("b", "c"):
            self.library.trash(self.library.import_sprite(png(16, 16), "x.png", name)["id"])
        self.assertEqual(self.library.empty_trash(), 2)
        self.assertEqual(self.library.trashed(), [])
        self.assertEqual(self.library.items(), [kept])
        self.assertEqual(self.library.empty_trash(), 0)


class Housekeeping(LibraryCase):
    def test_file_path_serves_only_the_file_an_item_is_drawn_from(self):
        item = self.library.import_sprite(png(16, 16), "a.png", "a")
        model = self.library.import_vox(vox(block(1, 1, 1)), "m.vox", "m")
        for bad_id, name in (("..", "a.png"), (item["id"], "meta.json"),
                             (item["id"], "../../state.json"), ("X", "a.png"),
                             (model["id"], "m.vox"), (model["id"], "meta.json")):
            self.assertIsNone(self.library.file_path(bad_id, name), (bad_id, name))

    def test_a_damaged_entry_costs_only_itself(self):
        good = self.library.import_sprite(png(16, 16), "a.png", "good")
        bad = self.library.import_sprite(png(16, 16), "b.png", "bad")
        (self.library.root / bad["id"] / "meta.json").write_text("{ not json")
        (self.library.root / "stray").mkdir()
        self.assertEqual(self.ids(), [good["id"]])

    def test_the_garden_is_remembered(self):
        self.assertIsNone(self.library.load_state())
        self.library.save_state(b'{"garden": "cols:4"}')
        self.assertEqual(Library(self.data).load_state(), b'{"garden": "cols:4"}')
        with self.assertRaises(Refused):
            self.library.save_state(b"not json")
        self.assertEqual(self.library.load_state(), b'{"garden": "cols:4"}')


class WhatAnOlderVersionLeft(LibraryCase):
    """v0.1.0 kept the files in %LOCALAPPDATA%, the copies as sprite.png and
    source.vox, and a fit as one number."""

    def old_library(self):
        old = self.data / "old"
        (old / "library" / "house_x_hut").mkdir(parents=True)
        (old / "library" / "x_rose").mkdir()
        data = vox(block(8, 4, 4))
        (old / "library" / "house_x_hut" / "source.vox").write_bytes(data)
        (old / "library" / "house_x_hut" / "mesh.json").write_text(
            '{"id":"house_x_hut","tiles":2,"boxes":[]}')
        (old / "library" / "house_x_hut" / "meta.json").write_text(json.dumps({
            "id": "house_x_hut", "added": 5, "name": "Hut", "kind": "vox",
            "category": "outer", "file": "mesh.json", "source": "hut.vox", "boxes": 32,
            "tiles": 2.0, "height": 1.0, "model": 0, "turn": 90, "fit": 2.0}))
        (old / "library" / "x_rose" / "sprite.png").write_bytes(png(16, 16))
        (old / "library" / "x_rose" / "meta.json").write_text(json.dumps({
            "id": "x_rose", "added": 3, "name": "Rose", "kind": "sprite",
            "category": "flowers", "file": "sprite.png", "source": "rose.png",
            "width": 16, "heightPx": 16}))
        (old / "state.json").write_text('{"garden": "cols:4"}')
        return old, data

    def test_its_files_are_copied_in_once_and_left_where_they_were(self):
        old, _ = self.old_library()
        library = Library(self.data / "new")
        self.assertEqual(library.adopt(old), 2)
        self.assertEqual([i["id"] for i in library.items()], ["x_rose", "house_x_hut"])
        self.assertEqual(library.load_state(), b'{"garden": "cols:4"}')
        self.assertTrue((old / "library" / "x_rose" / "sprite.png").is_file())
        # once: emptying the new library does not bring them back
        library.trash("x_rose")
        library.trash("house_x_hut")
        self.assertEqual(library.adopt(old), 0)
        self.assertEqual(library.items(), [])

    def test_a_library_already_in_use_is_left_alone(self):
        old, _ = self.old_library()
        library = Library(self.data / "new")
        mine = library.import_sprite(png(16, 16), "a.png", "mine")
        self.assertEqual(library.adopt(old), 0)
        self.assertEqual(library.items(), [mine])
        self.assertEqual(library.adopt(self.data / "nowhere"), 0)

    def test_its_records_read_as_this_versions_do(self):
        old, data = self.old_library()
        library = Library(self.data / "new")
        library.adopt(old)
        hut = next(i for i in library.items() if i["id"] == "house_x_hut")
        self.assertEqual((hut["original"], hut["size"], hut["fitWide"], hut["fitLong"]),
                         ("source.vox", "fit", 2.0, 2.0))
        rose = next(i for i in library.items() if i["id"] == "x_rose")
        self.assertEqual(library.file_path("x_rose", "sprite.png").read_bytes(), png(16, 16))
        self.assertEqual(rose["original"], "sprite.png")
        # ...and can be changed like anything added today
        changed = library.change("house_x_hut", turn=0, size="original")
        self.assertEqual((changed["turn"], changed["size"], changed["tilesWide"]),
                         (0, "original", 0.5))
        self.assertNotIn("fit", changed)


if __name__ == "__main__":
    unittest.main()
