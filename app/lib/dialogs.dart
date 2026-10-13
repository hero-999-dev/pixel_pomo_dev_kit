// The kit's dialogs: adding a sprite, adding a voxel model (and making those
// choices again), the details of one thing, the trash, updates, where the
// files are, and the guide.
import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:pixel_pomo/engine/garden_engine.dart' show BoxMesh;
import 'package:pixel_pomo/pixel.dart';

import 'api.dart';
import 'controller.dart';
import 'kit.dart';
import 'pick.dart';
import 'screen.dart';
import 'vox_preview.dart';

/// One dialog frame for all of them, in the game's panel colours. [beside]
/// sits to the right of the title; [side] is a second column right of the
/// body, which a narrow window stacks underneath instead.
Widget kitDialog(BuildContext context,
        {required String title,
        required List<Widget> children,
        required List<Widget> actions,
        Widget? beside,
        Widget? side,
        double width = 520}) =>
    Dialog(
      backgroundColor: col(kTheme.panel),
      shape: Border.all(color: col(kTheme.onSurfaceDim), width: 2),
      insetPadding: const EdgeInsets.symmetric(horizontal: 28, vertical: 20),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: width),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: LayoutBuilder(builder: (context, box) {
            final body = SingleChildScrollView(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
            );
            final wide = side != null && box.maxWidth >= 700;
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                    spacing: 18,
                    runSpacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [Text(title, style: kitText(12)), ?beside]),
                const SizedBox(height: 18),
                Flexible(
                  child: wide
                      ? Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Expanded(child: body),
                          const SizedBox(width: 20),
                          SizedBox(width: 340, child: side),
                        ])
                      : side == null
                          ? body
                          : SingleChildScrollView(
                              child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [...children, const SizedBox(height: 16), side]),
                            ),
                ),
                const SizedBox(height: 20),
                Wrap(spacing: 10, runSpacing: 12, children: actions),
              ],
            );
          }),
        ),
      ),
    );

Widget _caption(String text) => Padding(
    padding: const EdgeInsets.only(top: 14, bottom: 8),
    child: Text(text, style: kitText(7, kTheme.onSurfaceDim)));

Widget _note(String text, {int? color}) =>
    Text(text, style: kitText(7, color ?? kTheme.onSurfaceDim).copyWith(height: 1.7));

Widget _choices<T>(List<(T, String)> options, T chosen, void Function(T) onPick, String keyPrefix) =>
    Wrap(spacing: 8, runSpacing: 10, children: [
      for (final (value, text) in options)
        kitButton(text, () => onPick(value),
            on: value == chosen, fontSize: 8, key: Key('$keyPrefix$text')),
    ]);

Widget _field(TextEditingController controller,
        {required Key key, void Function(String)? onChanged, bool wrong = false}) =>
    TextField(
      key: key,
      controller: controller,
      onChanged: onChanged,
      style: kitText(10),
      cursorColor: col(kTheme.accent),
      decoration: InputDecoration(
        isDense: true,
        enabledBorder: UnderlineInputBorder(
            borderSide:
                BorderSide(color: col(wrong ? kTheme.accent : kTheme.onSurfaceDim), width: 2)),
        focusedBorder:
            UnderlineInputBorder(borderSide: BorderSide(color: col(kTheme.accent), width: 2)),
      ),
    );

Widget _nameField(TextEditingController controller) =>
    _field(controller, key: const Key('nameField'));

final _categoryChoices = [for (final c in KitCategory.values) (c, c.label)];

/// The 2D / 3D tag, as the shelf wears it.
Widget _dimTag(bool is3d) => Container(
      width: 30,
      padding: const EdgeInsets.symmetric(vertical: 3),
      alignment: Alignment.center,
      color: col(is3d ? k3dColor : k2dColor),
      child: Text(is3d ? '3D' : '2D', style: kitText(7, 0xFF101010)),
    );

Future<void> _failed(BuildContext context, String what, Object error) => showDialog<void>(
      context: context,
      builder: (ctx) => kitDialog(ctx, title: what, children: [
        _note('$error', color: kTheme.onSurface),
      ], actions: [
        kitButton('OK', () => Navigator.pop(ctx), on: true, key: const Key('errorOk')),
      ]),
    );

Future<bool> _confirm(BuildContext context,
    {required String title, required String body, required String yes, String no = 'CANCEL'}) async {
  final answer = await showDialog<bool>(
    context: context,
    builder: (ctx) => kitDialog(ctx, title: title, children: [
      _note(body, color: kTheme.onSurface),
    ], actions: [
      kitButton(yes, () => Navigator.pop(ctx, true), on: true, key: const Key('confirmYes')),
      kitButton(no, () => Navigator.pop(ctx, false), key: const Key('confirmNo')),
    ]),
  );
  return answer == true;
}

/// The file dialog, with a picked-but-unreadable file said out loud.
Future<List<PickedFile>> _pick(BuildContext context,
    {required String accept, bool multiple = false}) async {
  try {
    return await pickFiles(accept: accept, multiple: multiple);
  } on PickError catch (e) {
    if (context.mounted) await _failed(context, 'NOT READ', e);
    return const [];
  }
}

// ---- please wait ---------------------------------------------------------------

/// Run [job] behind a "please wait" panel that cannot be dismissed: what is
/// being done, which step of [steps] it is on, and how long it has taken —
/// so a model that takes the converter twenty seconds does not look like a
/// kit that has stopped. [job] moves the panel on by calling its argument
/// with the index of the step it has reached.
Future<T> withProgress<T>(BuildContext context,
    {required String title,
    required List<String> steps,
    required Future<T> Function(void Function(int step) reached) job}) async {
  final at = ValueNotifier<int>(0);
  final navigator = Navigator.of(context, rootNavigator: true);
  var open = true;
  unawaited(showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => PopScope(canPop: false, child: _ProgressPanel(title, steps, at)),
  ).whenComplete(() => open = false));
  try {
    return await job((step) => at.value = step);
  } finally {
    if (open) navigator.pop();
  }
}

