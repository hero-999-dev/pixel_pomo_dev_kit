// What the Dev Kit knows that the game does not: the list of things an artist
// can put in the garden (the game's own catalogue plus whatever they imported),
// which shelf of the market each one sits on, and the few garden edits the game
// never needed — a garden here is free, can shrink, and is edited with a brush.
//
// Pure Dart, no widgets and no browser, so all of it is unit-tested.
import 'dart:convert' show jsonDecode, jsonEncode;

import 'package:pixel_pomo/logic.dart';
import 'package:pixel_pomo/strings.dart' show t;

/// The market's four shelves, in the market's own order (ShopScreen's tabs).
enum KitCategory {
  flowers('catFlowers'),
  outer('catOuter'),
  inner('catInner'),
  pets('catPets');

  /// The game's own string key for the tab, so the kit never names a shelf
  /// differently from the market.
  final String labelKey;
  const KitCategory(this.labelKey);

  String get label => t('en', labelKey);

  static KitCategory parse(String? name) =>
      values.firstWhere((c) => c.name == name, orElse: () => outer);
}

/// How an imported file is used.
enum ImportKind {
  /// A 2D sprite that stands on its tile and faces the camera, like a flower.
  sprite,

  /// A 2D sprite laid flat on the ground, like a path.
  ground,

  /// A voxel model, drawn as real geometry that turns with the garden.
  vox,

  /// A 2D sprite that takes the place of one of the forest's own.
  forest;

  static ImportKind? parse(String? name) {
    for (final k in values) {
      if (k.name == name) return k;
    }
    return null;
  }
}

/// One thing that can be put on a garden tile.
class KitItem {
  /// What the garden stores for a tile holding it.
  final String id;
  final String name;
  final KitCategory category;

  /// Real geometry (true) or a flat sprite (false) — the 2D / 3D label.
  final bool is3d;

  /// Lies on the ground under whatever stands on the tile.
  final bool isGround;

  /// The game's own thumbnail, `assets/objects/<thumb>.png`. Null for an
  /// imported item, which is drawn from the file itself.
  final String? thumb;

  /// Set when the artist added it; null for the game's own objects.
  final ImportedFile? imported;

  const KitItem({
    required this.id,
    required this.name,
    required this.category,
    required this.is3d,
    this.isGround = false,
    this.thumb,
    this.imported,
  });

  String get dimLabel => is3d ? '3D' : '2D';
}

/// A file the artist added, as the launcher's library records it — every
/// choice made when it was added included, so the choices can be read back
/// and made again.
class ImportedFile {
  final String id;
  final String name;
  final ImportKind kind;
  final KitCategory category;

  /// The file to fetch for it: the sprite itself, or `mesh.json`.
  final String file;

  /// The file the artist picked, by its own name; and the name the kit's copy
  /// of it is kept under in the item's folder.
  final String source, original;

  /// For [ImportKind.forest]: the forest sprite it stands in for, e.g. `tree_07`.
  final String? target;

  /// Voxel models only: how many boxes the engine draws for it, and its size
  /// in tiles — the wider side, then each side and the height.
  final int boxes;
  final double tiles, tilesWide, tilesLong, height;

  /// Voxel models only, the choices: which model of how many in the file and
  /// its size in voxels, the turn in degrees, and the footprint it was fitted
  /// into ([fitted] false: its original size, 16 voxels to a tile). [models]
  /// is 0 where the record does not say — v0.1.0 did not write it down.
  final int model, models, turn;
  final List<int> modelSize;
  final bool fitted;
  final double fitWide, fitLong;

  /// Sprites only: the picture's size in pixels.
  final int width, heightPx;

  /// When it was added, in seconds since 1970. 0 if the record does not say.
  final double added;

  /// Set for something in the trash: the name of its entry there.
  final String? trashKey;

  const ImportedFile({
    required this.id,
    required this.name,
    required this.kind,
    required this.category,
    required this.file,
    this.source = '',
    this.original = '',
    this.target,
    this.boxes = 0,
    this.tiles = 0,
    this.tilesWide = 0,
    this.tilesLong = 0,
    this.height = 0,
    this.model = 0,
    this.models = 0,
    this.turn = 0,
    this.modelSize = const [],
    this.fitted = false,
    this.fitWide = 0,
    this.fitLong = 0,
    this.width = 0,
    this.heightPx = 0,
    this.added = 0,
    this.trashKey,
  });

