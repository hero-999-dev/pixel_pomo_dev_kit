// The kit's screen, driven by presses, with a launcher that is a few canned
// answers instead of a program.
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/gestures.dart' show kSecondaryButton;
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pixel_pomo/engine/garden_engine.dart';
import 'package:pixel_pomo/engine/garden_view.dart';
import 'package:pixel_pomo/logic.dart';
import 'package:pixel_pomo/pixel.dart';
import 'package:pixel_pomo_dev_kit/api.dart';
import 'package:pixel_pomo_dev_kit/controller.dart';
import 'package:pixel_pomo_dev_kit/dialogs.dart';
import 'package:pixel_pomo_dev_kit/kit.dart';
import 'package:pixel_pomo_dev_kit/main.dart';
import 'package:pixel_pomo_dev_kit/pick.dart';
import 'package:pixel_pomo_dev_kit/vox_preview.dart';

/// A launcher with [items] in its library and [state] saved; it records what
/// the page asks of it, and keeps a trash, a converter and a release page as
/// simple as a test needs them.
class FakeLauncher {
  final List<Map<String, dynamic>> items;
  final List<Map<String, dynamic>> trash = [];
  String? state;
  final List<String> saved = [];
  final List<String> asked = []; // "METHOD /path?query" of everything but hello
  final List<String> logged = [];
  bool down;

  /// What the release page says: null is "nothing published" (a 404).
  String? latest;
  bool canUpdate = true;
  String updateState = 'idle';

  /// Holds the converter's answers back until a test completes it.
  Completer<void>? converting;

  /// A model the converter refuses, by its index.
  int? tooHeavy;
  FakeLauncher(
      {List<Map<String, dynamic>> items = const [], this.state, this.down = false, this.latest})
      : items = [...items];

  static Map<String, dynamic> meshOf(String id, [double side = 1]) => {
        'id': id,
        'tiles': side,
        'boxes': [
          {'x': 0, 'y': 0, 'z': 0, 'w': side, 'd': side / 2, 'h': 1, 'side': '#805030', 'top': '#A07040'}
        ]
      };

  static const models = [
    {'x': 16, 'y': 8, 'z': 16, 'voxels': 2048},
    {'x': 32, 'y': 16, 'z': 8, 'voxels': 4096},
  ];

  Map<String, dynamic> _update() => {
        'state': updateState,
        'version': '9.9.9',
        'latest': latest ?? '',
        'notes': latest == null ? '' : 'A better kit.',
        'message': updateState == 'failed' ? 'No version of the Dev Kit has been published yet.' : '',
        'progress': updateState == 'downloading' ? 0.4 : 0.0,
        'canUpdate': canUpdate,
        'page': 'https://example.test/releases',
      };