const Duration _kBeat = Duration(milliseconds: 150);

class _ProgressPanel extends StatefulWidget {
  final String title;
  final List<String> steps;
  final ValueNotifier<int> at;
  const _ProgressPanel(this.title, this.steps, this.at);

  @override
  State<_ProgressPanel> createState() => _ProgressPanelState();
}

class _ProgressPanelState extends State<_ProgressPanel> {
  Timer? _tick;
  int _beat = 0; // one every [_kBeat]: the pulse, and the count of seconds

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(_kBeat, (_) => setState(() => _beat++));
    widget.at.addListener(_moved);
  }

  void _moved() => setState(() {});

  @override
  void dispose() {
    _tick?.cancel();
    widget.at.removeListener(_moved);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final step = widget.at.value.clamp(0, widget.steps.length - 1);
    final seconds = (_kBeat * _beat).inSeconds;
    return kitDialog(context, title: widget.title, width: 460, children: [
      Text('PLEASE WAIT', key: const Key('pleaseWait'), style: kitText(9, kTheme.accent)),
      const SizedBox(height: 14),
      // one cell a step: done ones filled, the one in hand pulsing
      Row(children: [
        for (var i = 0; i < widget.steps.length; i++)
          Expanded(
            child: Container(
              height: 14,
              margin: EdgeInsets.only(right: i == widget.steps.length - 1 ? 0 : 4),
              decoration: BoxDecoration(
                border: Border.all(color: col(kTheme.onSurfaceDim), width: 2),
                color: i < step
                    ? col(kTheme.work)
                    : i == step
                        ? col(kTheme.accent).withValues(alpha: _beat.isEven ? 1 : 0.45)
                        : col(kTheme.bg),
              ),
            ),
          ),
      ]),
      const SizedBox(height: 14),
      for (var i = 0; i < widget.steps.length; i++)
        Padding(
          padding: const EdgeInsets.only(bottom: 7),
          child: Text(
              '${i < step ? 'DONE ' : i == step ? '>>>  ' : '     '}${widget.steps[i]}',
              key: Key('progressStep$i'),
              style: kitText(7, i == step ? kTheme.onSurface : kTheme.onSurfaceDim)),
        ),
      const SizedBox(height: 6),
      _note(seconds < 3
          ? 'The kit is working.'
          : 'The kit is working — $seconds s so far. A large model can take half a minute.'),
    ], actions: const []);
  }
}

// ---- add a 2D sprite ---------------------------------------------------------

/// ADD 2D SPRITE: ask for one or more .png files, then how each is used.
Future<void> addSpriteFlow(BuildContext context, KitController kit) async {
  final files = await _pick(context, accept: '.png,image/png', multiple: true);
  for (final file in files) {
    if (!context.mounted) return;
    final ui.Image image;
    try {
      image = await decodeImage(file.bytes);
    } catch (_) {
      if (context.mounted) {
        await _failed(context, 'NOT A PICTURE', '${file.name} could not be read as a PNG.');
      }
      continue;
    }
    if (!context.mounted) return;
    final guess = guessSprite(file.name);
    final go = await showDialog<_SpriteChoice>(
        context: context,
        builder: (_) => _SpriteDialog(
              title: 'ADD 2D SPRITE',
              confirm: 'ADD',
              fileName: file.name,
              image: image,
              name: guess.name.toUpperCase(),
              kind: guess.kind,
              category:
                  guess.kind == ImportKind.ground ? KitCategory.outer : KitCategory.flowers,
              forestTarget: guess.target,
            ));
    if (go == null || !context.mounted) continue;
    try {
      await withProgress(context,
          title: 'ADDING ${go.name.toUpperCase()}',
          steps: const ['KEEPING A COPY OF THE FILE', 'PUTTING IT ON THE SHELF'],
          job: (reached) => kit.addSprite(file.bytes,
              fileName: file.name,
              name: go.name,
              kind: go.kind,
              category: go.category,
              target: go.target));
    } on KitError catch (e) {
      if (context.mounted) await _failed(context, 'NOT ADDED', e);
    }
  }
}

class _SpriteChoice {
  final String name;
  final ImportKind kind;
  final KitCategory category;
  final String? target;
  const _SpriteChoice(this.name, this.kind, this.category, this.target);
}

/// The choices for a sprite — when it is added, and again from CHANGE.
class _SpriteDialog extends StatefulWidget {
  final String title, confirm, fileName, name;
  final ui.Image? image;
  final ImportKind kind;
  final KitCategory category;

  /// The forest sprite the file's name says it is, if it says one. A forest
  /// sprite already added stays one: [locked].
  final String? forestTarget;
  final bool locked;
  const _SpriteDialog(
      {required this.title,
      required this.confirm,
      required this.fileName,
      required this.image,
      required this.name,
      required this.kind,
      required this.category,
      this.forestTarget,
      this.locked = false});

  @override
  State<_SpriteDialog> createState() => _SpriteDialogState();
}

