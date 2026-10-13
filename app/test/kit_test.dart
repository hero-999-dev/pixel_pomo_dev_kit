import 'package:flutter_test/flutter_test.dart';
import 'package:pixel_pomo/logic.dart';
import 'package:pixel_pomo_dev_kit/kit.dart';

ImportedFile file(String id, ImportKind kind,
        {KitCategory category = KitCategory.outer, String? target}) =>
    ImportedFile(
        id: id,
        name: id,
        kind: kind,
        category: category,
        file: kind == ImportKind.vox ? 'mesh.json' : 'sprite.png',
        target: target);

void main() {
  tearDown(() => registerImported(const []));

  group('The shelves hold everything the game ships', () {
    final items = builtInItems();
    KitItem item(String id) => items.firstWhere((i) => i.id == id);

    test('every flower is there, each drawn variant on its own', () {
      for (final f in Flowers.all) {
        final n = Flowers.variantsFor(f.id);
        final ids = n > 1 ? [for (var v = 0; v < n; v++) '${f.id}~$v'] : [f.id];
        for (final id in ids) {
          expect(item(id).category, KitCategory.flowers, reason: id);
        }
      }
      expect(item('gul~1').name, 'ROSE 2');
      expect(item('gul~1').thumb, 'flower_gul_1');
      expect(item('anthurium').thumb, 'flower_anthurium');
    });

    test('the daisy has its two models, and the chamomile is a flower of its own', () {
      expect(item('papatya~0').name, 'DAISY 1');
      expect(item('papatya~1').name, 'DAISY 2');
      expect(item('papatya~1').thumb, 'flower_papatya_1');
      expect(items.any((i) => i.id == 'papatya'), false);
      expect(item('chamomile').name, 'CHAMOMILE');
      expect(item('chamomile').thumb, 'flower_chamomile');
    });

    test('paths, fences and buildings sit on the market\'s OUTER DECOR shelf', () {
      for (final id in Placeables.objectIds) {
        expect(item(id).category, KitCategory.outer, reason: id);
      }
    });

    test('nothing is listed twice and every id can be stored in a garden', () {
      expect({for (final i in items) i.id}.length, items.length);
      for (final i in items) {
        expect(i.id.contains('+') || i.id.contains(':') || i.id.contains('\n'), false);
      }
    });

    test('the 2D / 3D label: flowers and grounds 2D, fences and houses 3D', () {
      expect(item('gul~0').dimLabel, '2D');
      expect(item('chamomile').dimLabel, '2D');
      for (final id in Placeables.roadIds) {
        expect(item(id).dimLabel, '2D', reason: id);
        expect(item(id).isGround, true, reason: id);
      }
      for (final id in [...Placeables.fenceIds, ...Placeables.houseIds]) {
        expect(item(id).dimLabel, '3D', reason: id);
        expect(item(id).isGround, false, reason: id);
      }
    });

    test('the shelves are named as the market names them', () {
      expect([for (final c in KitCategory.values) c.label],
          ['FLOWERS', 'OUTER DECOR', 'INNER DECOR', 'PETS']);
    });
  });

  group('What the artist added', () {
    test('a vox is 3D, a sprite 2D, a ground 2D and flat; each on its chosen shelf', () {
      final palette = paletteOf([
        file('house_x_cafe', ImportKind.vox, category: KitCategory.inner),
        file('x_bluerose', ImportKind.sprite, category: KitCategory.flowers),
        file('xroad_marble', ImportKind.ground),
      ]);
      KitItem item(String id) => palette.firstWhere((i) => i.id == id);
      expect(item('house_x_cafe').dimLabel, '3D');
      expect(item('house_x_cafe').category, KitCategory.inner);
      expect(item('x_bluerose').dimLabel, '2D');
      expect(item('x_bluerose').category, KitCategory.flowers);
      expect(item('xroad_marble').dimLabel, '2D');
      expect(item('xroad_marble').isGround, true);
      expect(item('house_x_cafe').imported, isNotNull);
      // the game's own objects are still all there, ahead of the artist's
      expect(palette.length, builtInItems().length + 3);
      expect(palette.first.imported, isNull);
    });

    test('a forest sprite grows in the woods, not on a shelf', () {
      final forest = file('forest_tree_07', ImportKind.forest, target: 'tree_07');
      expect(itemFor(forest), isNull);
      expect(paletteOf([forest]).length, builtInItems().length);
    });

    test('registering tells the game\'s own rules what to lay flat and what to build', () {
      registerImported([
        file('house_x_cafe', ImportKind.vox),
        file('xroad_marble', ImportKind.ground),
        file('x_bluerose', ImportKind.sprite),
      ]);
      expect(Placeables.isHouse('house_x_cafe'), true);
      expect(Placeables.isRoad('xroad_marble'), true);
      expect(Placeables.isFlower('x_bluerose'), true);
      // ...and forgetting them again when they are removed
      registerImported(const []);
      expect(Placeables.isHouse('house_x_cafe'), false);
      expect(Placeables.isRoad('xroad_marble'), false);
    });

    test('a library record is read; one this version cannot use is skipped', () {
      final vox = ImportedFile.fromJson({
        'id': 'house_x_cafe', 'name': 'Cafe', 'kind': 'vox', 'category': 'inner',
        'file': 'mesh.json', 'source': 'cafe.vox', 'boxes': 412, 'tiles': 2.5, 'height': 1.75,
      })!;
      expect(vox.kind, ImportKind.vox);
      expect(vox.category, KitCategory.inner);
      // a record from v0.1.0 has only the wider side: both sides read as it
      expect(vox.details, '412 boxes · 2.5 x 2.5 tiles · 1.75 tall');
      expect((vox.fitted, vox.turn, vox.sizeLabel), (false, 0, 'ORIGINAL SIZE'));
      // ...and does not say how many models its file held: none is claimed
      expect(vox.choices[1], ('MODEL', '1'));
      final sprite = ImportedFile.fromJson({
        'id': 'x_rose', 'kind': 'sprite', 'file': 'sprite.png', 'width': 256, 'heightPx': 304,
      })!;
      expect(sprite.name, 'x_rose');
      expect(sprite.details, '256x304 px');
      for (final bad in [
        null,
        'text',
        {'id': 'x', 'kind': 'hologram', 'file': 'a'},
        {'id': 'a+b', 'kind': 'sprite', 'file': 'sprite.png'},
        {'kind': 'sprite', 'file': 'sprite.png'},
      ]) {
        expect(ImportedFile.fromJson(bad), isNull, reason: '$bad');
      }
    });

    test('every choice made when a model was added is read back and written out', () {
      final f = ImportedFile.fromJson({
        'id': 'house_x_cafe', 'name': 'Cafe', 'kind': 'vox', 'category': 'inner',
        'file': 'mesh.json', 'source': 'Coffee Local.vox', 'original': 'Coffee Local.vox',
        'boxes': 1971, 'tiles': 3.0, 'tilesWide': 3.0, 'tilesLong': 2.25, 'height': 1.19,
        'model': 2, 'models': 9, 'modelSize': [36, 27, 19], 'turn': 100,
        'size': 'fit', 'fitWide': 3.0, 'fitLong': 4.5, 'added': 1700000000.5,
      })!;
      expect((f.model, f.models, f.turn), (2, 9, 100));
      expect(f.modelSize, [36, 27, 19]);
      expect((f.fitted, f.fitWide, f.fitLong), (true, 3.0, 4.5));
      expect((f.tilesWide, f.tilesLong, f.original), (3.0, 2.25, 'Coffee Local.vox'));
      expect(f.choices, [
        ('FILE', 'Coffee Local.vox'),
        ('MODEL', '3 of 9 (36x27x19 voxels)'),
        ('SIZE', 'FIT 3 x 4.5 TILES'),
        ('COMES OUT', '3 x 2.25 tiles, 1.19 tall'),
        ('TURN', '100 degrees'),
        ('BOXES', '1971'),
        ('SHELF', 'INNER DECOR'),
      ]);
    });

    test('a sprite\'s choices are its file, its picture, its use and its shelf', () {
      final rose = ImportedFile.fromJson({
        'id': 'x_rose', 'name': 'Rose', 'kind': 'sprite', 'category': 'flowers',
        'file': 'flower rose.png', 'source': 'flower rose.png', 'width': 256, 'heightPx': 304,
      })!;
      expect(rose.choices, [
        ('FILE', 'flower rose.png'),
        ('PICTURE', '256 x 304 px'),
        ('USE', 'STANDING'),
        ('SHELF', 'FLOWERS'),
      ]);
      final tree = file('forest_tree_07', ImportKind.forest, target: 'tree_07');
      expect(tree.useLabel, 'FOREST TREE_07');
      expect(tree.choices.any((row) => row.$1 == 'SHELF'), false);
      expect(file('xroad_m', ImportKind.ground).useLabel, 'FLAT GROUND');
    });

    test('something in the trash carries the name of its entry there', () {
      final t = ImportedFile.fromJson({
        'id': 'forest_tree_07', 'kind': 'forest', 'file': 'a.png', 'target': 'tree_07',
        'trashKey': 'forest_tree_07__2',
      })!;
      expect(t.trashKey, 'forest_tree_07__2');
      expect(file('x_rose', ImportKind.sprite).trashKey, isNull);
    });

    test('an id is only what a saved garden can hold', () {
      expect(validId('house_x_cafe_2'), true);
      for (final bad in ['', 'a+b', 'gul~1', 'a:b', 'a b', 'A', 'a\nb']) {
        expect(validId(bad), false, reason: bad);
      }
    });
  });

  group('A voxel model\'s size', () {
    test('at its original size it comes out as it is in the file', () {
      final out = voxFootprint(2.25, 1.5);
      expect((out.wide, out.long, out.scale), (2.25, 1.5, 1));
    });

    test('a fit is as large as goes into both sides, keeping the shape', () {
      // 2 x 1 into 2 x 2: filled across, half used along
      var out = voxFootprint(2, 1, wide: 2, long: 2);
      expect((out.wide, out.long, out.scale), (2, 1, 1));
      // ...into 4 x 1: its length is the limit
      out = voxFootprint(2, 1, wide: 4, long: 1);
      expect((out.wide, out.long, out.scale), (2, 1, 1));
      // ...into 3 x 3: half as large again
      out = voxFootprint(2, 1, wide: 3, long: 3);
      expect((out.wide, out.long, out.scale), (3, 1.5, 1.5));
      // smaller, too
      out = voxFootprint(4, 2, wide: 1, long: 1);
      expect((out.wide, out.long, out.scale), (1, 0.5, 0.25));
    });

    test('a quarter turn swaps the sides before the fit; the rest of a turn does not', () {
      var out = voxFootprint(2, 1, turn: 90);
      expect((out.wide, out.long), (1, 2));
      out = voxFootprint(2, 1, turn: 100, wide: 1, long: 4);
      expect((out.wide, out.long, out.scale), (1, 2, 1));
      expect(voxFootprint(2, 1, turn: 180).wide, 2);
      expect(voxFootprint(2, 1, turn: 270).wide, 1);
      expect(voxFootprint(2, 1, turn: 45).wide, 2);
      expect(voxFootprint(2, 1, turn: 360).wide, 2);
    });

    test('half a fit is no fit', () {
      expect(voxFootprint(2, 1, wide: 5).scale, 1);
      expect(voxFootprint(2, 1, long: 5).scale, 1);
    });

    test('a size typed in is a number of tiles the kit can use, or nothing', () {
      expect(parseFit('2'), 2);
      expect(parseFit(' 1.5 '), 1.5);
      expect(parseFit('2,5'), 2.5); // a comma, as half of Europe writes it
      expect(parseFit('0.25'), 0.25);
      expect(parseFit('16'), 16);
      for (final bad in ['', 'two', '0', '0.1', '17', '-2', 'NaN']) {
        expect(parseFit(bad), isNull, reason: bad);
      }
    });

    test('a turn typed in is whole degrees from 0 to 360', () {
      expect(parseTurn('0'), 0);
      expect(parseTurn(' 137 '), 137);
      expect(parseTurn('360'), 0);
      for (final bad in ['', '-1', '361', '12.5', 'left']) {
        expect(parseTurn(bad), isNull, reason: bad);
      }
    });

    test('numbers are written as an artist would write them', () {
      expect(trimNumber(2), '2');
      expect(trimNumber(1.5), '1.5');
      expect(trimNumber(0.333), '0.33');
      expect(trimNumber(10), '10');
      expect(trimNumber(100), '100');
      expect(trimNumber(0), '0');
    });
  });

  group('The garden', () {
    final rose = builtInItems().firstWhere((i) => i.id == 'gul~0');
    final road = builtInItems().firstWhere((i) => i.id == 'road_dirt');
    final fence = builtInItems().firstWhere((i) => i.id == 'fence_wood');
    final house = builtInItems().firstWhere((i) => i.id == 'house_wood');

    test('shrink undoes grow, tile for tile', () {
      final g = const Garden().plant(0, 'gul~0').plant(31, 'house_wood').plant(13, 'road_dirt');
      final back = shrink(g.grow());
      expect((back.cols, back.rows), (4, 8));
      expect(back.tiles, g.tiles);
    });

    test('shrink drops what stood on the rim and keeps the middle in place', () {
      var g = const Garden().grow(); // 6x12
      g = g.plant(0, 'gul~0'); // a corner: goes
      g = g.plant(2 * 6 + 1, 'papatya'); // the old 4x8's first tile: stays
      g = g.plant(11 * 6 + 5, 'lale~0'); // the far corner: goes
      final s = shrink(g);
      expect((s.cols, s.rows), (4, 8));
      expect(s.tiles, {0: 'papatya'});
    });

    test('the plot never goes below the game\'s own 4x8, nor past the kit\'s largest', () {
      expect(canShrink(const Garden()), false);
      expect(identical(shrink(const Garden()), shrink(const Garden())), true);
      expect(shrink(const Garden()).cols, 4);
      var g = const Garden();
      var grows = 0;
      while (canGrow(g)) {
        g = g.grow();
        grows++;
      }
      expect((g.cols, g.rows, grows), (16, 32, 6));
      expect(canShrink(g), true);
    });

    test('the brush places, and brushing the same thing again takes it off', () {
      var g = brush(const Garden(), 5, rose);
      expect(g.tiles, {5: 'gul~0'});
      g = brush(g, 5, rose);
      expect(g.tiles, isEmpty);
    });

    test('a different flower replaces the one standing there', () {
      final daisy = builtInItems().firstWhere((i) => i.id == 'chamomile');
      final g = brush(brush(const Garden(), 5, rose), 5, daisy);
      expect(g.tiles, {5: 'chamomile'});
    });

    test('a fence stands on a path and each comes off on its own', () {
      var g = brush(brush(const Garden(), 5, road), 5, fence);
      expect(g.tiles, {5: 'road_dirt+fence_wood'});
      g = brush(g, 5, road); // the path under the fence
      expect(g.tiles, {5: 'fence_wood'});
      g = brush(brush(g, 5, road), 5, fence); // the fence off the path
      expect(g.tiles, {5: 'road_dirt'});
    });

    test('the game\'s own rule holds: nothing that grows or is built goes on a path', () {
      final onRoad = brush(const Garden(), 5, road);
      expect(identical(brush(onRoad, 5, rose), onRoad), true);
      expect(identical(brush(onRoad, 5, house), onRoad), true);
    });

    test('an imported ground and an imported model follow the same rules', () {
      final imported = [file('xroad_marble', ImportKind.ground), file('house_x_cafe', ImportKind.vox)];
      registerImported(imported);
      final marble = itemFor(imported[0])!, cafe = itemFor(imported[1])!;
      var g = brush(brush(const Garden(), 2, marble), 2, fence);
      expect(g.tiles, {2: 'xroad_marble+fence_wood'});
      expect(g.groundAt(2), 'xroad_marble');
      g = brush(g, 3, cafe);
      expect(g.propAt(3), 'house_x_cafe');
      expect(identical(brush(g, 2, cafe), g), true, reason: 'no building on a ground');
    });

    test('a tile outside the plot is left alone', () {
      expect(brush(const Garden(), 999, rose).tiles, isEmpty);
    });

    // an added model, known to the game's rules as a building for this test
    KitItem theCafe() {
      final added = file('house_x_cafe', ImportKind.vox);
      registerImported([added]);
      return itemFor(added)!;
    }

    test('a model goes down at the angle asked for, and each copy keeps its own', () {
      final cafe = theCafe();
      var g = brush(const Garden(), 3, cafe, turn: 45);
      g = brush(g, 4, cafe, turn: 200);
      g = brush(g, 5, cafe);
      expect(g.tiles, {3: 'house_x_cafe@45', 4: 'house_x_cafe@200', 5: 'house_x_cafe'});
      expect([g.turnAt(3), g.turnAt(4), g.turnAt(5)], [45, 200, 0]);
      // what stands there is still the cafe, whichever way it faces
      expect([g.propAt(3), g.propAt(4), g.propAt(5)], List.filled(3, 'house_x_cafe'));
    });

    test('brushing a copy at another angle turns that copy; at its own, takes it off', () {
      final cafe = theCafe();
      var g = brush(brush(const Garden(), 3, cafe, turn: 45), 4, cafe, turn: 45);
      g = brush(g, 3, cafe, turn: 90);
      expect(g.tiles, {3: 'house_x_cafe@90', 4: 'house_x_cafe@45'}, reason: 'only tile 3 turned');
      g = brush(g, 3, cafe, turn: 90);
      expect(g.tiles, {4: 'house_x_cafe@45'});
      // a whole turn is the angle it already has
      g = brush(g, 4, cafe, turn: 405);
      expect(g.tiles, isEmpty);
    });

    test('what cannot be turned ignores the angle', () {
      final cafe = theCafe();
      expect(turnsWherePlaced(cafe), true);
      expect([turnsWherePlaced(rose), turnsWherePlaced(road), turnsWherePlaced(fence)],
          [false, false, false]);
      var g = brush(const Garden(), 5, rose, turn: 90);
      expect(g.tiles, {5: 'gul~0'});
      // and the same flower at "another angle" is still the same flower: off
      g = brush(g, 5, rose, turn: 180);
      expect(g.tiles, isEmpty);
      expect(brush(const Garden(), 5, fence, turn: 90).tiles, {5: 'fence_wood'});
    });

    test('removing a file takes its turned copies too, and leaves the others turned', () {
      final g = const Garden(tiles: {1: 'house_x_cafe@45', 2: 'house_wood@90', 3: 'house_x_cafe'});
      final known = {for (final i in builtInItems()) i.id};
      expect(dropUnknown(g, known).tiles, {2: 'house_wood@90'});
      final kept = dropUnknown(g, {...known, 'house_x_cafe'});
      expect(identical(kept, g), true);
    });

    test('removing a file takes what it left in the garden with it', () {
      final g = const Garden(tiles: {
        0: 'gul~0',
        1: 'house_x_cafe',
        2: 'road_dirt+fence_wood',
        3: 'xroad_marble+fence_wood',
        4: 'xroad_marble',
      });
      final known = {for (final i in builtInItems()) i.id};
      final cleaned = dropUnknown(g, known);
      expect(cleaned.tiles, {0: 'gul~0', 2: 'road_dirt+fence_wood', 3: 'fence_wood'});
      final untouched = const Garden(tiles: {0: 'gul~0'});
      expect(identical(dropUnknown(untouched, known), untouched), true);
    });
  });

  group('What is remembered', () {
    test('the garden, the view and the shelf come back as they were left', () {
      final state = KitState(
          garden: const Garden().grow().plant(7, 'gul~1').plant(8, 'road_dirt'),
          view: KitView.mobile,
          category: KitCategory.outer);
      final back = KitState.decode(state.encode());
      expect((back.garden.cols, back.garden.rows), (6, 12));
      expect(back.garden.tiles, state.garden.tiles);
      expect(back.view, KitView.mobile);
      expect(back.category, KitCategory.outer);
    });

    test('nothing saved, or something unreadable, is a fresh kit', () {
      for (final text in [null, '', 'not json', '[1,2]', '{"view": 7}', '{"garden": 3}']) {
        final s = KitState.decode(text);
        expect((s.garden.cols, s.garden.rows, s.view, s.category),
            (4, 8, KitView.web, KitCategory.flowers),
            reason: '$text');
      }
    });

    test('the phone is a tall one', () {
      expect(kPhoneHeight / kPhoneWidth, greaterThan(2.0));
    });
  });

  group('An Art Kit export says what it is by its name', () {
    test('flowers', () {
      expect(guessSprite('flower_gul.png'), (kind: ImportKind.sprite, name: 'gul', target: null));
      expect(guessSprite('flower_blue_rose_1.png'),
          (kind: ImportKind.sprite, name: 'blue_rose 2', target: null));
    });

    test('the woods', () {
      expect(guessSprite('tree_07.png'),
          (kind: ImportKind.forest, name: 'tree_07', target: 'tree_07'));
      expect(guessSprite('ROCK_3.PNG').target, 'rock_03');
      expect(guessSprite('bush_12.png').kind, ImportKind.forest);
      // not the Art Kit's naming: an artist's own tree stands like a flower
      expect(guessSprite('tree_big.png').kind, ImportKind.sprite);
    });

    test('grounds, and everything else', () {
      expect(guessSprite('road_marble.png').kind, ImportKind.ground);
      expect(guessSprite('floor-tiles.png').kind, ImportKind.ground);
      // what the Art Kit calls its exports of the game's four grounds
      for (final name in ['concrete.png', 'wood_path.png', 'dirt_path.png', 'stone_path.png']) {
        expect(guessSprite(name).kind, ImportKind.ground, reason: name);
      }
      expect(guessSprite('wood_path.png').name, 'wood_path');
      // a word, not a few letters of one
      expect(guessSprite('pathfinder.png').kind, ImportKind.sprite);
      expect(guessSprite('broadleaf.png').kind, ImportKind.sprite);
      expect(guessSprite('my drawing.png'),
          (kind: ImportKind.sprite, name: 'my drawing', target: null));
    });

    test('a vox is named after its file', () {
      expect(voxName('CoffeeLocal.vox'), 'CoffeeLocal');
      expect(voxName('a.b.VOX'), 'a.b');
    });
  });
}
