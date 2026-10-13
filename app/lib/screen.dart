// The kit's one screen: a bar of controls, the garden, and the shelf of
// everything that can be put in it.
import 'dart:ui' as ui;

import 'package:flutter/gestures.dart' show PointerScrollEvent;
import 'package:flutter/material.dart';
import 'package:pixel_pomo/engine/garden_engine.dart';
import 'package:pixel_pomo/engine/garden_view.dart';
import 'package:pixel_pomo/logic.dart';
import 'package:pixel_pomo/pixel.dart';
import 'package:pixel_pomo/strings.dart' show t;

import 'controller.dart';
import 'dialogs.dart';
import 'kit.dart';

/// The kit wears the game's own DARK theme.
const PixelTheme kTheme = Themes.dark;

/// The game's garden palette (GardenScreen's) — a garden is always green.
const int kGardenGround = 0xFF4E9E3E, kGardenSoil = 0xFF6B4A2B;

/// The colours of the 2D and 3D labels.
const int k2dColor = 0xFF46E08A, k3dColor = 0xFF58A6FF;

TextStyle kitText(double size, [int? color]) =>
    pixelStyle('en', size, col(color ?? kTheme.onSurface));

/// A toolbar button in the game's own button style. [on] paints it as chosen.
Widget kitButton(String text, VoidCallback? onTap,
        {bool on = false, bool enabled = true, Key? key, double fontSize = 9}) =>
    PixelButton(
      key: key,
      text: text,
      fill: on ? kTheme.accent : kTheme.panel,
      border: on ? kTheme.onSurface : kTheme.onSurfaceDim,
      textColor: on ? kTheme.onAccent : kTheme.onSurface,
      shadow: kTheme.shadow,
      lang: 'en',
      fontSize: fontSize,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
      opacity: enabled ? 1 : 0.4,
      onTap: enabled ? onTap : null,
    );

class KitScreen extends StatefulWidget {
  final KitController kit;
  const KitScreen(this.kit, {super.key});

  @override
  State<KitScreen> createState() => _KitScreenState();
}

class _KitScreenState extends State<KitScreen> {
  // One GardenView for both looks: it moves between them instead of being
  // rebuilt, so the camera gestures in progress and the critters carry over.
  final GlobalKey _gardenKey = GlobalKey(debugLabel: 'garden');
  final ScrollController _shelfScroll = ScrollController();
  int _addedSeen = 0;

  KitController get kit => widget.kit;