class _SpriteDialogState extends State<_SpriteDialog> {
  late final _name = TextEditingController(text: widget.name);
  late ImportKind _kind = widget.kind;
  late KitCategory _category = widget.category;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final img = widget.image;
    final target = widget.forestTarget;
    return kitDialog(context, title: widget.title, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (img != null)
          Container(
              color: const Color(0xFF4E9E3E),
              padding: const EdgeInsets.all(6),
              child: spritePreview(img, 96)),
        if (img != null) const SizedBox(width: 16),
        Expanded(
          child: _note(
              '${widget.fileName}${img == null ? '' : '\n${img.width} x ${img.height} px'}'),
        ),
      ]),
      _caption('NAME'),
      _nameField(_name),
      if (!widget.locked) ...[
        _caption('USE IT AS'),
        _choices<ImportKind>([
          (ImportKind.sprite, 'STANDING'),
          (ImportKind.ground, 'FLAT GROUND'),
          if (target != null) (ImportKind.forest, 'FOREST ${target.toUpperCase()}'),
        ], _kind, (k) => setState(() => _kind = k), 'use_'),
        const SizedBox(height: 10),
      ],
      _note(switch (_kind) {
        ImportKind.sprite => 'Stands on its tile and always faces you, like a flower. '
            'The game draws it into one tile whatever its size — its own flowers are '
            '16 art pixels across, saved 16 times larger.',
        ImportKind.ground => 'Lies flat and turns with the garden, like a path. '
            'It is stretched to cover exactly one tile.',
        _ => 'Takes the place of $target wherever it grows in the woods around the '
            'garden, at that sprite\'s own size.',
      }),
      if (_kind != ImportKind.forest) ...[
        _caption('SHELF'),
        _choices<KitCategory>(
            _categoryChoices, _category, (c) => setState(() => _category = c), 'shelf_'),
      ],
    ], actions: [
      kitButton(widget.confirm, () {
        final name = _name.text.trim();
        Navigator.pop(
            context,
            _SpriteChoice(name.isEmpty ? widget.name : name, _kind, _category,
                _kind == ImportKind.forest ? target : null));
      }, on: true, key: const Key('confirmAdd')),
      kitButton('CANCEL', () => Navigator.pop(context), key: const Key('cancelAdd')),
    ]);
  }
}

// ---- add a 3D vox file -------------------------------------------------------

/// ADD 3D VOX FILE: ask for a .vox, show what is in it, then how to bring it in.
Future<void> addVoxFlow(BuildContext context, KitController kit) async {
  final files = await _pick(context, accept: '.vox');
  if (files.isEmpty || !context.mounted) return;
  final file = files.first;
  final List<VoxModel> models;
  try {
    models = await withProgress(context,
        title: 'READING ${file.name}',
        steps: const ['READING THE FILE'],
        job: (_) => kit.api.inspectVox(file.bytes, file.name));
  } on KitError catch (e) {
    if (context.mounted) await _failed(context, 'NOT A VOX FILE', e);
    return;
  }
  if (!context.mounted) return;
  final go = await showDialog<VoxChoice>(
      context: context,
      builder: (_) => VoxDialog(
            title: 'ADD 3D VOX FILE',
            confirm: 'ADD',
            fileName: file.name,
            models: models,
            preview: (model) => kit.api.previewVox(file.bytes, file.name, model),
            name: voxName(file.name).toUpperCase(),
          ));
  if (go == null || !context.mounted) return;
  try {
    await withProgress(context,
        title: 'ADDING ${go.name.toUpperCase()}',
        steps: const ['SENDING THE FILE', 'CONVERTING THE MODEL', 'PUTTING IT ON THE SHELF'],
        job: (reached) async {
          // the launcher answers once, when the model is converted and kept;
          // the first step is over as soon as the file has been handed to it
          final sent = Future<void>.delayed(const Duration(milliseconds: 300), () => reached(1));
          await kit.addVox(file.bytes,
              fileName: file.name,
              name: go.name,
              category: go.category,
              model: go.model,
              turn: go.turn,
              wide: go.wide,
              long: go.long);
          await sent;
          reached(2);
        });
  } on KitError catch (e) {
    if (context.mounted) await _failed(context, 'NOT ADDED', e);
  }
}

/// What the artist chose in [VoxDialog]. [wide] and [long] are null for the
/// model's original size.
class VoxChoice {
  final String name;
  final KitCategory category;
  final int model, turn;
  final double? wide, long;
  const VoxChoice(this.name, this.category, this.model, this.turn, this.wide, this.long);
  bool get fitted => wide != null && long != null;
}

/// The choices for a voxel model, with the model itself on the right as they
/// are made — when it is added, and again from CHANGE.
class VoxDialog extends StatefulWidget {
  final String title, confirm, fileName, name;
  final List<VoxModel> models;

  /// One model of the file as a mesh, at its original size and unturned.
  final Future<BoxMesh> Function(int model) preview;
  final KitCategory category;
  final int model, turn;
  final double? wide, long;
  const VoxDialog(
      {required this.title,
      required this.confirm,
      required this.fileName,
      required this.models,
      required this.preview,
      required this.name,
      this.category = KitCategory.outer,
      this.model = 0,
      this.turn = 0,
      this.wide,
      this.long,
      super.key});

  @override
  State<VoxDialog> createState() => _VoxDialogState();
}

class _VoxDialogState extends State<VoxDialog> {
  late final _name = TextEditingController(text: widget.name);
  late final _wide = TextEditingController(text: trimNumber(widget.wide ?? 2));
  late final _long = TextEditingController(text: trimNumber(widget.long ?? 2));
  late final _turnText = TextEditingController(text: '${widget.turn}');
  late KitCategory _category = widget.category;
  late int _model = widget.model.clamp(0, widget.models.length - 1);
  late bool _fit = widget.wide != null && widget.long != null;