  /// Null for a record this version cannot use, so one unreadable entry costs
  /// one missing item rather than the whole library.
  static ImportedFile? fromJson(Object? json) {
    if (json is! Map) return null;
    final kind = ImportKind.parse(json['kind'] as String?);
    final id = json['id'], file = json['file'];
    if (kind == null || id is! String || file is! String || !validId(id)) return null;
    num n(String key) => json[key] is num ? json[key] as num : 0;
    final tiles = n('tiles').toDouble();
    final size = json['modelSize'];
    return ImportedFile(
      id: id,
      name: (json['name'] as String?)?.trim().isNotEmpty == true ? json['name'] as String : id,
      kind: kind,
      category: KitCategory.parse(json['category'] as String?),
      file: file,
      source: json['source'] as String? ?? '',
      original: json['original'] as String? ?? '',
      target: json['target'] as String?,
      boxes: n('boxes').toInt(),
      tiles: tiles,
      // a record from before the sides were written down has only the wider
      tilesWide: json['tilesWide'] is num ? n('tilesWide').toDouble() : tiles,
      tilesLong: json['tilesLong'] is num ? n('tilesLong').toDouble() : tiles,
      height: n('height').toDouble(),
      model: n('model').toInt(),
      models: n('models').toInt(),
      turn: n('turn').toInt(),
      modelSize: size is List && size.length == 3 && size.every((v) => v is num)
          ? [for (final v in size) (v as num).toInt()]
          : const [],
      fitted: json['size'] == 'fit',
      fitWide: n('fitWide').toDouble(),
      fitLong: n('fitLong').toDouble(),
      width: n('width').toInt(),
      heightPx: n('heightPx').toInt(),
      added: n('added').toDouble(),
      trashKey: json['trashKey'] as String?,
    );
  }

  /// One line under the name in a list.
  String get details => switch (kind) {
        ImportKind.vox =>
          '$boxes boxes · ${trimNumber(tilesWide)} x ${trimNumber(tilesLong)} tiles · ${trimNumber(height)} tall',
        ImportKind.forest => '${width}x$heightPx px · replaces $target',
        _ => '${width}x$heightPx px',
      };

  /// What it is used as, in the words of the ADD dialog.
  String get useLabel => switch (kind) {
        ImportKind.sprite => 'STANDING',
        ImportKind.ground => 'FLAT GROUND',
        ImportKind.forest => 'FOREST ${(target ?? '').toUpperCase()}',
        ImportKind.vox => '3D MODEL',
      };

  /// The size choice, as it was made.
  String get sizeLabel => fitted
      ? 'FIT ${trimNumber(fitWide)} x ${trimNumber(fitLong)} TILES'
      : 'ORIGINAL SIZE';

  /// Every choice made when it was added, written out: the rows of DETAILS.
  List<(String, String)> get choices => [
        ('FILE', source.isEmpty ? original : source),
        if (kind == ImportKind.vox) ...[
          (
            'MODEL',
            '${model + 1}${models > 0 ? ' of $models' : ''}'
                '${modelSize.length == 3 ? ' (${modelSize.join('x')} voxels)' : ''}'
          ),
          ('SIZE', sizeLabel),
          ('COMES OUT', '${trimNumber(tilesWide)} x ${trimNumber(tilesLong)} tiles, ${trimNumber(height)} tall'),
          ('TURN', '$turn degrees'),
          ('BOXES', '$boxes'),
        ] else ...[
          ('PICTURE', '$width x $heightPx px'),
          ('USE', useLabel),
        ],
        if (kind != ImportKind.forest) ('SHELF', category.label),
      ];
}

/// A number as an artist would write it: 2, 1.5, 0.33 — never 2.0000.
String trimNumber(double v) {
  final text = v.toStringAsFixed(2);
  return text.contains('.') ? text.replaceFirst(RegExp(r'\.?0+$'), '') : text;
}

// ---- a voxel model's size ---------------------------------------------------

/// The smallest and largest footprint side a model is fitted to, in tiles —
/// the launcher's own limits (library.MIN_FIT / MAX_FIT).
const double kMinFit = 0.25, kMaxFit = 16;

/// What a model comes out as, for the choices in the ADD dialog. [baseWide] x
/// [baseLong] is its footprint in tiles at its original size and unturned.
///
/// The launcher's arithmetic, kept in step with `Library._mesh`: the quarter
/// turns in [turn] swap the two sides, and a fit makes the model as large as
/// goes into [wide] x [long] both ways, keeping its shape. What is left of the
/// turn after the quarters is not measured: the model overhangs by a little.
({double wide, double long, double scale}) voxFootprint(double baseWide, double baseLong,
    {int turn = 0, double? wide, double? long}) {
  final quarter = (turn % 360) ~/ 90;
  final w = quarter.isOdd ? baseLong : baseWide, l = quarter.isOdd ? baseWide : baseLong;
  if (wide == null || long == null || w <= 0 || l <= 0) return (wide: w, long: l, scale: 1);
  final scale = wide / w < long / l ? wide / w : long / l;
  return (wide: w * scale, long: l * scale, scale: scale);
}

/// A size typed into a box, or null if it is not one the kit can use.
double? parseFit(String text) {
  final v = double.tryParse(text.trim().replaceAll(',', '.'));
  return v != null && v >= kMinFit && v <= kMaxFit ? v : null;
}

