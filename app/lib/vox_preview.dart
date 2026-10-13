// A voxel model standing on a patch of garden tiles, drawn by the game's own
// mesh code — what the ADD 3D VOX FILE dialog shows on its right while the
// size and the turn are being chosen.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:pixel_pomo/engine/garden_engine.dart';

/// A mesh's footprint and height in tiles: ([wide] along x, [long] along y).
({double wide, double long, double tall}) meshFootprint(BoxMesh mesh) {
  var x0 = double.infinity, x1 = -double.infinity;
  var y0 = double.infinity, y1 = -double.infinity;
  for (final b in mesh.boxes) {
    x0 = math.min(x0, b.x - b.w / 2);
    x1 = math.max(x1, b.x + b.w / 2);
    y0 = math.min(y0, b.y - b.d / 2);
    y1 = math.max(y1, b.y + b.d / 2);
  }
  return (wide: x1 - x0, long: y1 - y0, tall: mesh.height);
}

/// [mesh] (as it is in the file: original size, unturned) shown [scale] times
/// larger and turned [turn] degrees, on a tile grid. [fit], when there is one,
/// is the footprint in tiles the model is being fitted into, outlined on the
/// ground. Drag sideways to walk round it.
class VoxPreview extends StatefulWidget {
  final BoxMesh mesh;
  final double scale;
  final int turn;
  final ({double wide, double long})? fit;
  const VoxPreview(this.mesh, {this.scale = 1, this.turn = 0, this.fit, super.key});

  @override
  State<VoxPreview> createState() => _VoxPreviewState();
}

class _VoxPreviewState extends State<VoxPreview> {
  // a quarter turn off square, so two walls and the top all show
  double _yaw = 0.6;

  @override
  Widget build(BuildContext context) => MouseRegion(
        cursor: SystemMouseCursors.grab,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onPanUpdate: (d) => setState(() => _yaw += d.delta.dx * 0.012),
          child: CustomPaint(
            painter: VoxPreviewPainter(widget.mesh,
                scale: widget.scale, turn: widget.turn, fit: widget.fit, yaw: _yaw),
            size: Size.infinite,
          ),
        ),
      );
}

class VoxPreviewPainter extends CustomPainter {
  final BoxMesh mesh;
  final double scale, yaw;
  final int turn;
  final ({double wide, double long})? fit;
  const VoxPreviewPainter(this.mesh,
      {required this.scale, required this.turn, required this.yaw, this.fit});

  /// The garden's own greens (GardenScreen's ground, a shade apart).
  static const _grassA = Color(0xFF4E9E3E), _grassB = Color(0xFF479238);

  @override
  void paint(Canvas canvas, Size size) {
    final foot = meshFootprint(mesh);
    final reach = [foot.wide * scale, foot.long * scale, fit?.wide ?? 0, fit?.long ?? 0]
        .reduce(math.max);
    // whole tiles either side of the one the model stands on, and one spare
    final rings = math.max(1, (reach / 2 + 0.5).ceil());
    final span = (rings * 2 + 1).toDouble();
    final tall = foot.tall * scale;
    // the patch is a square seen at any angle: its diagonal across, and that
    // squashed by the camera's tilt deep, with the model standing above it
    final across = span * 1.42;
    final t = math.min(size.width / across, size.height / (across * kVy + tall + 0.3));
    final centre = Offset(size.width / 2, size.height - across * kVy * t / 2 - 4);
    final p = Projector(1, 1, t, centre, yaw);

    canvas.save();
    canvas.clipRect(Offset.zero & size);
    for (var gy = -rings; gy <= rings; gy++) {
      for (var gx = -rings; gx <= rings; gx++) {
        final tile = Path()
          ..addPolygon([
            p.projectGrid(Offset(gx - 0.5, gy - 0.5)),
            p.projectGrid(Offset(gx + 0.5, gy - 0.5)),
            p.projectGrid(Offset(gx + 0.5, gy + 0.5)),
            p.projectGrid(Offset(gx - 0.5, gy + 0.5)),
          ], true);
        canvas.drawPath(tile, Paint()..color = (gx + gy).isEven ? _grassA : _grassB);
      }
    }
    final box = fit;
    if (box != null) {
      final outline = Path()
        ..addPolygon([
          p.projectGrid(Offset(-box.wide / 2, -box.long / 2)),
          p.projectGrid(Offset(box.wide / 2, -box.long / 2)),
          p.projectGrid(Offset(box.wide / 2, box.long / 2)),
          p.projectGrid(Offset(-box.wide / 2, box.long / 2)),
        ], true);
      canvas.drawPath(
          outline,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2
            ..color = const Color(0xFFFFE08A));
    }
    // the game's paintMesh, with the size the artist is choosing
    canvas.translate(centre.dx, centre.dy);
    canvas.scale(t * scale);
    canvas.drawVertices(mesh.batchFor(yaw + mesh.turn + turn * math.pi / 180), BlendMode.dst,
        Paint()..isAntiAlias = false);
    canvas.restore();
  }

  @override
  bool shouldRepaint(VoxPreviewPainter old) =>
      old.mesh != mesh ||
      old.scale != scale ||
      old.turn != turn ||
      old.yaw != yaw ||
      old.fit != fit;
}