  BoxMesh? _mesh;
  String? _refused; // why this model cannot be shown, and so cannot be added
  int _asked = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [_name, _wide, _long, _turnText]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final mine = ++_asked;
    setState(() {
      _mesh = null;
      _refused = null;
    });
    try {
      final mesh = await widget.preview(_model);
      if (mounted && mine == _asked) setState(() => _mesh = mesh);
    } on KitError catch (e) {
      if (mounted && mine == _asked) setState(() => _refused = e.message);
    }
  }

  int? get _turn => parseTurn(_turnText.text);
  double? get _wideTiles => _fit ? parseFit(_wide.text) : null;
  double? get _longTiles => _fit ? parseFit(_long.text) : null;
  bool get _sizeOk => !_fit || (_wideTiles != null && _longTiles != null);

  void _setTurn(int degrees) => setState(() => _turnText.text = '${degrees % 360}');

  @override
  Widget build(BuildContext context) {
    final m = widget.models[_model];
    final mesh = _mesh;
    final turn = _turn;
    final base = mesh == null ? null : meshFootprint(mesh);
    final out = base == null || !_sizeOk
        ? null
        : voxFootprint(base.wide, base.long,
            turn: turn ?? 0, wide: _wideTiles, long: _longTiles);
    final ready = mesh != null && turn != null && _sizeOk;
    return kitDialog(context,
        title: widget.title,
        width: 940,
        // the scale, said once, where the eye starts
        beside: Text('ORIGINAL SIZE: 16 VOXELS = 1 TILE',
            key: const Key('scaleNote'), style: kitText(7, kTheme.work)),
        side: _previewPane(mesh, out, turn ?? 0),
        children: [
          _note('${widget.fileName}\n${m.size} voxels in the box, ${m.voxels} filled'),
          if (widget.models.length > 1) ...[
            _caption('THIS FILE HOLDS ${widget.models.length} MODELS — WHICH ONE'),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 118),
              child: SingleChildScrollView(
                child: _choices<int>([
                  for (var i = 0; i < widget.models.length; i++)
                    (i, '${i + 1}: ${widget.models[i].size}'),
                ], _model, (i) {
                  _model = i;
                  _load();
                }, 'model_'),
              ),
            ),
          ],
          _caption('NAME'),
          _nameField(_name),
          _caption('SIZE'),
          _choices<bool>(const [(false, 'ORIGINAL SIZE'), (true, 'FIT TO TILES')], _fit,
              (v) => setState(() => _fit = v), 'size_'),
          if (_fit) ...[
            const SizedBox(height: 12),
            Row(children: [
              Text('WIDE', style: kitText(7, kTheme.onSurfaceDim)),
              const SizedBox(width: 8),
              SizedBox(
                  width: 64,
                  child: _field(_wide,
                      key: const Key('fitWide'),
                      wrong: _wideTiles == null,
                      onChanged: (_) => setState(() {}))),
              const SizedBox(width: 14),
              Text('x   LONG', style: kitText(7, kTheme.onSurfaceDim)),
              const SizedBox(width: 8),
              SizedBox(
                  width: 64,
                  child: _field(_long,
                      key: const Key('fitLong'),
                      wrong: _longTiles == null,
                      onChanged: (_) => setState(() {}))),
              const SizedBox(width: 10),
              Text('TILES', style: kitText(7, kTheme.onSurfaceDim)),
            ]),
          ],
          const SizedBox(height: 10),
          if (!_sizeOk)
            _note('Each side is a number of tiles from ${trimNumber(kMinFit)} to ${trimNumber(kMaxFit)}.',
                color: kTheme.accent)
          else if (out == null)
            _note(_fit
                ? 'The model is made as large as goes into that footprint, keeping its shape.'
                : 'The size it has in the file.')
          else
            _note(
                '${_fit ? 'As large as goes into that footprint, keeping its shape. ' : ''}'
                'Comes out ${trimNumber(out.wide)} x ${trimNumber(out.long)} tiles, '
                '${trimNumber(base!.tall * out.scale)} tall.',
                color: kTheme.onSurface),
          _caption('TURN'),
          Row(children: [
            SizedBox(
                width: 64,
                child: _field(_turnText,
                    key: const Key('turnField'),
                    wrong: turn == null,
                    onChanged: (_) => setState(() {}))),
            const SizedBox(width: 8),
            Text('DEGREES', style: kitText(7, kTheme.onSurfaceDim)),
            const SizedBox(width: 14),
            for (final quarter in const [0, 90, 180, 270]) ...[
              kitButton('$quarter', () => _setTurn(quarter),
                  on: turn == quarter, fontSize: 8, key: Key('turn_$quarter')),
              const SizedBox(width: 6),
            ],
          ]),
          SliderTheme(
            data: SliderThemeData(
              activeTrackColor: col(kTheme.accent),
              inactiveTrackColor: col(kTheme.onSurfaceDim),
              thumbColor: col(kTheme.onSurface),
              overlayShape: SliderComponentShape.noOverlay,
              trackHeight: 4,
            ),
            child: Padding(
              padding: const EdgeInsets.only(top: 10, bottom: 6),
              child: Slider(
                key: const Key('turnSlider'),
                min: 0,
                max: 359,
                value: (turn ?? 0).toDouble(),
                onChanged: (v) => _setTurn(v.round()),
              ),
            ),
          ),
          _note(turn == null
              ? 'A turn is a whole number of degrees from 0 to 360.'
              : 'Any angle from 0 to 360. At 0, MagicaVoxel\'s front (-y) faces the camera.',
              color: turn == null ? kTheme.accent : null),
          _caption('SHELF'),
          _choices<KitCategory>(
              _categoryChoices, _category, (c) => setState(() => _category = c), 'shelf_'),
        ],
        actions: [
          kitButton(widget.confirm, () {
            final name = _name.text.trim();
            Navigator.pop(
                context,
                VoxChoice(name.isEmpty ? voxName(widget.fileName) : name, _category, _model,
                    turn!, _wideTiles, _longTiles));
          }, on: true, enabled: ready, key: const Key('confirmAdd')),
          kitButton('CANCEL', () => Navigator.pop(context), key: const Key('cancelAdd')),
        ]);
  }

  Widget _previewPane(
      BoxMesh? mesh, ({double wide, double long, double scale})? out, int turn) {
    final Widget view;
    if (mesh != null) {
      view = VoxPreview(mesh,
          key: const Key('voxPreview'),
          scale: out?.scale ?? 1,
          turn: turn,
          fit: _fit && _sizeOk ? (wide: _wideTiles!, long: _longTiles!) : null);
    } else if (_refused != null) {
      view = Padding(
        padding: const EdgeInsets.all(14),
        child: Center(
            child: Text(_refused!,
                key: const Key('previewRefused'),
                textAlign: TextAlign.center,
                style: kitText(7, kTheme.accent).copyWith(height: 1.7))),
      );
    } else {
      view = const _Converting();
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('PREVIEW', style: kitText(7, kTheme.onSurfaceDim)),
      const SizedBox(height: 8),
      Container(
        height: 330,
        decoration: BoxDecoration(
          color: const Color(0xFF2B5E24), // the woods' shade, behind the tiles
          border: Border.all(color: col(kTheme.onSurfaceDim), width: 2),
        ),
        child: view,
      ),
      const SizedBox(height: 8),
      _note(mesh == null
          ? (_refused == null ? 'The model is being converted...' : 'This model cannot be added.')
          : '${mesh.boxes.length} boxes.  Drag the picture to walk round it.'
              '${mesh.boxes.length > kHeavyBoxes ? '\nA heavy model — no phone has been tried with one this size.' : ''}',
          color: mesh != null && mesh.boxes.length > kHeavyBoxes ? kTheme.accent : null),
    ]);
  }
}

