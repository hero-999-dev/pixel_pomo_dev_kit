"""The artist's files, on disk.

    <files>/library/<id>/meta.json        what it is, and every choice made
                         CoffeeLocal.vox  the file as it was picked, under its
                                          own name — the kit's copy of it
                         mesh.json        a voxel model: the box mesh drawn
    <files>/trash/<key>/...               the same, for what was taken off the
                                          shelf; nothing is deleted until the
                                          artist empties it
    <files>/state.json                    the garden and the view, as last left

A .vox becomes a mesh through the game's own `vox_to_boxes.py` — imported,
never copied, for the reason the Art Kit imports `gen_objects.py`: a second
converter would be a second answer to "what will the game draw", and the kit
exists to give the game's.
"""
import functools
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from dev_kit import paths

KINDS = ("sprite", "ground", "vox", "forest")
CATEGORIES = ("flowers", "outer", "inner", "pets")
FOREST_TARGET = re.compile(r"^(tree|bush|rock)_\d\d$")
ID = re.compile(r"^[a-z0-9_]+$")

# How many of each forest sprite the game has (kForestTrees/Bushes/Rocks).
FOREST_POOL = {"tree": 20, "bush": 10, "rock": 5}

# Guards, not measurements. The largest picture the game ships is 1024 px a
# side; the heaviest model tried in the garden is about 2000 boxes.
MAX_SPRITE_PIXELS = 4096
MAX_BOXES = 10000
# A model is fitted into a footprint of between a quarter of a tile and this.
MIN_FIT, MAX_FIT = 0.25, 16.0

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Files of the kit's own in an item's folder; the artist's copy never takes
# one of these names.
OWN_FILES = ("meta.json", "mesh.json")
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                   *(f"LPT{n}" for n in range(1, 10))}

# A file's models are kept in memory between the steps of one ADD (what is in
# it, the preview, the conversion) only when they are small enough not to
# matter; a 1.7-million-voxel scene is read again each time instead.
KEEP_VOXELS = 300_000


class Refused(Exception):
    """Something the kit will not do, said in words meant for the artist."""


def _remembering(read_vox):
    """`read_vox`, remembering the last file it read."""
    kept = {}

    def read(path):
        stat = os.stat(path)
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key in kept:
            return kept[key]
        result = read_vox(path)
        kept.clear()
        if sum(len(voxels) for _, voxels in result[0]) <= KEEP_VOXELS:
            kept[key] = result
        return result

    return read


@functools.lru_cache(maxsize=1)
def converter():
    """The game's `vox_to_boxes` module."""
    folder = paths.tools_dir()
    path = folder / "vox_to_boxes.py"
    if not path.exists():
        raise Refused(
            f"The game's voxel converter is missing ({path}). The Dev Kit and "
            f"the App folder have to sit side by side.")
    # vox_to_boxes imports its sibling obj_to_boxes by bare name
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location("vox_to_boxes", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # the same function, the same answers; it only stops one ADD reading a
    # large file three times over
    module.read_vox = _remembering(module.read_vox)
    return module


def vox_parts(data):
    """([(SIZE chunk, XYZI chunk)] per model, the RGBA chunk) of a .vox, each
    chunk as its raw bytes — or None for anything that is not plainly a
    well-formed file with a palette, which is then left to the game's own
    reader to describe.

    The pairing is the game's (`vox_to_boxes.read_vox`): a model is an XYZI
    chunk and the SIZE chunk last seen before it.
    """
    if len(data) < 20 or data[:4] != b"VOX " or data[8:12] != b"MAIN":
        return None
    models, palette, size = [], None, None
    at, end = 20 + struct.unpack_from("<i", data, 12)[0], len(data)
    while at + 12 <= end:
        cid, n, m = struct.unpack_from("<4sii", data, at)
        stop = at + 12 + n + m
        if n < 0 or m < 0 or stop > end:
            return None
        chunk = data[at:stop]
        if cid == b"SIZE":
            size = chunk
        elif cid == b"XYZI":
            if size is None or n < 4:
                return None
            models.append((size, chunk))
        elif cid == b"RGBA":
            palette = chunk
        at = stop
    if not models or palette is None:
        return None
    return models, palette


def one_model(data, model):
    """A .vox holding only model number `model` of `data`, and how many
    models `data` has: ((bytes, count)), or None where `vox_parts` gives up.

    A scene file is easily 9 MB and eighty models, and the game's reader
    reads every voxel of all of them to convert one. Handed a file with the
    one model in it, the same reader and the same converter do the same work
    on that model alone — in a fraction of a second instead of several."""
    parts = vox_parts(data)
    if parts is None:
        return None
    models, palette = parts
    if not 0 <= model < len(models):
        return None
    body = models[model][0] + models[model][1] + palette
    return (data[:8] + b"MAIN" + struct.pack("<ii", 0, len(body)) + body), len(models)


def png_size(data):
    """(width, height) of a PNG, or Refused if it is not one."""
    if len(data) < 24 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise Refused("That is not a PNG file.")
    return struct.unpack(">II", data[16:24])


def slug(name):
    """A garden-safe id fragment: the garden stores a tile as `index:id`,
    joins a ground and a prop with `+` and marks a variant with `~`, so an id
    is lower-case letters, digits and underscores and nothing else."""
    out = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return out[:40] or "item"


def safe_file_name(name, fallback):
    """The artist's own file name, made safe to write in a folder of the
    kit's: no path, nothing Windows refuses, never one of the kit's files."""
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:120]
    if not name:
        return fallback
    if name.lower() in OWN_FILES or name.split(".")[0].upper() in WINDOWS_DEVICES:
        name = "_" + name
    return name