  @override
  void dispose() {
    _shelfScroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: kit,
      builder: (context, _) {
        final bank = kit.bank;
        if (kit.added != _addedSeen) {
          // A new item goes on the far end of its shelf, usually off the edge
          // of the window. Once it has been laid out, slide the shelf to it.
          _addedSeen = kit.added;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!_shelfScroll.hasClients) return;
            _shelfScroll.animateTo(_shelfScroll.position.maxScrollExtent,
                duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
          });
        }
        return Scaffold(
          backgroundColor: col(kTheme.bg),
          body: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _bar(context),
              Expanded(
                child: kit.fatal != null
                    ? _message(kit.fatal!)
                    : bank == null
                        ? _message('LOADING THE GARDEN...')
                        : _stage(bank),
              ),
              _statusLine(),
              _shelf(bank),
            ],
          ),
        );
      },
    );
  }

  Widget _message(String text) => Center(
      child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(text, textAlign: TextAlign.center, style: kitText(10, kTheme.onSurfaceDim))));

  // ---- the bar ---------------------------------------------------------------

  Widget _bar(BuildContext context) {
    final g = kit.garden;
    Widget label(String text) => Padding(
        padding: const EdgeInsets.only(right: 8),
        child: Text(text, style: kitText(8, kTheme.onSurfaceDim)));
    Widget group(List<Widget> children) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0 && children[i - 1] is! Padding) const SizedBox(width: 8),
            children[i],
          ]
        ]);
    final update = kit.update;
    final controls = Wrap(
        spacing: 20,
        runSpacing: 12,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          group([
            Image.asset('assets/icon/app_icon.png',
                width: 24,
                height: 24,
                filterQuality: FilterQuality.none,
                errorBuilder: (_, _, _) => const SizedBox(width: 24, height: 24)),
            Text('PIXEL POMO DEV KIT', style: kitText(10)),
            if (kit.version.isNotEmpty)
              // the version is a button: it opens where everything is kept
              MouseRegion(
                cursor: SystemMouseCursors.click,
                child: GestureDetector(
                  key: const Key('versionButton'),
                  onTap: () => showAbout(context, kit),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
                    decoration: BoxDecoration(
                        border: Border.all(color: col(kTheme.onSurfaceDim), width: 1)),
                    child: Text('v${kit.version}', style: kitText(7, kTheme.onSurfaceDim)),
                  ),
                ),
              ),
          ]),
          group([
            label('VIEW'),
            kitButton('WEB', () => kit.show(KitView.web),
                on: kit.view == KitView.web, key: const Key('viewWeb')),
            kitButton('MOBILE', () => kit.show(KitView.mobile),
                on: kit.view == KitView.mobile, key: const Key('viewMobile')),
          ]),
          group([
            _addMenu(context),
            kitButton('GUIDE', () => showGuide(context, kit), key: const Key('guideButton')),
          ]),
          group([
            label('GARDEN'),
            kitButton('SHRINK', kit.shrinkGarden,
                enabled: canShrink(g), key: const Key('shrinkButton')),
            Text('${g.cols}x${g.rows}', key: const Key('gardenSize'), style: kitText(10)),
            kitButton('EXPAND', kit.growGarden, enabled: canGrow(g), key: const Key('expandButton')),
            kitButton('CLEAR', kit.clearGarden,
                enabled: g.tiles.isNotEmpty, key: const Key('clearButton')),
          ]),
        ]);
    return Container(
      color: col(kTheme.panel),
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 14),
      // The controls wrap, so a narrow window gets a second row instead of a
      // clipped one; UPDATE and TRASH keep the top right corner either way.
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: controls),
        const SizedBox(width: 16),
        group([
          kitButton(
              update.available ? 'UPDATE  v${update.latest}' : 'UPDATE',
              () => showUpdate(context, kit),
              on: update.available,
              enabled: kit.online,
              key: const Key('updateButton')),
          kitButton(
              kit.trashed.isEmpty ? 'TRASH' : 'TRASH  ${kit.trashed.length}',
              () => showTrash(context, kit),
              enabled: kit.online,
              key: const Key('trashBarButton')),
        ]),
      ]),
    );
  }

  Widget _addMenu(BuildContext context) {
    PopupMenuItem<String> entry(String value, String text, [String? note]) => PopupMenuItem(
          value: value,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(text, style: kitText(9)),
              if (note != null) ...[
                const SizedBox(height: 5),
                Text(note, style: kitText(7, kTheme.onSurfaceDim)),
              ],
            ],
          ),
        );
    return PopupMenuButton<String>(
      key: const Key('addButton'),
      tooltip: '',
      color: col(kTheme.panel),
      shape: Border.all(color: col(kTheme.onSurfaceDim), width: 2),
      position: PopupMenuPosition.under,
      enabled: kit.bank != null && kit.online,
      onSelected: (choice) => switch (choice) {
        'sprite' => addSpriteFlow(context, kit),
        'vox' => addVoxFlow(context, kit),
        _ => showImported(context, kit),
      },
      itemBuilder: (_) => [
        entry('sprite', 'ADD 2D SPRITE', 'a .png — an Art Kit export'),
        entry('vox', 'ADD 3D VOX FILE', 'a .vox — saved from MagicaVoxel'),
        const PopupMenuDivider(),
        entry('imported', 'IMPORTED FILES', '${kit.imported.length} added so far'),
      ],
      // the button only draws; the menu owns the press
      child: IgnorePointer(
          child: kitButton('ADD', () {}, on: true, enabled: kit.bank != null && kit.online)),
    );
  }

  // ---- the garden ------------------------------------------------------------

  Widget _stage(SpriteBank bank) {
    final garden = GardenView(
      key: _gardenKey,
      garden: kit.garden,
      sprites: bank,
      customizing: kit.brushing, // the tile grid shows while there is a brush
      onTapTile: kit.tapTile,
      groundColor: kGardenGround,
      soilColor: kGardenSoil,
      uiColor: kTheme.onSurface,
      panelColor: kTheme.panel,
      lang: 'en',
      tr: (key) => t('en', key),
      camera: kit.camera,
    );
    if (kit.view == KitView.web) return garden;
    // A phone: the garden is laid out on a phone's own logical screen and the
    // whole frame scaled to fit, so a tile, a sprite and the corner button all
    // keep the size they have against each other on the real thing.
    return Container(
      color: const Color(0xFF0B0B0B),
      padding: const EdgeInsets.all(14),
      alignment: Alignment.center,
      child: AspectRatio(
        aspectRatio: kPhoneWidth / kPhoneHeight,
        child: Container(
          key: const Key('phoneFrame'),
          decoration: BoxDecoration(
            color: Colors.black,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: const Color(0xFF3C3C3C), width: 2),
          ),
          padding: const EdgeInsets.all(7),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(15),
            child: FittedBox(
              fit: BoxFit.contain,
              child: SizedBox(width: kPhoneWidth, height: kPhoneHeight, child: garden),
            ),
          ),
        ),
      ),
    );
  }

  Widget _statusLine() {
    final item = kit.brushItem;
    final String text;
    var color = kTheme.onSurfaceDim;
    if (kit.status.isNotEmpty) {
      text = kit.status;
      color = kit.statusIsError ? kTheme.accent : kTheme.work;
    } else if (kit.erasing) {
      text = 'ERASER — click a tile to clear it.';
    } else if (item != null) {
      text = '${item.name} (${item.dimLabel}) — click a tile to place it, click it again to take it off.';
    } else {
      text = 'Pick something below to place it — right-click it for its details.  Right-drag turns the garden, the wheel zooms, drag or WASD moves it.';
    }
    return Container(
      color: col(kTheme.bg),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
      child: Text(text,
          key: const Key('statusLine'),
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: kitText(8, color).copyWith(height: 1.5)),
    );
  }

  // ---- the shelf -------------------------------------------------------------

  Widget _shelf(SpriteBank? bank) {
    final items = kit.shelf;
    return Container(
      color: col(kTheme.panel),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(spacing: 8, runSpacing: 10, children: [
            for (final c in KitCategory.values)
              kitButton(c.label, () => kit.showCategory(c),
                  on: kit.category == c, key: Key('category_${c.name}')),
          ]),
          const SizedBox(height: 12),
          SizedBox(
            height: 112,
            // the wheel is the hand an artist has on the mouse; a sideways list
            // only answers shift+wheel by default
            child: Listener(
              onPointerSignal: (e) {
                if (e is! PointerScrollEvent || !_shelfScroll.hasClients) return;
                final to = _shelfScroll.offset + e.scrollDelta.dy + e.scrollDelta.dx;
                _shelfScroll.jumpTo(to.clamp(0.0, _shelfScroll.position.maxScrollExtent));
              },
              child: Scrollbar(
                controller: _shelfScroll,
                thumbVisibility: true,
                // A Row, not a lazy list: with forty-odd tiles there is nothing
                // to save, and a lazy list only estimates how long it is, so
                // sliding to a newly added item stopped short of it.
                child: SingleChildScrollView(
                  controller: _shelfScroll,
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    _tile(
                      key: const Key('item_eraser'),
                      name: 'ERASER',
                      chosen: kit.erasing,
                      onTap: kit.pickEraser,
                      picture: Icon(Icons.clear, size: 34, color: col(kTheme.onSurfaceDim)),
                    ),
                    for (final item in items)
                      _tile(
                        key: Key('item_${item.id}'),
                        name: item.name,
                        chosen: !kit.erasing && kit.brushItem?.id == item.id,
                        onTap: () => kit.pick(item),
                        onDetails: () => showDetails(context, kit, item),
                        picture: _picture(item, bank),
                        dim: item.dimLabel,
                        added: item.imported != null,
                      ),
                    if (items.isEmpty)
                      Padding(
                        padding: const EdgeInsets.only(left: 12),
                        child: Center(
                            child: Text(
                                '${t('en', 'comingSoon')} — nothing of the game\'s is on this shelf yet.\nADD puts your own here.',
                                style: kitText(8, kTheme.onSurfaceDim).copyWith(height: 1.7))),
                      ),
                  ]),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _picture(KitItem item, SpriteBank? bank) {
    final file = item.imported;
    if (file == null) {
      return Image.asset('assets/objects/${item.thumb}.png',
          filterQuality: FilterQuality.none,
          fit: BoxFit.contain,
          errorBuilder: (_, _, _) => const SizedBox());
    }
    if (file.kind == ImportKind.vox) {
      final mesh = bank?.mesh(file.id);
      return mesh == null ? const SizedBox() : CustomPaint(painter: MeshThumbPainter(mesh));
    }
    return RawImage(
        image: kit.pictures[file.id], filterQuality: FilterQuality.none, fit: BoxFit.contain);
  }

  Widget _tile(
      {required Key key,
      required String name,
      required bool chosen,
      required VoidCallback onTap,
      VoidCallback? onDetails,
      required Widget picture,
      String? dim,
      bool added = false}) {
    Widget tag(String text, int fill) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 2),
        color: col(fill),
        child: Text(text, style: kitText(6, 0xFF101010)));
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: GestureDetector(
        key: key,
        onTap: onTap,
        // the right button: what it is, and for something added, CHANGE and
        // MOVE TO TRASH
        onSecondaryTap: onDetails,
        child: Container(
          width: 100,
          padding: const EdgeInsets.fromLTRB(5, 5, 5, 4),
          decoration: BoxDecoration(
            color: col(chosen ? 0xFF3A2A2B : kTheme.bg),
            border: Border.all(
                color: col(chosen ? kTheme.accent : 0xFF4A4A4A), width: chosen ? 3 : 2),
          ),
          child: Column(
            children: [
              Expanded(
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Padding(padding: const EdgeInsets.all(2), child: picture),
                    if (dim != null)
                      Positioned(
                          right: 0, top: 0, child: tag(dim, dim == '3D' ? k3dColor : k2dColor)),
                    if (added) Positioned(left: 0, top: 0, child: tag('NEW', kTheme.accent)),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              SizedBox(
                height: 20,
                child: Center(
                  child: Text(name,
                      maxLines: 2,
                      textAlign: TextAlign.center,
                      overflow: TextOverflow.ellipsis,
                      style: kitText(6).copyWith(height: 1.4)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A voxel model drawn small, by the game's own mesh painter — the same three
/// quarters view it has standing in the garden.
class MeshThumbPainter extends CustomPainter {
  final BoxMesh mesh;
  const MeshThumbPainter(this.mesh);

  /// A quarter turn off square, so two walls and the top all show.
  static const double yaw = 0.6;

  // The thumbnail's own triangle list, built once a mesh. Not the mesh's
  // cached one — that holds one yaw, the garden's, and borrowing it here would
  // make the garden build it again on its next frame — and not rebuilt on
  // every paint either: a shelf repaints whenever it scrolls, and sorting a
  // nine-thousand-box model each time is what makes a window stop answering.
  static final Expando<ui.Vertices> _kept = Expando('thumb');

  @override
  void paint(Canvas canvas, Size size) {
    // A footprint `tiles` across is at most tiles*sqrt2 wide on screen once
    // turned, and that same diagonal squashed by kVy deep; the model stands
    // `height` above the middle of it.
    final across = mesh.tiles * 1.42;
    final tall = mesh.height + across * kVy;
    final scale = [size.width / across, size.height / tall].reduce((a, b) => a < b ? a : b);
    // the footprint reaches as far below its centre as above it, so the whole
    // drawing is centred when the centre sits half the model's height down
    final ground = size.height / 2 + mesh.height * scale / 2;
    var vertices = _kept[mesh];
    if (vertices == null) {
      final tri = meshTriangles(mesh, yaw + mesh.turn);
      vertices = _kept[mesh] =
          ui.Vertices.raw(ui.VertexMode.triangles, tri.positions, colors: tri.colors);
    }
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    canvas.translate(size.width / 2, ground);
    canvas.scale(scale);
    canvas.drawVertices(vertices, BlendMode.dst, Paint()..isAntiAlias = false);
    canvas.restore();
  }

  @override
  bool shouldRepaint(MeshThumbPainter old) => old.mesh != mesh;
}

/// Kept for the dialogs, which preview a sprite before it is added.
Widget spritePreview(ui.Image image, double size) => SizedBox(
    width: size,
    height: size,
    child: RawImage(image: image, filterQuality: FilterQuality.none, fit: BoxFit.contain));