/// What the preview shows while the launcher converts the model.
class _Converting extends StatefulWidget {
  const _Converting();

  @override
  State<_Converting> createState() => _ConvertingState();
}

class _ConvertingState extends State<_Converting> {
  Timer? _tick;
  int _beat = 0;

  @override
  void initState() {
    super.initState();
    _tick = Timer.periodic(_kBeat, (_) => setState(() => _beat++));
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('CONVERTING — PLEASE WAIT',
              key: const Key('previewWait'), style: kitText(8, kTheme.onSurface)),
          const SizedBox(height: 14),
          Row(mainAxisSize: MainAxisSize.min, children: [
            for (var i = 0; i < 6; i++)
              Container(
                width: 16,
                height: 12,
                margin: const EdgeInsets.symmetric(horizontal: 2),
                color: col(_beat % 6 == i ? kTheme.accent : kTheme.panel),
              ),
          ]),
          const SizedBox(height: 14),
          Text((_kBeat * _beat).inSeconds < 3 ? '' : '${(_kBeat * _beat).inSeconds} s',
              style: kitText(7, kTheme.onSurfaceDim)),
        ]),
      );
}

// ---- the details of one thing, and changing them --------------------------------

/// What a right-click on a shelf tile opens: what the thing is and every choice
/// that was made when it was added, with CHANGE under them and MOVE TO TRASH.
/// One of the game's own objects has neither — it is the game's.
Future<void> showDetails(BuildContext context, KitController kit, KitItem item) {
  final id = item.id;
  return showDialog<void>(
    context: context,
    builder: (ctx) => AnimatedBuilder(
      animation: kit,
      builder: (ctx, _) {
        // CHANGE replaces the record; read it afresh each time
        final f = item.imported == null
            ? null
            : kit.imported.where((old) => old.id == id).firstOrNull;
        Widget row(String label, String value) => Padding(
              padding: const EdgeInsets.only(bottom: 9),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: 108, child: Text(label, style: kitText(7, kTheme.onSurfaceDim))),
                Expanded(
                    child: Text(value,
                        key: Key('detail_$label'),
                        style: kitText(7).copyWith(height: 1.5))),
              ]),
            );
        if (f == null) {
          return kitDialog(ctx, title: item.name, children: [
            Row(children: [
              _dimTag(item.is3d),
              const SizedBox(width: 12),
              Expanded(child: _note('PART OF THE GAME', color: kTheme.onSurface)),
            ]),
            const SizedBox(height: 16),
            row('KIND', item.is3d
                ? '3D — real geometry, it stays put while the garden turns'
                : item.isGround
                    ? '2D — lies flat on the ground and turns with the garden'
                    : '2D — a sprite that always faces you'),
            row('SHELF', item.category.label),
            row('ID', item.id),
            const SizedBox(height: 6),
            _note(item.imported == null
                ? 'One of the game\'s own objects. It cannot be changed or thrown away here.'
                : 'It is no longer on the shelf.'),
          ], actions: [
            kitButton('CLOSE', () => Navigator.pop(ctx), on: true, key: const Key('closeDetails')),
          ]);
        }
        return kitDialog(ctx, title: f.name.toUpperCase(), width: 600, children: [
          Row(children: [
            _dimTag(f.kind == ImportKind.vox),
            const SizedBox(width: 12),
            Expanded(child: _note('ADDED BY YOU', color: kTheme.onSurface)),
          ]),
          const SizedBox(height: 16),
          for (final (label, value) in f.choices) row(label, value),
          const SizedBox(height: 4),
          kitButton('CHANGE', () => changeFlow(ctx, kit, f),
              fontSize: 8, key: const Key('changeButton')),
          const SizedBox(height: 16),
          _note('The kit\'s copy of the file is kept in'),
          const SizedBox(height: 6),
          _pathButton(kit, '${kit.dataDir}${_sep(kit.dataDir)}library${_sep(kit.dataDir)}${f.id}',
              'item', f.id, const Key('itemFolder')),
        ], actions: [
          kitButton('CLOSE', () => Navigator.pop(ctx), on: true, key: const Key('closeDetails')),
          kitButton('MOVE TO TRASH', () async {
            try {
              await kit.moveToTrash(f);
              if (ctx.mounted) Navigator.pop(ctx);
            } on KitError catch (e) {
              if (ctx.mounted) await _failed(ctx, 'NOT MOVED', e);
            }
          }, key: const Key('trashButton')),
        ]);
      },
    ),
  );
}