def _write(path, data):
    """Write whole or not at all — a kit closed mid-write must not leave a
    half file where a good one was."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _number(value, what, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise Refused(f"{what} has to be a number.") from None
    if not low <= value <= high:   # also turns NaN away
        raise Refused(f"{what} has to be between {low:g} and {high:g}.")
    return value


class Library:
    def __init__(self, data_dir):
        self.data = Path(data_dir)
        self.root = self.data / "library"
        self.bin = self.data / "trash"
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.data / "tmp", ignore_errors=True)   # last run's scratch

    # ---- reading -----------------------------------------------------------

    @staticmethod
    def _read(folder):
        """A folder's meta, or None if it is not a usable item."""
        try:
            item = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(item, dict) or not ID.match(str(item.get("id", ""))):
            return None
        if not (folder / str(item.get("file"))).is_file():
            return None
        # what v0.1.0 wrote, said the way this version says it
        if "original" not in item:
            item["original"] = "source.vox" if item.get("kind") == "vox" else "sprite.png"
        if item.get("kind") == "vox" and "size" not in item:
            fit = item.get("fit")
            item["size"] = "original" if fit is None else "fit"
            item["fitWide"] = item["fitLong"] = fit
        return item

    def items(self):
        """Every readable item, oldest first — the order they were added."""
        out = []
        for folder in self.root.iterdir():
            item = self._read(folder)
            if item is not None and item["id"] == folder.name:
                out.append(item)
        out.sort(key=lambda item: (item.get("added", 0), item["id"]))
        return out

    def trashed(self):
        """What is in the trash, the latest thrown first. `trashKey` names
        the entry: the same item can be in there more than once."""
        out = []
        if self.bin.is_dir():
            for folder in self.bin.iterdir():
                item = self._read(folder)
                if item is not None and ID.match(folder.name):
                    out.append({**item, "trashKey": folder.name})
        out.sort(key=lambda item: -item.get("trashed", 0))
        return out

    def _item(self, item_id):
        """(folder, meta) of an item on the shelf, or Refused."""
        folder = self.root / item_id if ID.match(str(item_id)) else None
        item = self._read(folder) if folder and folder.is_dir() else None
        if item is None:
            raise Refused("That file is not in the library any more.")
        return folder, item

    def folder_of(self, item_id):
        return self._item(item_id)[0]

    def file_path(self, item_id, name):
        """The path of the file an item is drawn from, or None."""
        try:
            folder, item = self._item(item_id)
        except Refused:
            return None
        if name != item["file"]:
            return None
        return folder / name

    # ---- adding ------------------------------------------------------------

    def _new_id(self, base):
        # an id in the trash is still taken: putting it back must not find
        # another item under its name
        candidate, n = base, 1
        while (self.root / candidate).exists() or (self.bin / candidate).exists():
            n += 1
            candidate = f"{base}_{n}"
        return candidate

    def _save(self, item_id, meta, files, added=None):
        folder = self.root / item_id
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            _write(folder / name, data)
        meta = {"id": item_id, "added": added or time.time(), **meta}
        _write(folder / "meta.json", json.dumps(meta, indent=1).encode("utf-8"))
        return meta

    def import_sprite(self, data, file_name, name, kind="sprite",
                      category="flowers", target=None):
        if kind not in ("sprite", "ground", "forest"):
            raise Refused(f"A sprite cannot be added as '{kind}'.")
        if category not in CATEGORIES:
            raise Refused(f"There is no shelf called '{category}'.")
        width, height = png_size(data)
        if max(width, height) > MAX_SPRITE_PIXELS:
            raise Refused(
                f"{file_name} is {width} x {height} px. The largest sprite the "
                f"game ships is 1024 px a side; the kit takes up to "
                f"{MAX_SPRITE_PIXELS}.")
        name = (name or "").strip() or Path(file_name).stem
        original = safe_file_name(file_name, "sprite.png")
        meta = {"name": name, "kind": kind, "category": category,
                "file": original, "source": file_name, "original": original,
                "width": width, "heightPx": height}
        if kind == "forest":
            if not target or not FOREST_TARGET.match(target):
                raise Refused("A forest sprite has to say which one it replaces, "
                              "like tree_07.")
            which, number = target.split("_")
            if int(number) >= FOREST_POOL[which]:
                raise Refused(f"The game has {FOREST_POOL[which]} {which} sprites, "
                              f"{which}_00 to {which}_{FOREST_POOL[which] - 1:02d}; "
                              f"there is no {target}.")
            # one replacement a forest sprite: a second one takes its place,
            # and the first goes to the trash, not away
            item_id = f"forest_{target}"
            if (self.root / item_id).exists():
                self._bin(item_id)
            meta["target"] = target
        else:
            # `x` for "the artist's": no id of the game's starts with it
            prefix = "xroad_" if kind == "ground" else "x_"
            item_id = self._new_id(prefix + slug(name))
        return self._save(item_id, meta, {original: data})

    # ---- voxel models --------------------------------------------------------

    def _scratch(self, data):
        """A .vox on disk for the converter, which reads paths. Named after
        its contents, so the steps of one ADD find the same file."""
        folder = self.data / "tmp"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (hashlib.sha1(data).hexdigest() + ".vox")
        if not path.is_file():
            _write(path, data)
        kept = sorted(folder.glob("*.vox"), key=lambda p: p.stat().st_mtime)
        for old in kept[:-3]:
            if old != path:
                old.unlink(missing_ok=True)
        return path

    @contextmanager
    def _converting(self, path, file_name):
        """The converter's own refusals, with the artist's file named in them
        instead of wherever the kit happens to keep it."""
        conv = converter()
        try:
            yield conv
        except conv.Refused as exc:
            raise Refused(str(exc).replace(Path(path).name, file_name)) from None
        except Refused:
            raise
        except (struct.error, IndexError, ValueError):
            raise Refused(f"{file_name} is damaged — it stops in the middle of "
                          f"a chunk.") from None

    def _models(self, data, file_name):
        """[{x, y, z, voxels}] for each model in the file."""
        parts = vox_parts(data)
        if parts is not None:
            # the chunk headers say all of this; no voxel needs reading
            return [{"x": x, "y": y, "z": z, "voxels": count}
                    for (x, y, z), count in (
                        (struct.unpack_from("<iii", size, 12),
                         struct.unpack_from("<i", xyzi, 12)[0])
                        for size, xyzi in parts[0])]
        path = self._scratch(data)
        with self._converting(path, file_name) as conv:
            models, _ = conv.read_vox(str(path))
        return [{"x": size[0], "y": size[1], "z": size[2], "voxels": len(voxels)}
                for size, voxels in models]

    def _mesh(self, data, file_name, mesh_id, model=0, turn=0, wide=None, long=None):
        """(mesh, facts) for one model of the .vox in `data`.

        `turn` is whole degrees. The converter writes quarter turns into the
        boxes; what is left over rides in the mesh as `turn`, which the game's
        painter adds to the camera for this one object. `wide` x `long` is a
        footprint in tiles to fit the model into, keeping its shape; without
        them it keeps the game's scale, 16 voxels to a tile.
        """
        turn = int(_number(turn, "The turn", 0, 360)) % 360
        if (wide is None) != (long is None):
            raise Refused("A fit needs both sides: how wide and how long.")
        if wide is not None:
            wide = _number(wide, "The width in tiles", MIN_FIT, MAX_FIT)
            long = _number(long, "The length in tiles", MIN_FIT, MAX_FIT)
        quarters, rest = divmod(turn, 90)
        if not isinstance(model, int) or isinstance(model, bool):
            raise Refused("Which model has to be a whole number.")
        # the one model on its own, where the file can be cut; else the file
        cut = one_model(data, model)
        count = None if cut is None else cut[1]
        path = self._scratch(data if cut is None else cut[0])
        index = model if cut is None else 0
        with self._converting(path, file_name) as conv:
            models, _ = conv.read_vox(str(path))
            count = len(models) if count is None else count
            if not 0 <= index < len(models):
                raise Refused(f"{file_name} has no model {model} — it holds {count}.")
            size, voxels = models[index]
            if not voxels:
                raise Refused(f"Model {model + 1} of {file_name} is empty.")
            placed = conv.turned(voxels, quarters)
            span_x = max(x for x, _, _ in placed) + 1
            span_y = max(y for _, y, _ in placed) + 1
            units = conv.DEFAULT_UNITS
            if wide is not None:
                # as large as fits both ways; the shape is the artist's
                units = max(span_x / wide, span_y / long)
            mesh = conv.convert(str(path), mesh_id, units=units, model=index,
                                turn=quarters)
        boxes = mesh["boxes"]
        if len(boxes) > MAX_BOXES:
            raise Refused(
                f"{file_name} needs {len(boxes)} boxes and the kit draws up to "
                f"{MAX_BOXES}. The heaviest model tried in the garden so far is "
                f"about 2000 — make it smaller, or simpler on the outside.")
        if rest:
            mesh["turn"] = rest
        facts = {"boxes": len(boxes), "tiles": mesh["tiles"],
                 "tilesWide": round(span_x / units, 4),
                 "tilesLong": round(span_y / units, 4),
                 "height": round(max(b["z"] + b["h"] for b in boxes), 4),
                 "model": model, "models": count, "modelSize": list(size),
                 "turn": turn, "size": "original" if wide is None else "fit",
                 "fitWide": wide, "fitLong": long}
        return mesh, facts

    def inspect_vox(self, data, file_name):
        """[{x, y, z, voxels}] for each model in the file."""
        return self._models(data, file_name)

    def preview_vox(self, data, file_name, model=0):
        """One model's mesh as it is in the file — the game's scale, not
        turned — for the dialog to show before anything is added."""
        return self._mesh(data, file_name, "preview", model)[0]

    def import_vox(self, data, file_name, name, category="outer", model=0,
                   turn=0, wide=None, long=None):
        if category not in CATEGORIES:
            raise Refused(f"There is no shelf called '{category}'.")
        name = (name or "").strip() or Path(file_name).stem
        # `house_`: how both renderers tell a building from a flower
        item_id = self._new_id("house_x_" + slug(name))
        mesh, facts = self._mesh(data, file_name, item_id, model, turn, wide, long)
        original = safe_file_name(file_name, "source.vox")
        meta = {"name": name, "kind": "vox", "category": category,
                "file": "mesh.json", "source": file_name, "original": original,
                **facts}
        return self._save(item_id, meta, {
            original: data,
            "mesh.json": json.dumps(mesh, separators=(",", ":")).encode("utf-8"),
        })

    def inspect_item(self, item_id):
        """What is in the .vox an added model was made from."""
        folder, item = self._vox_item(item_id)
        return self._models((folder / item["original"]).read_bytes(), item["source"])

    def preview_item(self, item_id, model=0):
        folder, item = self._vox_item(item_id)
        return self._mesh((folder / item["original"]).read_bytes(), item["source"],
                          "preview", model)[0]

    def _vox_item(self, item_id):
        folder, item = self._item(item_id)
        if item.get("kind") != "vox":
            raise Refused(f"{item.get('name', item_id)} is not a voxel model.")
        if not (folder / item["original"]).is_file():
            raise Refused(f"The kit's copy of {item['source']} is gone from "
                          f"{folder}, so the model cannot be made again.")
        return folder, item

    # ---- changing ------------------------------------------------------------

    def change(self, item_id, name=None, category=None, kind=None, model=None,
               turn=None, size=None, wide=None, long=None):
        """Make the same choices again for something already added. It keeps
        its id, so what stands in the garden changes where it stands."""
        folder, item = self._item(item_id)
        if category is not None and category not in CATEGORIES:
            raise Refused(f"There is no shelf called '{category}'.")
        changed = dict(item)
        if name is not None and name.strip():
            changed["name"] = name.strip()
        if category is not None:
            changed["category"] = category
        files = {}
        if item["kind"] == "vox":
            if size not in (None, "original", "fit"):
                raise Refused("A model is added at its original size or fitted to tiles.")
            size = size or item["size"]
            if size == "fit":
                wide = item.get("fitWide") if wide is None else wide
                long = item.get("fitLong") if long is None else long
                if wide is None or long is None:
                    raise Refused("A fit needs both sides: how wide and how long.")
            else:
                wide = long = None
            self._vox_item(item_id)
            mesh, facts = self._mesh(
                (folder / item["original"]).read_bytes(), item["source"], item_id,
                item.get("model", 0) if model is None else model,
                item.get("turn", 0) if turn is None else turn, wide, long)
            changed.update(facts)
            changed.pop("fit", None)   # v0.1.0's word for it
            files["mesh.json"] = json.dumps(mesh, separators=(",", ":")).encode("utf-8")
        elif kind is not None and kind != item["kind"]:
            if item["kind"] == "forest" or kind not in ("sprite", "ground"):
                raise Refused("A sprite stands or lies flat; a forest sprite is "
                              "added again to stand for another one.")
            changed["kind"] = kind
        changed["changed"] = time.time()
        changed.pop("id")
        added = changed.pop("added", None)
        return self._save(item_id, changed, files, added=added)

    # ---- the trash -------------------------------------------------------------

    def _bin(self, item_id):
        """Move an item's folder into the trash, whole."""
        folder, item = self._item(item_id)
        self.bin.mkdir(parents=True, exist_ok=True)
        key, n = item_id, 1
        while (self.bin / key).exists():
            n += 1
            key = f"{item_id}__{n}"
        item["trashed"] = time.time()
        _write(folder / "meta.json", json.dumps(item, indent=1).encode("utf-8"))
        os.replace(folder, self.bin / key)
        return {**item, "trashKey": key}

    def trash(self, item_id):
        """Take something off the shelf. Nothing is deleted: its folder, the
        artist's own file included, moves to the trash."""
        return self._bin(item_id)

    def _trashed(self, key):
        folder = self.bin / key if ID.match(str(key)) else None
        item = self._read(folder) if folder and folder.is_dir() else None
        if item is None:
            raise Refused("That is not in the trash any more.")
        return folder, item

    def restore(self, key):
        """Put something from the trash back on its shelf."""
        folder, item = self._trashed(key)
        if (self.root / item["id"]).exists():
            # only a forest sprite can find its place taken (one a target);
            # the one standing there now goes to the trash in its turn
            self._bin(item["id"])
        item.pop("trashed", None)
        _write(folder / "meta.json", json.dumps(item, indent=1).encode("utf-8"))
        os.replace(folder, self.root / item["id"])
        return item

    def delete(self, key):
        """Delete one thing in the trash for good — the kit's copy of the
        file with it."""
        folder, _ = self._trashed(key)
        shutil.rmtree(folder)

    def empty_trash(self):
        count = len(self.trashed())
        shutil.rmtree(self.bin, ignore_errors=True)
        return count

    # ---- what an older version left ---------------------------------------------

    def adopt(self, old_data):
        """Copy the library and garden an older version kept elsewhere into
        this one. Once, and only into an empty library: copies, never moves,
        so nothing can be lost if it is interrupted. Returns how many items."""
        note = self.data / ".adopted"
        old = Path(old_data)
        if note.exists() or not (old / "library").is_dir() or any(self.root.iterdir()):
            return 0
        if old.resolve() == self.data.resolve():
            return 0
        count = 0
        for folder in (old / "library").iterdir():
            if folder.is_dir() and ID.match(folder.name) and self._read(folder):
                try:
                    shutil.copytree(folder, self.root / folder.name)
                    count += 1
                except OSError:
                    shutil.rmtree(self.root / folder.name, ignore_errors=True)
        state = old / "state.json"
        if state.is_file() and not (self.data / "state.json").exists():
            try:
                shutil.copy2(state, self.data / "state.json")
            except OSError:
                pass
        note.write_text(f"{count} items copied from {old}\n", encoding="utf-8")
        return count

    # ---- the garden as last left --------------------------------------------

    def load_state(self):
        try:
            return (self.data / "state.json").read_bytes()
        except OSError:
            return None

    def save_state(self, data):
        try:
            json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Refused("That is not a saved garden.") from None
        _write(self.data / "state.json", data)
