// Everything the kit's screen shows and everything a press on it does, kept
// apart from the widgets so it can be driven without a window.
import 'dart:async';
import 'dart:convert' show jsonDecode, utf8;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:pixel_pomo/engine/garden_engine.dart';
import 'package:pixel_pomo/logic.dart';

import 'api.dart';
import 'kit.dart';

Future<ui.Image> decodeImage(Uint8List bytes) async {
  final codec = await ui.instantiateImageCodec(bytes);
  return (await codec.getNextFrame()).image;
}

class KitController extends ChangeNotifier {
  final KitApi api;

  /// Loads the game's own sprites and meshes. A test passes its own.
  final Future<SpriteBank> Function() loadBank;

  KitController(this.api, {this.loadBank = SpriteBank.load});

  /// Null until the game's art is loaded.
  SpriteBank? bank;

  /// Why the kit could not start, if it could not.
  String? fatal;

  List<ImportedFile> imported = [];

  /// What has been taken off the shelves and not yet deleted, latest first.
  List<ImportedFile> trashed = [];
  List<KitItem> palette = builtInItems();
  Garden garden = const Garden();
  KitView view = KitView.web;
  KitCategory category = KitCategory.flowers;

  /// The camera belongs to the kit, not to the view, so switching between the
  /// two looks keeps the angle the artist was studying.
  final GardenCamera camera = GardenCamera();

  /// What a click on a tile does: place [brushItem], erase, or nothing.
  KitItem? brushItem;
  bool erasing = false;
  bool get brushing => erasing || brushItem != null;

  /// The line under the garden. [statusIsError] paints it as a refusal.
  String status = '';
  bool statusIsError = false;

  /// From the launcher: its version, the folder the program is in, the folder
  /// the artist's files are in, and what kind of start this is (`installed`,
  /// `portable`, `source`). [online] is false when the page is open without a
  /// launcher behind it — the garden still works, but nothing can be added or
  /// remembered.
  String version = '', dataDir = '', programDir = '', build = '';
  bool online = false;

  /// Where an update stands. `available` lights the UPDATE button.
  UpdateStatus update = const UpdateStatus();

  /// Goes up each time something lands at the far end of a shelf, so the
  /// screen can bring it into view.
  int added = 0;

  /// The decoded picture of every imported sprite, for the shelf.
  final Map<String, ui.Image> pictures = {};

  // a forest sprite an import replaced, so removing the import brings it back
  final Map<String, ui.Image?> _forestOriginals = {};
  Timer? _saveSoon, _alive, _updatePoll;
  bool _disposed = false;

  Future<void> start() async {
    try {
      bank = await loadBank();
    } catch (e) {
      fatal = 'The game\'s sprites did not load: $e';
      notifyListeners();
      return;
    }
    try {
      final hello = await api.hello();
      version = hello['version'] as String? ?? '';
      dataDir = hello['dataDir'] as String? ?? '';
      programDir = hello['programDir'] as String? ?? '';
      build = hello['build'] as String? ?? '';
      online = true;
      final files = await api.library();
      for (final f in files) {
        try {
          await _install(f);
          imported.add(f);
        } catch (_) {
          // one unreadable file costs that one item, not the library
        }
      }
      trashed = await api.trash();
      final saved = await api.loadState();
      view = saved.view;
      category = saved.category;
      garden = saved.garden;
      // The page says it is open. The launcher only listens for this when it
      // had to fall back to an ordinary browser tab, which it cannot watch.
      _alive = Timer.periodic(const Duration(seconds: 10), (_) => api.hello().ignore());
      // Ask once, quietly, whether there is a newer kit: the button says so.
      // A machine that is offline simply keeps a plain UPDATE button.
      unawaited(api.checkUpdate().then(_setUpdate).catchError((Object _) {}));
    } on KitError catch (e) {
      online = false;
      _say('${e.message} Nothing you add will be kept.', error: true);
    }
    _refreshPalette();
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _saveSoon?.cancel();
    _alive?.cancel();
    _updatePoll?.cancel();
    super.dispose();
  }

  // ---- the shelf -------------------------------------------------------------

  List<KitItem> get shelf => [
        for (final item in palette)
          if (item.category == category) item
      ];

  void showCategory(KitCategory c) {
    category = c;
    _say('');
    _changed();
  }

  void pick(KitItem item) {
    // picking what is already on the brush puts the brush down
    brushItem = !erasing && brushItem?.id == item.id ? null : item;
    erasing = false;
    _say('');
    notifyListeners();
  }

  void pickEraser() {
    erasing = !erasing;
    brushItem = null;
    _say('');
    notifyListeners();
  }