/// The separator the artist's own paths are written with.
String _sep(String path) => path.contains('\\') ? '\\' : '/';

/// A folder's path as a button that opens it.
Widget _pathButton(KitController kit, String path, String which, String? id, Key key) =>
    MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        key: key,
        onTap: kit.online ? () => kit.openFolder(which, id) : null,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
          decoration: BoxDecoration(
              color: col(kTheme.bg), border: Border.all(color: const Color(0xFF4A4A4A), width: 2)),
          child: Text(path, style: kitText(7, kTheme.work).copyWith(height: 1.5)),
        ),
      ),
    );

/// CHANGE: the choices of ADD again, filled in as they were made.
Future<void> changeFlow(BuildContext context, KitController kit, ImportedFile f) async {
  if (f.kind != ImportKind.vox) {
    final go = await showDialog<_SpriteChoice>(
        context: context,
        builder: (_) => _SpriteDialog(
              title: 'CHANGE ${f.name.toUpperCase()}',
              confirm: 'CHANGE',
              fileName: f.source,
              image: kit.pictures[f.id],
              name: f.name,
              kind: f.kind,
              category: f.category,
              forestTarget: f.target,
              locked: f.kind == ImportKind.forest,
            ));
    if (go == null || !context.mounted) return;
    try {
      await kit.changeItem(f,
          name: go.name,
          category: go.category,
          kind: f.kind == ImportKind.forest ? null : go.kind);
    } on KitError catch (e) {
      if (context.mounted) await _failed(context, 'NOT CHANGED', e);
    }
    return;
  }
  final List<VoxModel> models;
  try {
    models = await withProgress(context,
        title: 'READING ${f.source}',
        steps: const ['READING THE KIT\'S COPY OF THE FILE'],
        job: (_) => kit.api.inspectItem(f.id));
  } on KitError catch (e) {
    if (context.mounted) await _failed(context, 'CANNOT BE CHANGED', e);
    return;
  }
  if (!context.mounted) return;
  final go = await showDialog<VoxChoice>(
      context: context,
      builder: (_) => VoxDialog(
            title: 'CHANGE ${f.name.toUpperCase()}',
            confirm: 'CHANGE',
            fileName: f.source,
            models: models,
            preview: (model) => kit.api.previewItem(f.id, model),
            name: f.name,
            category: f.category,
            model: f.model,
            turn: f.turn,
            wide: f.fitted ? f.fitWide : null,
            long: f.fitted ? f.fitLong : null,
          ));
  if (go == null || !context.mounted) return;
  try {
    await withProgress(context,
        title: 'CHANGING ${go.name.toUpperCase()}',
        steps: const ['CONVERTING THE MODEL AGAIN', 'PUTTING IT BACK ON THE SHELF'],
        job: (reached) => kit.changeItem(f,
            name: go.name,
            category: go.category,
            model: go.model,
            turn: go.turn,
            fitted: go.fitted,
            wide: go.wide,
            long: go.long));
  } on KitError catch (e) {
    if (context.mounted) await _failed(context, 'NOT CHANGED', e);
  }
}

// ---- what has been added -----------------------------------------------------

Future<void> showImported(BuildContext context, KitController kit) => showDialog<void>(
      context: context,
      builder: (ctx) => AnimatedBuilder(
        animation: kit,
        builder: (ctx, _) => kitDialog(ctx, title: 'IMPORTED FILES', width: 680, children: [
          if (kit.imported.isEmpty)
            _note('Nothing yet. ADD brings in a .png from the Art Kit or a .vox from MagicaVoxel.'),
          for (final f in kit.imported)
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Row(children: [
                _dimTag(f.kind == ImportKind.vox),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(f.name.toUpperCase(), style: kitText(9)),
                    const SizedBox(height: 6),
                    _note('${f.source} · ${f.details}'),
                  ]),
                ),
                const SizedBox(width: 12),
                kitButton(
                    'DETAILS',
                    () => showDetails(
                        ctx,
                        kit,
                        itemFor(f) ??
                            // a forest sprite has no tile on a shelf; its
                            // details are reached from here
                            KitItem(
                                id: f.id,
                                name: f.name.toUpperCase(),
                                category: f.category,
                                is3d: false,
                                imported: f)),
                    fontSize: 8,
                    key: Key('details_${f.id}')),
              ]),
            ),
        ], actions: [
          kitButton('CLOSE', () => Navigator.pop(ctx), on: true, key: const Key('closeImported')),
          kitButton('OPEN FOLDER', kit.openFolder, key: const Key('openFolder')),
        ]),
      ),
    );

// ---- the trash -----------------------------------------------------------------