  Future<http.Response> answer(http.Request r) async {
    if (down) throw http.ClientException('connection refused');
    final path = r.url.path, q = r.url.queryParameters;
    http.Response json(Object body, [int status = 200]) =>
        http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});
    if (path == '/api/hello') {
      return json({
        'app': 'pixel-pomo-dev-kit', 'version': '9.9.9', 'dataDir': 'D:\\kit\\Files',
        'programDir': 'D:\\kit', 'build': 'installed', 'trash': trash.length,
      });
    }
    asked.add('${r.method} $path${r.url.hasQuery ? '?${r.url.query}' : ''}');
    if (path == '/api/library') return json({'items': items});
    if (path == '/api/state' && r.method == 'GET') {
      return state == null ? json({'error': 'none'}, 404) : http.Response(state!, 200);
    }
    if (path == '/api/state' && r.method == 'PUT') {
      saved.add(r.body);
      return json({'ok': true});
    }
    if (path == '/api/log') {
      logged.add(r.body);
      return json({'ok': true});
    }
    if (path == '/api/open-folder') return json({'ok': true});

    // ---- the converter
    if (path == '/api/inspect/vox' || path.startsWith('/api/inspect/item/')) {
      return json({'models': models});
    }
    if (path == '/api/preview/vox' || path.startsWith('/api/preview/item/')) {
      await converting?.future;
      final model = int.parse(q['model'] ?? '0');
      if (model == tooHeavy) return json({'error': 'That model needs 27601 boxes.'}, 400);
      return json(meshOf('preview', model == 0 ? 1 : 2));
    }
    if (path == '/api/import/vox') {
      await converting?.future;
      final item = <String, dynamic>{
        'id': 'house_x_${q['name']!.toLowerCase()}', 'name': q['name'], 'kind': 'vox',
        'category': q['category'], 'file': 'mesh.json', 'source': q['file'],
        'original': q['file'], 'boxes': 1, 'tiles': 1.0, 'tilesWide': 1.0, 'tilesLong': 0.5,
        'height': 1.0, 'model': int.parse(q['model']!), 'models': 2,
        'modelSize': [16, 8, 16], 'turn': int.parse(q['turn']!),
        'size': q.containsKey('wide') ? 'fit' : 'original',
        'fitWide': q.containsKey('wide') ? double.parse(q['wide']!) : null,
        'fitLong': q.containsKey('long') ? double.parse(q['long']!) : null,
      };
      items.add(item);
      return json(item);
    }
    if (path.startsWith('/api/change/')) {
      final id = path.split('/').last;
      final at = items.indexWhere((i) => i['id'] == id);
      if (at < 0) return json({'error': 'That file is not in the library any more.'}, 400);
      final next = {...items[at]};
      for (final key in ['name', 'category', 'kind', 'size']) {
        if (q.containsKey(key)) next[key] = q[key];
      }
      for (final key in ['model', 'turn']) {
        if (q.containsKey(key)) next[key] = int.parse(q[key]!);
      }
      if (q['size'] == 'fit') {
        next['fitWide'] = double.parse(q['wide']!);
        next['fitLong'] = double.parse(q['long']!);
      }
      items[at] = next;
      return json(next);
    }

    // ---- the trash
    if (path == '/api/trash' && r.method == 'GET') return json({'items': trash});
    if (path == '/api/trash' && r.method == 'DELETE') {
      final count = trash.length;
      trash.clear();
      return json({'deleted': count});
    }
    if (path.startsWith('/api/trash/') && r.method == 'POST') {
      final id = path.split('/').last;
      final at = items.indexWhere((i) => i['id'] == id);
      if (at < 0) return json({'error': 'That file is not in the library any more.'}, 400);
      final thrown = {...items.removeAt(at), 'trashKey': id};
      trash.insert(0, thrown);
      return json(thrown);
    }
    if (path.startsWith('/api/trash/') && r.method == 'DELETE') {
      trash.removeWhere((t) => t['trashKey'] == path.split('/').last);
      return json({'ok': true});
    }
    if (path.startsWith('/api/restore/')) {
      final at = trash.indexWhere((t) => t['trashKey'] == path.split('/').last);
      if (at < 0) return json({'error': 'That is not in the trash any more.'}, 400);
      final back = {...trash.removeAt(at)}..remove('trashKey');
      items.add(back);
      return json(back);
    }

    // ---- the release page
    if (path == '/api/update') return json(_update());
    if (path == '/api/update/check') {
      updateState = latest == null ? 'failed' : (latest == '9.9.9' ? 'none' : 'available');
      return json(_update());
    }
    if (path == '/api/update/apply') {
      if (!canUpdate) return json({'error': 'Only the installed Dev Kit can update itself.'}, 400);
      updateState = 'downloading';
      return json(_update());
    }

    if (path.endsWith('/mesh.json')) return json(meshOf(path.split('/')[2]));
    return json({'error': 'the fake launcher has no $path'}, 404);
  }

  /// Everything the page asked for under [prefix].
  List<String> asks(String prefix) => [
        for (final a in asked)
          if (a.startsWith(prefix)) a
      ];

  KitController controller() => KitController(
      KitApi(Uri.parse('http://127.0.0.1:8791/'), MockClient(answer)),
      loadBank: () async => SpriteBank({}, {}));
}

Map<String, dynamic> get cafe => {
      'id': 'house_x_cafe', 'name': 'Cafe', 'kind': 'vox', 'category': 'outer',
      'file': 'mesh.json', 'source': 'cafe.vox', 'original': 'cafe.vox', 'boxes': 1,
      'tiles': 1.0, 'tilesWide': 1.0, 'tilesLong': 0.5, 'height': 1.0, 'model': 0, 'models': 2,
      'modelSize': [16, 8, 16], 'turn': 30, 'size': 'fit', 'fitWide': 1.0, 'fitLong': 3.0,
    };

/// Stand in for the file dialog: the next ADD gets [name].
void picking(String name) {
  pickFilesForTest = ({required accept, multiple = false}) async =>
      [PickedFile(name, Uint8List.fromList(const [1, 2, 3]))];
  addTearDown(() => pickFilesForTest = null);
}

String textOf(WidgetTester tester, String key) =>
    tester.widget<Text>(find.byKey(Key(key))).data!;

/// What a bar button says.
String label(WidgetTester tester, String key) =>
    tester.widget<PixelButton>(find.byKey(Key(key))).text;