  // ---- the garden ------------------------------------------------------------

  void tapTile(int index) {
    final item = brushItem;
    if (erasing) {
      garden = garden.clear(index);
    } else if (item != null) {
      final next = brush(garden, index, item);
      if (identical(next, garden)) {
        // the only refusal Garden.plant has: something that grows, on a path
        _say('${item.name} cannot stand on a path — that is the game\'s own rule.', error: true);
        notifyListeners();
        return;
      }
      garden = next;
    } else {
      return;
    }
    _say('');
    _changed();
  }

  void growGarden() {
    if (!canGrow(garden)) return;
    garden = garden.grow();
    _say('');
    _changed();
  }

  void shrinkGarden() {
    if (!canShrink(garden)) return;
    garden = shrink(garden);
    _say('');
    _changed();
  }

  void clearGarden() {
    garden = Garden(cols: garden.cols, rows: garden.rows);
    _say('');
    _changed();
  }

  void show(KitView v) {
    view = v;
    _say('');
    _changed();
  }

  // ---- adding files ------------------------------------------------------------

  Future<void> addVox(Uint8List bytes,
      {required String fileName,
      required String name,
      required KitCategory category,
      required int model,
      required int turn,
      double? wide,
      double? long}) async {
    final f = await api.importVox(bytes,
        fileName: fileName,
        name: name,
        category: category,
        model: model,
        turn: turn,
        wide: wide,
        long: long);
    await _added(f);
    _say(
        'Added ${f.name.toUpperCase()}: ${f.details}.'
        '${f.boxes > kHeavyBoxes ? ' That is a heavy model — no phone has been tried with one this size.' : ''}',
        error: f.boxes > kHeavyBoxes);
    notifyListeners();
  }

  Future<void> addSprite(Uint8List bytes,
      {required String fileName,
      required String name,
      required ImportKind kind,
      required KitCategory category,
      String? target}) async {
    final f = await api.importSprite(bytes,
        fileName: fileName, name: name, kind: kind, category: category, target: target);
    await _added(f);
    // a second sprite for the same forest tree sent the first to the trash
    if (f.kind == ImportKind.forest) trashed = await api.trash();
    _say(f.kind == ImportKind.forest
        ? 'Added ${f.name.toUpperCase()} — it now grows in the woods wherever ${f.target} did.'
        : 'Added ${f.name.toUpperCase()}. Click a tile to place it.');
    notifyListeners();
  }

  Future<void> _added(ImportedFile f) async {
    await _install(f);
    _put(f);
    _refreshPalette();
    final item = itemFor(f);
    if (item != null) {
      category = item.category;
      brushItem = item;
      erasing = false;
      added++;
    }
    _changed();
  }

  /// [f] into the list of what is added, in the place of whatever had its id.
  void _put(ImportedFile f) {
    final at = imported.indexWhere((old) => old.id == f.id);
    imported = at < 0
        ? [...imported, f]
        : [
            for (final old in imported)
              if (old.id == f.id) f else old
          ];
  }

  // ---- changing what was added -----------------------------------------------

  /// Make the choices again for [f]. It keeps its id, so every one of it
  /// standing in the garden changes where it stands.
  Future<void> changeItem(ImportedFile f,
      {String? name,
      KitCategory? category,
      ImportKind? kind,
      int? model,
      int? turn,
      bool? fitted,
      double? wide,
      double? long}) async {
    final next = await api.change(f.id,
        name: name,
        category: category,
        kind: kind,
        model: model,
        turn: turn,
        fitted: fitted,
        wide: wide,
        long: long);
    _uninstall(f);
    await _install(next);
    _put(next);
    _refreshPalette();
    final item = itemFor(next);
    if (item != null) {
      if (brushItem?.id == next.id) brushItem = item;
      this.category = item.category;
    }
    _say('Changed ${next.name.toUpperCase()}: ${next.details}.');
    _changed();
  }

  // ---- the trash ---------------------------------------------------------------

  /// Take [f] off its shelf and out of the garden. Nothing is deleted: the
  /// launcher moves its folder, the artist's file included, to the trash.
  Future<void> moveToTrash(ImportedFile f) async {
    await api.moveToTrash(f.id);
    _uninstall(f);
    imported = [
      for (final old in imported)
        if (old.id != f.id) old
    ];
    if (brushItem?.id == f.id) brushItem = null;
    trashed = await api.trash();
    _refreshPalette();
    _say('${f.name.toUpperCase()} is in the trash. TRASH, top right, puts it back or deletes it.');
    _changed();
  }