/// TRASH, top right: what was taken off the shelves. Each thing goes back with
/// PUT BACK or is deleted for good with DELETE — the only place the kit
/// deletes anything.
Future<void> showTrash(BuildContext context, KitController kit) => showDialog<void>(
      context: context,
      builder: (ctx) => AnimatedBuilder(
        animation: kit,
        builder: (ctx, _) => kitDialog(ctx, title: 'TRASH', width: 720, children: [
          if (kit.trashed.isEmpty)
            _note('Nothing in the trash.\n\nRight-click something you added, on the shelf, and choose MOVE TO TRASH. It waits here until you put it back or delete it.')
          else
            _note('Taken off the shelves, not deleted. The kit still has each file.',
                color: kTheme.onSurface),
          if (kit.trashed.isNotEmpty) const SizedBox(height: 16),
          for (final t in kit.trashed)
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Row(children: [
                _dimTag(t.kind == ImportKind.vox),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(t.name.toUpperCase(), style: kitText(9)),
                    const SizedBox(height: 6),
                    _note('${t.source} · ${t.details}'),
                  ]),
                ),
                const SizedBox(width: 12),
                kitButton('PUT BACK', () async {
                  try {
                    await kit.restore(t);
                  } on KitError catch (e) {
                    if (ctx.mounted) await _failed(ctx, 'NOT PUT BACK', e);
                  }
                }, fontSize: 8, key: Key('restore_${t.trashKey}')),
                const SizedBox(width: 8),
                kitButton('DELETE', () async {
                  final sure = await _confirm(ctx,
                      title: 'DELETE ${t.name.toUpperCase()}?',
                      body: 'It is deleted from the Dev Kit for good, and the kit\'s copy of '
                          '${t.source} with it.\n\nThe file you added it from, wherever you keep '
                          'it, is not touched.',
                      yes: 'DELETE',
                      no: 'KEEP');
                  if (!sure) return;
                  try {
                    await kit.deleteForever(t);
                  } on KitError catch (e) {
                    if (ctx.mounted) await _failed(ctx, 'NOT DELETED', e);
                  }
                }, fontSize: 8, key: Key('delete_${t.trashKey}')),
              ]),
            ),
        ], actions: [
          kitButton('CLOSE', () => Navigator.pop(ctx), on: true, key: const Key('closeTrash')),
          kitButton('EMPTY THE TRASH', () async {
            final sure = await _confirm(ctx,
                title: 'EMPTY THE TRASH?',
                body: '${kit.trashed.length} '
                    '${kit.trashed.length == 1 ? 'thing is' : 'things are'} deleted from the Dev '
                    'Kit for good, with the kit\'s copies of their files.\n\nThe files you added '
                    'them from are not touched.',
                yes: 'DELETE ALL',
                no: 'KEEP');
            if (!sure) return;
            try {
              await kit.emptyTrash();
            } on KitError catch (e) {
              if (ctx.mounted) await _failed(ctx, 'NOT EMPTIED', e);
            }
          }, enabled: kit.trashed.isNotEmpty, key: const Key('emptyTrash')),
          kitButton('OPEN FOLDER', () => kit.openFolder('trash'), key: const Key('trashFolder')),
        ]),
      ),
    );

// ---- updates -------------------------------------------------------------------

/// UPDATE, top right: ask whether there is a newer kit, and install it.
Future<void> showUpdate(BuildContext context, KitController kit) {
  // an answer already in hand (the kit asks once when it opens) is shown as
  // it is; anything else is asked afresh
  if (!const {'available', 'downloading', 'ready', 'checking'}.contains(kit.update.state)) {
    unawaited(kit.checkUpdate());
  }
  return showDialog<void>(
    context: context,
    builder: (ctx) => AnimatedBuilder(
      animation: kit,
      builder: (ctx, _) {
        final u = kit.update;
        final mine = 'v${kit.version}';
        final List<Widget> body;
        var actions = <Widget>[
          kitButton('CLOSE', () => Navigator.pop(ctx), on: true, key: const Key('closeUpdate')),
        ];
        switch (u.state) {
          case 'available':
            body = [
              Text('v${u.latest} IS OUT', key: const Key('updateHead'), style: kitText(10, kTheme.work)),
              const SizedBox(height: 10),
              _note('You have $mine.', color: kTheme.onSurface),
              if (u.notes.trim().isNotEmpty) ...[
                _caption('WHAT CHANGED'),
                ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 160),
                    child: SingleChildScrollView(child: _note(u.notes.trim()))),
              ],
              const SizedBox(height: 14),
              _note(u.canUpdate
                  ? 'The kit downloads it, closes, and opens again as the new version.\nEverything you added stays exactly where it is — an update replaces the program only.'
                  : 'This copy cannot update itself: it is not the installed kit. Download the new version from\n${u.page}\nand start it — it updates the installed kit and keeps everything you added.'),
            ];
            actions = [
              if (u.canUpdate)
                kitButton('UPDATE NOW', kit.applyUpdate, on: true, key: const Key('updateNow')),
              kitButton('LATER', () => Navigator.pop(ctx),
                  on: !u.canUpdate, key: const Key('closeUpdate')),
            ];
          case 'downloading' || 'ready':
            final percent = (u.progress * 100).round();
            body = [
              Text(u.state == 'ready' ? 'RESTARTING...' : 'DOWNLOADING v${u.latest}  $percent%',
                  key: const Key('updateHead'), style: kitText(10, kTheme.work)),
              const SizedBox(height: 14),
              Container(
                height: 14,
                decoration:
                    BoxDecoration(border: Border.all(color: col(kTheme.onSurfaceDim), width: 2)),
                alignment: Alignment.centerLeft,
                child: FractionallySizedBox(
                    widthFactor: u.state == 'ready' ? 1 : u.progress.clamp(0.0, 1.0),
                    child: Container(color: col(kTheme.work))),
              ),
              const SizedBox(height: 14),
              _note('PLEASE WAIT. The kit closes and opens again by itself.\nYour files are not touched.'),
            ];
            actions = const [];
          case 'none':
            body = [
              Text('YOU HAVE THE NEWEST VERSION',
                  key: const Key('updateHead'), style: kitText(10, kTheme.work)),
              const SizedBox(height: 10),
              _note('$mine is the latest one published.', color: kTheme.onSurface),
            ];
          case 'failed':
            body = [
              Text('NOT CHECKED', key: const Key('updateHead'), style: kitText(10, kTheme.accent)),
              const SizedBox(height: 10),
              _note(u.message, color: kTheme.onSurface),
              const SizedBox(height: 10),
              _note('You have $mine. Nothing was changed.'),
            ];
            actions.add(kitButton('TRY AGAIN', kit.checkUpdate, key: const Key('updateRetry')));
          default:
            body = [
              Text('ASKING FOR THE LATEST VERSION...',
                  key: const Key('updateHead'), style: kitText(10)),
              const SizedBox(height: 10),
              _note('You have $mine.'),
            ];
        }
        return PopScope(
          canPop: actions.isNotEmpty,
          child: kitDialog(ctx, title: 'UPDATE', width: 600, children: body, actions: actions),
        );
      },
    ),
  );
}