/// A turn typed into a box: whole degrees from 0 to 360, or null.
int? parseTurn(String text) {
  final v = int.tryParse(text.trim());
  return v != null && v >= 0 && v <= 360 ? v % 360 : null;
}

/// A garden stores a tile as `index:id`, joins a ground and a prop with `+`,
/// and marks a flower's variant with `~`, one tile to a line — so an id may
/// hold none of those, or a saved garden would read back as something else.
bool validId(String id) => RegExp(r'^[a-z0-9_]+$').hasMatch(id);

/// A box count past which a model is worth a warning. The four test models run
/// from 350 to 2000 boxes and draw smoothly; nothing bigger has been tried on a
/// phone, so this is where the kit says so rather than a measured limit.
const int kHeavyBoxes = 2500;

/// Everything the game itself ships, in the market's order: each flower (every
/// drawn variant of it, since the point here is to look at the art), then the
/// paths, fences and buildings.
List<KitItem> builtInItems() => [
      for (final f in Flowers.all)
        if (Flowers.variantsFor(f.id) > 1)
          for (var v = 0; v < Flowers.variantsFor(f.id); v++)
            KitItem(
                id: '${f.id}~$v',
                name: '${f.nameIn('en').toUpperCase()} ${v + 1}',
                category: KitCategory.flowers,
                is3d: false,
                thumb: 'flower_${f.id}_$v')
        else
          KitItem(
              id: f.id,
              name: f.nameIn('en').toUpperCase(),
              category: KitCategory.flowers,
              is3d: false,
              thumb: 'flower_${f.id}'),
      for (final id in Placeables.roadIds)
        KitItem(
            id: id,
            name: t('en', id),
            category: KitCategory.outer,
            is3d: false,
            isGround: true,
            thumb: id),
      // a fence is posts and rails — geometry, like a building
      for (final id in Placeables.fenceIds)
        KitItem(id: id, name: t('en', id), category: KitCategory.outer, is3d: true, thumb: id),
      for (final id in Placeables.houseIds)
        KitItem(id: id, name: t('en', id), category: KitCategory.outer, is3d: true, thumb: id),
    ];

/// The palette entry for an imported file, or null for one that is not placed
/// by hand (a forest sprite shows in the woods, not on a shelf).
KitItem? itemFor(ImportedFile f) => f.kind == ImportKind.forest
    ? null
    : KitItem(
        id: f.id,
        name: f.name.toUpperCase(),
        category: f.category,
        is3d: f.kind == ImportKind.vox,
        isGround: f.kind == ImportKind.ground,
        imported: f);

/// The whole palette: the game's objects, then the artist's, each on its shelf.
List<KitItem> paletteOf(List<ImportedFile> imported) => [
      ...builtInItems(),
      for (final f in imported)
        ?itemFor(f),
    ];

/// Tell the game's own rules about the imported grounds and models, so its
/// painter lays the one flat and draws the other as geometry. Replaces whatever
/// was registered before.
void registerImported(List<ImportedFile> imported) {
  Placeables.importedRoadIds
    ..clear()
    ..addAll([
      for (final f in imported)
        if (f.kind == ImportKind.ground) f.id
    ]);
  Placeables.importedHouseIds
    ..clear()
    ..addAll([
      for (final f in imported)
        if (f.kind == ImportKind.vox) f.id
    ]);
}

// ---- the garden -------------------------------------------------------------

/// The largest plot the kit grows to: six EXPANDs from the game's 4x8. The game
/// has no ceiling of its own, only a rising price.
const int kMaxCols = 16;

bool canGrow(Garden g) => g.cols + 2 <= kMaxCols;

/// The game's smallest garden is the one it starts with.
bool canShrink(Garden g) =>
    g.cols - 2 >= Economy.baseGardenCols && g.rows - 4 >= Economy.baseGardenRows;

/// Undo one [Garden.grow]: take a tile off each side and two off each end,
/// keeping what stands in the middle where it is. Whatever stood on the rim
/// that goes is gone with it. The game never shrinks a garden; the kit does,
/// to look at the same planting at every size.
Garden shrink(Garden g) {
  if (!canShrink(g)) return g;
  final nc = g.cols - 2, nr = g.rows - 4;
  final kept = <int, String>{};
  g.tiles.forEach((index, id) {
    final c = index % g.cols - 1, r = index ~/ g.cols - 2;
    if (c >= 0 && c < nc && r >= 0 && r < nr) kept[r * nc + c] = id;
  });
  return Garden(cols: nc, rows: nr, tiles: kept);
}