  /// Put something from the trash back on its shelf.
  Future<void> restore(ImportedFile t) async {
    final f = await api.restore(t.trashKey!);
    await _install(f);
    _put(f);
    trashed = await api.trash();
    _refreshPalette();
    final item = itemFor(f);
    if (item != null) {
      category = item.category;
      added++;
    }
    _say('${f.name.toUpperCase()} is back on its shelf.');
    _changed();
  }

  /// Delete one thing in the trash for good — the kit's copy of its file too.
  Future<void> deleteForever(ImportedFile t) async {
    await api.deleteForever(t.trashKey!);
    trashed = await api.trash();
    _say('${t.name.toUpperCase()} is deleted.');
    notifyListeners();
  }

  Future<void> emptyTrash() async {
    await api.emptyTrash();
    trashed = await api.trash();
    _say('The trash is empty.');
    notifyListeners();
  }

  // ---- folders and updates -----------------------------------------------------

  Future<void> openFolder([String which = 'files', String? id]) async {
    try {
      await api.openFolder(which, id);
    } on KitError catch (e) {
      _say(e.message, error: true);
      notifyListeners();
    }
  }

  void _setUpdate(UpdateStatus u) {
    if (_disposed) return;
    update = u;
    notifyListeners();
  }

  /// Ask the release page again. The answer is in [update].
  Future<void> checkUpdate() async {
    _setUpdate(UpdateStatus(state: 'checking', version: version));
    try {
      _setUpdate(await api.checkUpdate());
    } on KitError catch (e) {
      _setUpdate(UpdateStatus(state: 'failed', version: version, message: e.message));
    }
  }

  /// Download the update. When it is ready the launcher closes this window
  /// and the new kit opens; until then [update] carries the progress.
  Future<void> applyUpdate() async {
    try {
      _setUpdate(await api.applyUpdate());
    } on KitError catch (e) {
      _setUpdate(UpdateStatus(
          state: 'failed', version: version, latest: update.latest, message: e.message));
      return;
    }
    _updatePoll?.cancel();
    _updatePoll = Timer.periodic(const Duration(milliseconds: 500), (timer) async {
      try {
        final now = await api.updateStatus();
        _setUpdate(now);
        if (now.state != 'downloading') timer.cancel();
      } on KitError {
        timer.cancel(); // the launcher has gone: the new kit is on its way
      }
    });
  }

  // ---- the game's sprite bank ----------------------------------------------------

  /// Hand an imported file to the game's sprite bank under the key its painter
  /// looks it up by.
  Future<void> _install(ImportedFile f) async {
    final sprites = bank!;
    final bytes = await api.fileOf(f);
    if (f.kind == ImportKind.vox) {
      sprites.meshes[f.id] =
          BoxMesh.fromJson(jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>);
      return;
    }
    final image = await decodeImage(bytes);
    pictures[f.id] = image;
    switch (f.kind) {
      case ImportKind.sprite:
        sprites.images['flower_${f.id}'] = image; // SpriteBank.flower's key
      case ImportKind.ground:
        sprites.images[f.id] = image; // SpriteBank.object's key
      case ImportKind.forest:
        final target = f.target!;
        if (!_forestOriginals.containsKey(target)) {
          _forestOriginals[target] = sprites.images[target];
        }
        sprites.images[target] = image;
      case ImportKind.vox:
        break;
    }
  }

  void _uninstall(ImportedFile f) {
    final sprites = bank!;
    pictures.remove(f.id);
    switch (f.kind) {
      case ImportKind.vox:
        sprites.meshes.remove(f.id);
      case ImportKind.sprite:
        sprites.images.remove('flower_${f.id}');
      case ImportKind.ground:
        sprites.images.remove(f.id);
      case ImportKind.forest:
        final original = _forestOriginals.remove(f.target);
        if (original != null) sprites.images[f.target!] = original;
    }
  }

  void _refreshPalette() {
    registerImported(imported);
    palette = paletteOf(imported);
    garden = dropUnknown(garden, {for (final item in palette) item.id});
  }

  /// Say that something slow has started, so the window is not simply still.
  /// Empty clears it.
  void working(String what) {
    _say(what);
    notifyListeners();
  }

  void _say(String text, {bool error = false}) {
    status = text;
    statusIsError = error;
  }

  /// Repaint, and write the garden down shortly — not on every tile of a
  /// brush stroke.
  void _changed() {
    notifyListeners();
    if (!online) return;
    _saveSoon?.cancel();
    _saveSoon = Timer(const Duration(milliseconds: 400), () {
      api
          .saveState(KitState(garden: garden, view: view, category: category))
          .catchError((Object _) {});
    });
  }
}