// ---- where everything is ----------------------------------------------------------

/// What a click on the version number opens: which kit is running and where
/// everything it owns is kept. Each path opens the folder it names.
Future<void> showAbout(BuildContext context, KitController kit) {
  Widget row(String label, Widget value) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.only(top: 9),
            child: SizedBox(width: 108, child: Text(label, style: kitText(7, kTheme.onSurfaceDim))),
          ),
          Expanded(child: value),
        ]),
      );
  Widget plain(String text, Key key) => Padding(
      padding: const EdgeInsets.only(top: 9), child: Text(text, key: key, style: kitText(7)));
  final sep = _sep(kit.dataDir);
  return showDialog<void>(
    context: context,
    builder: (ctx) => kitDialog(ctx, title: 'ABOUT THE DEV KIT', width: 720, children: [
      row('VERSION', plain('v${kit.version}', const Key('aboutVersion'))),
      row(
          'BUILD',
          plain(
              switch (kit.build) {
                'installed' => 'INSTALLED',
                'source' => 'FROM SOURCE',
                'portable' => 'NOT INSTALLED — RUNNING WHERE IT WAS STARTED',
                _ => 'NO LAUNCHER — NOTHING IS KEPT',
              },
              const Key('aboutBuild'))),
      if (kit.online) ...[
        row('PROGRAM', _pathButton(kit, kit.programDir, 'program', null, const Key('aboutProgram'))),
        row('YOUR FILES', _pathButton(kit, kit.dataDir, 'files', null, const Key('aboutFiles'))),
        row(
            'TRASH',
            _pathButton(
                kit, '${kit.dataDir}${sep}trash', 'trash', null, const Key('aboutTrash'))),
        const SizedBox(height: 4),
        _note('Click a folder to open it.\n\n'
            'YOUR FILES holds everything you added — a copy of each file under its own name, in library — the garden as you left it, and devkit.log.\n\n'
            'An update replaces the program only. YOUR FILES stays as it is, and the trash is emptied by you and nobody else.'),
      ],
    ], actions: [
      kitButton('CLOSE', () => Navigator.pop(ctx), on: true, key: const Key('closeAbout')),
      if (kit.online)
        kitButton('CHECK FOR UPDATES', () {
          Navigator.pop(ctx);
          showUpdate(context, kit);
        }, key: const Key('aboutUpdate')),
    ]),
  );
}

// ---- the guide ---------------------------------------------------------------

Future<void> showGuide(BuildContext context, KitController kit) {
  Widget step(String head, String body) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(head, style: kitText(9, kTheme.accent)),
          const SizedBox(height: 8),
          _note(body, color: kTheme.onSurface),
        ]),
      );
  return showDialog<void>(
    context: context,
    builder: (ctx) => kitDialog(ctx, title: 'GUIDE', width: 680, children: [
      step('1  DRAW',
          '2D: in the Art Kit, "Export engine sprite" writes a .png.\n3D: in MagicaVoxel, save the model — the .vox file is what the kit reads.'),
      step('2  ADD',
          'ADD > ADD 2D SPRITE or ADD 3D VOX FILE, and pick your file. A model is shown as you choose its size and its turn. It lands on the shelf you choose, marked NEW.'),
      step('3  PLACE',
          'Pick it on the shelf at the bottom, then click a tile in the garden. Click the same tile again to take it off; ERASER clears a tile. Every object of the game is on the shelves too, sorted as the market sorts them.'),
      step('4  LOOK',
          'VIEW switches between the browser build\'s wide look and a phone\'s upright screen. Hold the right mouse button and drag to turn the garden, scroll to zoom, drag or use WASD to move. SHRINK and EXPAND resize the plot the way the game does.'),
      step('5  CHANGE, OR THROW AWAY',
          'Right-click anything on the shelf for its details. For something you added they are the choices you made, with CHANGE under them to make them again — its size, its turn, its name, its shelf — and MOVE TO TRASH.\nNothing is deleted by that: TRASH, top right, puts it back or deletes it for good.'),
      step('2D AND 3D',
          'A 2D sprite always faces you. A 3D model is real geometry: it stays where it is and you walk round it. Flowers and grounds are 2D; fences, houses and every .vox are 3D.'),
      step('A .VOX THAT COMES OUT RIGHT',
          'At its original size, 16 voxels are one garden tile; FIT TO TILES makes it as large as goes into the footprint you type, keeping its shape. Build it with its front toward MagicaVoxel\'s -y, or turn it by any angle when you add it. One model becomes one object. Only colours come across — glass, glow and metal are ignored.'),
      step(
          'YOUR FILES',
          kit.dataDir.isEmpty
              ? 'Kept by the Dev Kit.'
              : 'Everything you add is kept, under its own name, in\n${kit.dataDir}\nAn update replaces the program and leaves that folder alone. Click the version number, top left, to see where everything is.'),
    ], actions: [
      kitButton('CLOSE', () => Navigator.pop(ctx), on: true, key: const Key('closeGuide')),
      if (kit.online) kitButton('OPEN FOLDER', kit.openFolder, key: const Key('guideOpenFolder')),
    ]),
  );
}