/// Let a chain of answers from the launcher arrive, a frame at a time, without
/// waiting for the screen to come to rest.
Future<void> breathe(WidgetTester tester, [int frames = 6]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

bool enabled(WidgetTester tester, String key) =>
    tester.widget<PixelButton>(find.byKey(Key(key))).onTap != null;

Future<KitController> open(WidgetTester tester, FakeLauncher launcher) async {
  PixelButton.animate = false;
  tester.view.physicalSize = const Size(1280, 800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  addTearDown(() => registerImported(const []));
  final kit = launcher.controller();
  await kit.start();
  await tester.pumpWidget(DevKitApp(kit));
  await tester.pump();
  await tester.pump(); // the quiet update check the kit makes when it opens
  _opened = kit;
  return kit;
}

KitController? _opened;

/// A widget test that closes the kit it opened: the page's timers (its word to
/// the launcher every ten seconds, the save that trails a change) have to be
/// gone before the framework checks that none are left.
void kitTest(String description, Future<void> Function(WidgetTester tester) body) =>
    testWidgets(description, (tester) async {
      await body(tester);
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpWidget(const SizedBox());
      _opened?.dispose();
      _opened = null;
    });

GardenView garden(WidgetTester tester) => tester.widget<GardenView>(find.byType(GardenView));

void main() {
  kitTest('it opens on the garden, with the bar above and the shelf below', (tester) async {
    await open(tester, FakeLauncher());
    expect(find.text('PIXEL POMO DEV KIT'), findsOneWidget);
    expect(find.text('v9.9.9'), findsOneWidget);
    for (final key in ['viewWeb', 'viewMobile', 'addButton', 'guideButton', 'shrinkButton', 'expandButton']) {
      expect(find.byKey(Key(key)), findsOneWidget, reason: key);
    }
    expect(find.byType(GardenView), findsOneWidget);
    expect(find.byKey(const Key('gardenSize')), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('gardenSize'))).data, '4x8');
    // GUIDE sits right beside ADD
    final add = tester.getRect(find.byKey(const Key('addButton')));
    final guide = tester.getRect(find.byKey(const Key('guideButton')));
    expect(guide.left - add.right, inInclusiveRange(0, 16));
    // the garden is between the bar and the shelf
    final view = tester.getRect(find.byType(GardenView));
    expect(view.top, greaterThanOrEqualTo(add.bottom));
    expect(view.bottom, lessThan(tester.getRect(find.byKey(const Key('category_flowers'))).top));
  });

  kitTest('the shelves are the market\'s, and every item wears its 2D or 3D label', (tester) async {
    await open(tester, FakeLauncher());
    expect(find.byKey(const Key('item_gul~0')), findsOneWidget);
    expect(find.descendant(of: find.byKey(const Key('item_gul~0')), matching: find.text('2D')),
        findsOneWidget);
    await tester.tap(find.byKey(const Key('category_outer')));
    await tester.pump();
    expect(find.byKey(const Key('item_gul~0')), findsNothing);
    Finder label(String id, String dim) =>
        find.descendant(of: find.byKey(Key('item_$id')), matching: find.text(dim));
    expect(label('road_concrete', '2D'), findsOneWidget);
    expect(label('fence_wood', '3D'), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const Key('item_house_wood')), 200,
        scrollable: find.byType(Scrollable).last);
    expect(label('house_wood', '3D'), findsOneWidget);
    // the two shelves the market has not filled yet say so
    await tester.tap(find.byKey(const Key('category_pets')));
    await tester.pump();
    expect(find.textContaining('COMING SOON'), findsOneWidget);
    expect(find.byKey(const Key('item_eraser')), findsOneWidget);
  });

  kitTest('pick on the shelf, click a tile: it is placed, and saved', (tester) async {
    final launcher = FakeLauncher();
    final kit = await open(tester, launcher);
    expect(garden(tester).customizing, false, reason: 'no tile grid until there is a brush');
    await tester.tap(find.byKey(const Key('item_gul~1')));
    await tester.pump();
    expect(garden(tester).customizing, true);
    garden(tester).onTapTile(9);
    await tester.pump();
    expect(kit.garden.tiles, {9: 'gul~1'});
    expect(garden(tester).garden.tiles, {9: 'gul~1'});
    // the eraser takes it off again
    await tester.tap(find.byKey(const Key('item_eraser')));
    await tester.pump();
    garden(tester).onTapTile(9);
    await tester.pump(const Duration(seconds: 1));
    expect(kit.garden.tiles, isEmpty);
    expect(launcher.saved, isNotEmpty);
    expect(KitState.decode(launcher.saved.last).garden.tiles, isEmpty);
  });

  kitTest('a refused placement says why', (tester) async {
    final kit = await open(tester, FakeLauncher());
    kit.pick(kit.palette.firstWhere((i) => i.id == 'road_dirt'));
    kit.tapTile(3);
    kit.pick(kit.palette.firstWhere((i) => i.id == 'gul~0'));
    kit.tapTile(3);
    await tester.pump();
    expect(kit.garden.tiles, {3: 'road_dirt'});
    expect(tester.widget<Text>(find.byKey(const Key('statusLine'))).data,
        contains('cannot stand on a path'));
  });

  kitTest('EXPAND and SHRINK resize the plot; SHRINK stops at the game\'s smallest', (tester) async {
    final kit = await open(tester, FakeLauncher());
    String size() => tester.widget<Text>(find.byKey(const Key('gardenSize'))).data!;
    await tester.tap(find.byKey(const Key('shrinkButton')));
    await tester.pump();
    expect(size(), '4x8');
    await tester.tap(find.byKey(const Key('expandButton')));
    await tester.pump();
    expect(size(), '6x12');
    expect((garden(tester).garden.cols, garden(tester).garden.rows), (6, 12));
    await tester.tap(find.byKey(const Key('shrinkButton')));
    await tester.pump();
    expect(size(), '4x8');
    expect(kit.garden.cols, 4);
  });

  kitTest('VIEW switches between the wide look and a phone, keeping the camera', (tester) async {
    final kit = await open(tester, FakeLauncher());
    final wide = tester.getSize(find.byType(GardenView));
    expect(wide.width, 1280);
    expect(find.byKey(const Key('phoneFrame')), findsNothing);
    kit.camera.yaw = 1.25;
    final stateBefore = tester.state(find.byType(GardenView));

    await tester.tap(find.byKey(const Key('viewMobile')));
    await tester.pump();
    expect(find.byKey(const Key('phoneFrame')), findsOneWidget);
    // laid out at a phone's own logical size, whatever the window is
    expect(tester.getSize(find.byType(GardenView)), const Size(kPhoneWidth, kPhoneHeight));
    // ...and shown upright, inside the stage
    final shown = tester.getRect(find.byKey(const Key('phoneFrame')));
    expect(shown.height, greaterThan(shown.width * 2));
    expect(shown.height, lessThanOrEqualTo(wide.height));
    expect(identical(tester.state(find.byType(GardenView)), stateBefore), true,
        reason: 'the same garden view moves into the frame; it is not rebuilt');
    expect(garden(tester).camera!.yaw, 1.25);

    await tester.tap(find.byKey(const Key('viewWeb')));
    await tester.pump();
    expect(tester.getSize(find.byType(GardenView)), wide);
  });

  kitTest('what was added before is on its shelf, drawn as geometry, marked NEW', (tester) async {
    final launcher = FakeLauncher(items: [cafe], state: jsonEncode({
      'garden': 'cols:6\nrows:12\n4:house_x_cafe\n5:gul~0\n6:house_x_gone',
      'view': 'mobile',
      'category': 'outer',
    }));
    final kit = await open(tester, launcher);
    expect(kit.view, KitView.mobile);
    expect(find.byKey(const Key('phoneFrame')), findsOneWidget);
    expect(kit.category, KitCategory.outer);
    // the saved garden comes back — less the model whose file is gone
    expect(kit.garden.tiles, {4: 'house_x_cafe', 5: 'gul~0'});
    expect(Placeables.isHouse('house_x_cafe'), true);
    expect(kit.bank!.mesh('house_x_cafe')!.boxes.length, 1);
    await tester.scrollUntilVisible(find.byKey(const Key('item_house_x_cafe')), 200,
        scrollable: find.byType(Scrollable).last);
    final tile = find.byKey(const Key('item_house_x_cafe'));
    expect(find.descendant(of: tile, matching: find.text('3D')), findsOneWidget);
    expect(find.descendant(of: tile, matching: find.text('NEW')), findsOneWidget);
    expect(find.descendant(of: tile, matching: find.text('CAFE')), findsOneWidget);
  });

  kitTest('UPDATE and TRASH keep the top right corner', (tester) async {
    await open(tester, FakeLauncher());
    final update = tester.getRect(find.byKey(const Key('updateButton')));
    final trash = tester.getRect(find.byKey(const Key('trashBarButton')));
    // beside each other, TRASH last, hard against the right edge of the window
    expect(trash.left - update.right, inInclusiveRange(0, 16));
    expect(1280 - trash.right, inInclusiveRange(0, 20));
    // on the bar's top row, right of every other control
    final clear = tester.getRect(find.byKey(const Key('clearButton')));
    expect(update.left, greaterThan(clear.right));
    expect(update.top, closeTo(tester.getRect(find.byKey(const Key('addButton'))).top, 3));
  });

  kitTest('a narrow window wraps the controls and leaves UPDATE and TRASH where they are',
      (tester) async {
    await open(tester, FakeLauncher());
    tester.view.physicalSize = const Size(960, 700);
    await tester.pump();
    final trash = tester.getRect(find.byKey(const Key('trashBarButton')));
    expect(960 - trash.right, inInclusiveRange(0, 20));
    expect(trash.top, closeTo(tester.getRect(find.byKey(const Key('addButton'))).top, 3));
    // the garden's own controls went to a second row instead of under them
    expect(tester.getRect(find.byKey(const Key('clearButton'))).top, greaterThan(trash.bottom - 4));
    expect(tester.takeException(), isNull);
  });

  kitTest('a right-click on one of the game\'s objects says what it is, and offers no trash',
      (tester) async {
    final kit = await open(tester, FakeLauncher());
    await tester.tap(find.byKey(const Key('item_gul~0')), buttons: kSecondaryButton);
    await tester.pump();
    expect(find.text('PART OF THE GAME'), findsOneWidget);
    expect(textOf(tester, 'detail_KIND'), contains('2D'));
    expect(textOf(tester, 'detail_SHELF'), 'FLOWERS');
    expect(find.byKey(const Key('changeButton')), findsNothing);
    expect(find.byKey(const Key('trashButton')), findsNothing);
    // looking is not picking
    expect(kit.brushItem, isNull);
    await tester.tap(find.byKey(const Key('closeDetails')));
    await tester.pump();
    expect(find.text('PART OF THE GAME'), findsNothing);
  });

  kitTest('a right-click on something added writes out the choices that were made',
      (tester) async {
    await open(tester, FakeLauncher(items: [cafe], state: jsonEncode({'category': 'outer'})));
    await tester.scrollUntilVisible(find.byKey(const Key('item_house_x_cafe')), 200,
        scrollable: find.byType(Scrollable).last);
    await tester.tap(find.byKey(const Key('item_house_x_cafe')), buttons: kSecondaryButton);
    await tester.pump();
    expect(find.text('ADDED BY YOU'), findsOneWidget);
    expect(textOf(tester, 'detail_FILE'), 'cafe.vox');
    expect(textOf(tester, 'detail_MODEL'), '1 of 2 (16x8x16 voxels)');
    expect(textOf(tester, 'detail_SIZE'), 'FIT 1 x 3 TILES');
    expect(textOf(tester, 'detail_COMES OUT'), '1 x 0.5 tiles, 1 tall');
    expect(textOf(tester, 'detail_TURN'), '30 degrees');
    expect(textOf(tester, 'detail_SHELF'), 'OUTER DECOR');
    // CHANGE is under the details, above the way out
    final change = tester.getRect(find.byKey(const Key('changeButton')));
    expect(change.top, greaterThan(tester.getRect(find.byKey(const Key('detail_SHELF'))).bottom));
    expect(change.bottom, lessThan(tester.getRect(find.byKey(const Key('trashButton'))).top));
    // and where the kit's copy of the file is
    expect(find.text('D:\\kit\\Files\\library\\house_x_cafe'), findsOneWidget);
  });

  kitTest('MOVE TO TRASH takes it off the shelf and out of the garden, and deletes nothing',
      (tester) async {
    final launcher = FakeLauncher(
        items: [cafe],
        state: jsonEncode({'garden': 'cols:4\nrows:8\n4:house_x_cafe\n5:gul~0', 'category': 'outer'}));
    final kit = await open(tester, launcher);
    expect(label(tester, 'trashBarButton'), 'TRASH');
    await tester.scrollUntilVisible(find.byKey(const Key('item_house_x_cafe')), 200,
        scrollable: find.byType(Scrollable).last);
    await tester.tap(find.byKey(const Key('item_house_x_cafe')), buttons: kSecondaryButton);
    await tester.pump();
    await tester.tap(find.byKey(const Key('trashButton')));
    await breathe(tester, 14);
    expect(find.text('ADDED BY YOU'), findsNothing, reason: 'the details close behind it');
    expect(launcher.asks('POST /api/trash/'), ['POST /api/trash/house_x_cafe']);
    expect(launcher.asks('DELETE'), isEmpty);
    expect(kit.garden.tiles, {5: 'gul~0'});
    expect(kit.palette.any((i) => i.id == 'house_x_cafe'), false);
    expect(Placeables.isHouse('house_x_cafe'), false);
    expect(kit.bank!.mesh('house_x_cafe'), isNull);
    expect(kit.trashed.single.trashKey, 'house_x_cafe');
    // the bar counts what is waiting there
    expect(label(tester, 'trashBarButton'), 'TRASH  1');
    expect(textOf(tester, 'statusLine'), contains('is in the trash'));
  });

  kitTest('TRASH puts a thing back on its shelf', (tester) async {
    final launcher = FakeLauncher(items: [cafe]);
    final kit = await open(tester, launcher);
    await kit.moveToTrash(kit.imported.single);
    await tester.pump();
    await tester.tap(find.byKey(const Key('trashBarButton')));
    await tester.pump();
    expect(find.text('CAFE'), findsOneWidget);
    await tester.tap(find.byKey(const Key('restore_house_x_cafe')));
    await breathe(tester, 14);
    expect(kit.trashed, isEmpty);
    expect(kit.imported.single.id, 'house_x_cafe');
    expect(kit.bank!.mesh('house_x_cafe'), isNotNull);
    expect(Placeables.isHouse('house_x_cafe'), true);
    expect(kit.category, KitCategory.outer);
    expect(find.textContaining('Nothing in the trash'), findsOneWidget);
  });

  kitTest('deleting from the trash asks first, and KEEP keeps', (tester) async {
    final launcher = FakeLauncher(items: [cafe]);
    final kit = await open(tester, launcher);
    await kit.moveToTrash(kit.imported.single);
    await tester.pump();
    await tester.tap(find.byKey(const Key('trashBarButton')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('delete_house_x_cafe')));
    await tester.pump();
    expect(find.text('DELETE CAFE?'), findsOneWidget);
    expect(find.textContaining('wherever you keep it, is not touched'), findsOneWidget);
    await tester.tap(find.byKey(const Key('confirmNo')));
    await breathe(tester, 14);
    expect(launcher.asks('DELETE'), isEmpty);
    expect(kit.trashed.length, 1);

    await tester.tap(find.byKey(const Key('delete_house_x_cafe')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('confirmYes')));
    await breathe(tester, 14);
    expect(launcher.asks('DELETE'), ['DELETE /api/trash/house_x_cafe']);
    expect(kit.trashed, isEmpty);
    expect(launcher.trash, isEmpty);
  });

  kitTest('EMPTY THE TRASH asks first, and is off when there is nothing in it', (tester) async {
    final launcher = FakeLauncher(items: [cafe]);
    final kit = await open(tester, launcher);
    await tester.tap(find.byKey(const Key('trashBarButton')));
    await tester.pump();
    expect(enabled(tester, 'emptyTrash'), false);
    await tester.tap(find.byKey(const Key('closeTrash')));
    await tester.pump();
    await kit.moveToTrash(kit.imported.single);
    await tester.pump();
    await tester.tap(find.byKey(const Key('trashBarButton')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('emptyTrash')));
    await tester.pump();
    expect(find.text('EMPTY THE TRASH?'), findsOneWidget);
    await tester.tap(find.byKey(const Key('confirmYes')));
    await breathe(tester, 14);
    expect(launcher.asks('DELETE'), ['DELETE /api/trash']);
    expect(kit.trashed, isEmpty);
  });

  kitTest('ADD 3D VOX FILE: the scale is said beside the title, the size is ORIGINAL SIZE',
      (tester) async {
    final launcher = FakeLauncher();
    await open(tester, launcher);
    picking('Cafe.vox');
    unawaited(addVoxFlow(tester.element(find.byType(GardenView)), _opened!));
    await breathe(tester, 14);
    final title = tester.getRect(find.text('ADD 3D VOX FILE'));
    final note = tester.getRect(find.byKey(const Key('scaleNote')));
    expect(textOf(tester, 'scaleNote'), 'ORIGINAL SIZE: 16 VOXELS = 1 TILE');
    expect(note.left, greaterThan(title.right));
    expect((note.center.dy - title.center.dy).abs(), lessThan(8), reason: 'on the title\'s own line');
    expect(find.byKey(const Key('size_ORIGINAL SIZE')), findsOneWidget);
    expect(find.byKey(const Key('size_FIT TO TILES')), findsOneWidget);
    expect(find.textContaining('16 VOXELS = 1 TILE'), findsOneWidget, reason: 'said once');
    // the fit's two sides appear only when a fit is asked for
    expect(find.byKey(const Key('fitWide')), findsNothing);
    await tester.tap(find.byKey(const Key('cancelAdd')));
    await breathe(tester, 14);
    expect(launcher.asks('POST /api/import'), isEmpty);
  });

  kitTest('the model is shown on the right as it will stand, and follows the choices',
      (tester) async {
    final launcher = FakeLauncher();
    await open(tester, launcher);
    picking('Cafe.vox');
    unawaited(addVoxFlow(tester.element(find.byType(GardenView)), _opened!));
    await breathe(tester, 14);
    VoxPreview preview() => tester.widget<VoxPreview>(find.byKey(const Key('voxPreview')));
    // right of the settings, inside the dialog
    expect(tester.getRect(find.byKey(const Key('voxPreview'))).left,
        greaterThan(tester.getRect(find.byKey(const Key('nameField'))).right));
    expect((preview().scale, preview().turn, preview().fit), (1, 0, null));
    expect(find.textContaining('Comes out 1 x 0.5 tiles, 1 tall'), findsOneWidget);

    // 2 long, 2 wide — typed, not picked from three
    await tester.tap(find.byKey(const Key('size_FIT TO TILES')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('fitWide')), '2');
    await tester.enterText(find.byKey(const Key('fitLong')), '2');
    await tester.pump();
    expect(preview().scale, 2);
    expect(preview().fit, (wide: 2.0, long: 2.0));
    expect(find.textContaining('Comes out 2 x 1 tiles, 2 tall'), findsOneWidget);

    // any angle
    await tester.enterText(find.byKey(const Key('turnField')), '137');
    await tester.pump();
    expect(preview().turn, 137);
    // a quarter turn swaps the sides it is fitted by
    await tester.tap(find.byKey(const Key('turn_90')));
    await tester.pump();
    expect(preview().turn, 90);
    expect(find.textContaining('Comes out 1 x 2 tiles'), findsOneWidget);

    await tester.tap(find.byKey(const Key('confirmAdd')));
    await breathe(tester, 14);
    final sent = Uri.parse(launcher.asks('POST /api/import/vox').single.split(' ').last);
    expect(sent.queryParameters,
        {'file': 'Cafe.vox', 'name': 'CAFE', 'category': 'outer', 'model': '0', 'turn': '90',
         'wide': '2.0', 'long': '2.0'});
  });

  kitTest('what cannot be used is said, and ADD waits for it to be put right', (tester) async {
    final launcher = FakeLauncher();
    await open(tester, launcher);
    picking('Cafe.vox');
    unawaited(addVoxFlow(tester.element(find.byType(GardenView)), _opened!));
    await breathe(tester, 14);
    expect(enabled(tester, 'confirmAdd'), true);
    await tester.enterText(find.byKey(const Key('turnField')), '400');
    await tester.pump();
    expect(enabled(tester, 'confirmAdd'), false);
    expect(find.textContaining('whole number of degrees from 0 to 360'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('turnField')), '359');
    await tester.pump();
    expect(enabled(tester, 'confirmAdd'), true);

    await tester.tap(find.byKey(const Key('size_FIT TO TILES')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('fitWide')), '40');
    await tester.pump();
    expect(enabled(tester, 'confirmAdd'), false);
    expect(find.textContaining('from 0.25 to 16'), findsOneWidget);
    // back to the original size: the bad number no longer matters
    await tester.tap(find.byKey(const Key('size_ORIGINAL SIZE')));
    await tester.pump();
    expect(enabled(tester, 'confirmAdd'), true);
    await tester.tap(find.byKey(const Key('cancelAdd')));
    await breathe(tester, 14);
  });

  kitTest('while a model is converted the dialog says so, and a refused one cannot be added',
      (tester) async {
    final launcher = FakeLauncher()
      ..converting = Completer<void>()
      ..tooHeavy = 1;
    await open(tester, launcher);
    picking('Cafe.vox');
    unawaited(addVoxFlow(tester.element(find.byType(GardenView)), _opened!));
    await breathe(tester);
    expect(find.byKey(const Key('previewWait')), findsOneWidget);
    expect(find.text('CONVERTING — PLEASE WAIT'), findsOneWidget);
    expect(enabled(tester, 'confirmAdd'), false, reason: 'nothing to add until it is shown');
    launcher.converting!.complete();
    await breathe(tester, 14);
    expect(find.byKey(const Key('previewWait')), findsNothing);
    expect(find.byKey(const Key('voxPreview')), findsOneWidget);
    expect(enabled(tester, 'confirmAdd'), true);

    // the file's second model is too heavy
    await tester.tap(find.byKey(const Key('model_2: 32x16x8')));
    await breathe(tester, 14);
    expect(textOf(tester, 'previewRefused'), 'That model needs 27601 boxes.');
    expect(find.byKey(const Key('voxPreview')), findsNothing);
    expect(enabled(tester, 'confirmAdd'), false);
    await tester.tap(find.byKey(const Key('cancelAdd')));
    await breathe(tester, 14);
  });

  kitTest('adding says PLEASE WAIT with its steps until the model is on the shelf', (tester) async {
    final launcher = FakeLauncher();
    final kit = await open(tester, launcher);
    picking('Cafe.vox');
    unawaited(addVoxFlow(tester.element(find.byType(GardenView)), kit));
    await breathe(tester, 14);
    launcher.converting = Completer<void>();
    await tester.tap(find.byKey(const Key('confirmAdd')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('ADDING CAFE'), findsOneWidget);
    expect(find.byKey(const Key('pleaseWait')), findsOneWidget);
    expect(textOf(tester, 'progressStep0'), contains('SENDING THE FILE'));
    expect(textOf(tester, 'progressStep1'), contains('CONVERTING THE MODEL'));
    expect(textOf(tester, 'progressStep2'), contains('PUTTING IT ON THE SHELF'));
    expect(textOf(tester, 'progressStep0'), startsWith('>>>'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(textOf(tester, 'progressStep0'), startsWith('DONE'));
    expect(textOf(tester, 'progressStep1'), startsWith('>>>'));
    // it cannot be clicked away while the kit is working
    await tester.tapAt(const Offset(5, 5));
    await tester.pump(const Duration(seconds: 4));
    expect(find.byKey(const Key('pleaseWait')), findsOneWidget);
    expect(find.textContaining('4 s so far'), findsOneWidget);

    launcher.converting!.complete();
    await breathe(tester, 14);
    expect(find.byKey(const Key('pleaseWait')), findsNothing);
    expect(kit.imported.single.id, 'house_x_cafe');
    expect(kit.brushItem?.id, 'house_x_cafe');
    expect(textOf(tester, 'statusLine'), startsWith('Added CAFE'));
  });

  kitTest('CHANGE opens the same choices as they were made, and the thing keeps its place',
      (tester) async {
    final launcher = FakeLauncher(
        items: [cafe],
        state: jsonEncode({'garden': 'cols:4\nrows:8\n4:house_x_cafe', 'category': 'outer'}));
    final kit = await open(tester, launcher);
    await tester.scrollUntilVisible(find.byKey(const Key('item_house_x_cafe')), 200,
        scrollable: find.byType(Scrollable).last);
    await tester.tap(find.byKey(const Key('item_house_x_cafe')), buttons: kSecondaryButton);
    await tester.pump();
    await tester.tap(find.byKey(const Key('changeButton')));
    await breathe(tester, 14);
    expect(find.text('CHANGE CAFE'), findsOneWidget);
    String field(String key) => tester.widget<TextField>(find.byKey(Key(key))).controller!.text;
    expect((field('nameField'), field('turnField'), field('fitWide'), field('fitLong')),
        ('Cafe', '30', '1', '3'));
    // the preview is of the kit's own copy of the file
    expect(launcher.asks('GET /api/preview/item/'), ['GET /api/preview/item/house_x_cafe?model=0']);

    await tester.enterText(find.byKey(const Key('turnField')), '200');
    await tester.tap(find.byKey(const Key('size_ORIGINAL SIZE')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('confirmAdd')));
    await breathe(tester, 14);
    final sent = Uri.parse(launcher.asks('POST /api/change/').single.split(' ').last);
    expect(sent.path, '/api/change/house_x_cafe');
    expect(sent.queryParameters,
        {'name': 'Cafe', 'category': 'outer', 'model': '0', 'turn': '200', 'size': 'original'});
    expect(kit.imported.single.turn, 200);
    expect(kit.garden.tiles, {4: 'house_x_cafe'}, reason: 'it changes where it stands');
    // the details behind the dialog now read the new choices
    expect(textOf(tester, 'detail_TURN'), '200 degrees');
    expect(textOf(tester, 'detail_SIZE'), 'ORIGINAL SIZE');
  });

  kitTest('the version number opens where everything is kept, and each folder opens',
      (tester) async {
    final launcher = FakeLauncher();
    await open(tester, launcher);
    await tester.tap(find.byKey(const Key('versionButton')));
    await tester.pump();
    expect(find.text('ABOUT THE DEV KIT'), findsOneWidget);
    expect(textOf(tester, 'aboutVersion'), 'v9.9.9');
    expect(textOf(tester, 'aboutBuild'), 'INSTALLED');
    expect(find.text('D:\\kit'), findsOneWidget);
    expect(find.text('D:\\kit\\Files'), findsOneWidget);
    expect(find.text('D:\\kit\\Files\\trash'), findsOneWidget);
    expect(find.textContaining('An update replaces the program only'), findsOneWidget);
    for (final key in ['aboutProgram', 'aboutFiles', 'aboutTrash']) {
      await tester.tap(find.byKey(Key(key)));
      await tester.pump();
    }
    expect(launcher.asks('POST /api/open-folder'), [
      'POST /api/open-folder?which=program',
      'POST /api/open-folder?which=files',
      'POST /api/open-folder?which=trash',
    ]);
  });

  kitTest('UPDATE lights up when a newer kit is out, and installing it keeps the window waiting',
      (tester) async {
    final launcher = FakeLauncher(latest: '10.0.0');
    final kit = await open(tester, launcher);
    expect(kit.update.available, true, reason: 'the kit asks once when it opens');
    expect(label(tester, 'updateButton'), 'UPDATE  v10.0.0');
    await tester.tap(find.byKey(const Key('updateButton')));
    await tester.pump();
    expect(textOf(tester, 'updateHead'), 'v10.0.0 IS OUT');
    expect(find.textContaining('Everything you added stays exactly where it is'), findsOneWidget);
    await tester.tap(find.byKey(const Key('updateNow')));
    await tester.pump();
    await tester.pump();
    expect(launcher.asks('POST /api/update/apply').length, 1);
    expect(textOf(tester, 'updateHead'), 'DOWNLOADING v10.0.0  40%');
    expect(find.byKey(const Key('closeUpdate')), findsNothing, reason: 'nothing to press meanwhile');
    launcher.updateState = 'ready';
    await tester.pump(const Duration(seconds: 1));
    expect(textOf(tester, 'updateHead'), 'RESTARTING...');
  });

  kitTest('with nothing newer, UPDATE says so', (tester) async {
    final launcher = FakeLauncher(latest: '9.9.9');
    await open(tester, launcher);
    expect(label(tester, 'updateButton'), 'UPDATE');
    await tester.tap(find.byKey(const Key('updateButton')));
    await breathe(tester, 14);
    expect(textOf(tester, 'updateHead'), 'YOU HAVE THE NEWEST VERSION');
    expect(find.byKey(const Key('updateNow')), findsNothing);
  });

  kitTest('with nothing published yet, UPDATE says that, and nothing is changed', (tester) async {
    final launcher = FakeLauncher();
    await open(tester, launcher);
    await tester.tap(find.byKey(const Key('updateButton')));
    await breathe(tester, 14);
    expect(textOf(tester, 'updateHead'), 'NOT CHECKED');
    expect(find.text('No version of the Dev Kit has been published yet.'), findsOneWidget);
    expect(find.byKey(const Key('updateRetry')), findsOneWidget);
    expect(launcher.asks('POST /api/update/apply'), isEmpty);
  });

  kitTest('a kit that is not installed is told where the new version is', (tester) async {
    final launcher = FakeLauncher(latest: '10.0.0')..canUpdate = false;
    await open(tester, launcher);
    await tester.tap(find.byKey(const Key('updateButton')));
    await tester.pump();
    expect(find.byKey(const Key('updateNow')), findsNothing);
    expect(find.textContaining('https://example.test/releases'), findsOneWidget);
  });

  kitTest('GUIDE explains the kit and where the files are', (tester) async {
    await open(tester, FakeLauncher());
    await tester.tap(find.byKey(const Key('guideButton')));
    await tester.pump();
    expect(find.text('GUIDE'), findsWidgets);
    expect(find.textContaining('ADD 2D SPRITE or ADD 3D VOX FILE'), findsOneWidget);
    expect(find.textContaining('D:\\kit\\Files'), findsOneWidget);
    expect(find.textContaining('MOVE TO TRASH'), findsOneWidget);
    await tester.tap(find.byKey(const Key('closeGuide')));
    await tester.pump();
    expect(find.byKey(const Key('closeGuide')), findsNothing);
  });

  kitTest('ADD offers a 2D sprite and a 3D vox file', (tester) async {
    await open(tester, FakeLauncher());
    await tester.tap(find.byKey(const Key('addButton')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('ADD 2D SPRITE'), findsOneWidget);
    expect(find.text('ADD 3D VOX FILE'), findsOneWidget);
    expect(find.text('IMPORTED FILES'), findsOneWidget);
  });

  kitTest('without a launcher behind it the garden still works and says nothing is kept', (tester) async {
    final launcher = FakeLauncher(down: true);
    final kit = await open(tester, launcher);
    expect(kit.online, false);
    expect(find.byType(GardenView), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('statusLine'))).data,
        contains('Nothing you add will be kept'));
    kit.pick(kit.palette.first);
    kit.tapTile(0);
    await tester.pump(const Duration(seconds: 1));
    expect(kit.garden.tiles.length, 1);
    expect(launcher.saved, isEmpty);
  });
}