/// Brush [item] onto tile [index]. Brushing a tile with what it already holds
/// takes it off again; otherwise the game's own layering rules decide
/// ([Garden.plant]) — so a flower is refused on a path here exactly as it is in
/// the game, and the garden comes back unchanged.
Garden brush(Garden g, int index, KitItem item) {
  if (!g.isValidIndex(index)) return g;
  final (road, prop) = switch (g.tiles[index]) {
    final value? => Placeables.split(value),
    null => (null, null),
  };
  if (item.isGround && road == item.id) return _put(g, index, null, prop);
  if (!item.isGround && prop == item.id) return _put(g, index, road, null);
  return g.plant(index, item.id);
}

Garden _put(Garden g, int index, String? road, String? prop) {
  if (road == null && prop == null) return g.clear(index);
  return Garden(
      cols: g.cols, rows: g.rows, tiles: {...g.tiles, index: Placeables.combine(road, prop)});
}

/// Take every tile off that holds something not in [known] — the ids of
/// [paletteOf]. A garden saved with an imported model in it still names that
/// model after the file is removed; left there it would be an invisible thing
/// occupying a tile.
Garden dropUnknown(Garden g, Set<String> known) {
  var changed = false;
  final tiles = <int, String>{};
  g.tiles.forEach((index, value) {
    final parts = [
      for (final part in value.split('+'))
        if (known.contains(part)) part
    ];
    if (parts.length != value.split('+').length) changed = true;
    if (parts.isNotEmpty) tiles[index] = parts.join('+');
  });
  return changed ? Garden(cols: g.cols, rows: g.rows, tiles: tiles) : g;
}

// ---- what is remembered between runs ----------------------------------------

/// Which of the two looks the garden is shown in.
enum KitView {
  /// The whole stage, wide — the garden as the browser build shows it.
  web,

  /// A phone's upright screen, at a phone's own size in logical pixels.
  mobile;

  static KitView parse(String? name) => name == 'mobile' ? mobile : web;
}

/// The logical screen the MOBILE look is laid out at: a current tall Android
/// phone (the Pixel 8's 412x915). The frame is scaled to fit the window, so
/// everything in it keeps a phone's proportions.
const double kPhoneWidth = 412, kPhoneHeight = 915;

class KitState {
  final Garden garden;
  final KitView view;
  final KitCategory category;
  const KitState(
      {this.garden = const Garden(), this.view = KitView.web, this.category = KitCategory.flowers});

  String encode() => jsonEncode(
      {'garden': garden.encode(), 'view': view.name, 'category': category.name});

  /// Anything unreadable falls back to a fresh kit rather than failing to open.
  static KitState decode(String? text) {
    if (text == null || text.trim().isEmpty) return const KitState();
    try {
      final json = jsonDecode(text);
      if (json is! Map) return const KitState();
      return KitState(
        garden: Garden.decode(json['garden'] as String?),
        view: KitView.parse(json['view'] as String?),
        category: KitCategory.values.firstWhere((c) => c.name == json['category'],
            orElse: () => KitCategory.flowers),
      );
    } catch (_) {
      return const KitState();
    }
  }
}

// ---- reading a file's name --------------------------------------------------

/// What an Art Kit export is, told from the name it was exported under.
///
/// The Art Kit writes an engine sprite as `flower_<species>.png`,
/// `flower_<species>_<model>.png`, or — for the woods — `tree_07.png`,
/// `bush_03.png`, `rock_01.png`. Anything else is the artist's own name and
/// stands like a flower until they say otherwise.
({ImportKind kind, String name, String? target}) guessSprite(String fileName) {
  final base = fileName.replaceFirst(RegExp(r'\.[A-Za-z0-9]+$'), '').toLowerCase();
  final forest = RegExp(r'^(tree|bush|rock)_(\d{1,2})$').firstMatch(base);
  if (forest != null) {
    final target = '${forest[1]}_${forest[2]!.padLeft(2, '0')}';
    return (kind: ImportKind.forest, name: target, target: target);
  }
  final flower = RegExp(r'^flower_(.+?)(?:_(\d+))?$').firstMatch(base);
  if (flower != null) {
    final model = flower[2];
    return (
      kind: ImportKind.sprite,
      name: model == null ? flower[1]! : '${flower[1]} ${int.parse(model) + 1}',
      target: null,
    );
  }
  // A ground says so somewhere in its name: the game's own are `road_<kind>`,
  // and the Art Kit exports a drawing under the artist's name for it —
  // `wood_path.png`, `concrete.png`.
  const groundWords = {'road', 'path', 'floor', 'ground', 'tile', 'tiles', 'concrete', 'pavement'};
  final flat = base.split(RegExp(r'[^a-z0-9]+')).any(groundWords.contains);
  return (kind: flat ? ImportKind.ground : ImportKind.sprite, name: base, target: null);
}

/// A .vox file's name without its extension.
String voxName(String fileName) =>
    fileName.replaceFirst(RegExp(r'\.vox$', caseSensitive: false), '');
