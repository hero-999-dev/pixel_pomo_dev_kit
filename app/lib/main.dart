// Pixel Pomo Dev Kit — the game's garden, with an artist's own sprites and
// voxel models in it.
//
// This is the page the launcher serves and opens in its own window. It draws
// with the game's engine (package:pixel_pomo), so a model looks here exactly as
// the game will draw it; the launcher keeps the artist's files.
import 'dart:ui' show PlatformDispatcher;

import 'package:flutter/gestures.dart' show PointerDeviceKind;
import 'package:flutter/material.dart';
import 'package:pixel_pomo/pixel.dart' show col;

import 'api.dart';
import 'controller.dart';
import 'screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final api = KitApi(Uri.base);
  // Whatever the page trips over goes to the launcher's log, in the artist's
  // folder: a kit that misbehaved on someone's machine leaves a trace there
  // instead of only in a console nobody can open.
  var reported = 0;
  void report(String what, Object error, StackTrace? stack) {
    if (reported++ >= 20) return;
    final trace = '${stack ?? ''}'.split('\n').take(12).join('\n');
    api.log('$what: $error\n$trace');
  }

  final shown = FlutterError.onError;
  FlutterError.onError = (details) {
    shown?.call(details);
    report('flutter', details.exception, details.stack);
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    report('uncaught', error, stack);
    return false; // and to the console too, as before
  };
  final kit = KitController(api)..start();
  runApp(DevKitApp(kit));
}

class DevKitApp extends StatelessWidget {
  final KitController kit;
  const DevKitApp(this.kit, {super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Pixel Pomo Dev Kit',
        debugShowCheckedModeBanner: false,
        scrollBehavior: const _KitScrollBehavior(),
        theme: ThemeData(
          useMaterial3: false,
          brightness: Brightness.dark,
          scaffoldBackgroundColor: col(kTheme.bg),
          splashFactory: NoSplash.splashFactory,
          splashColor: Colors.transparent,
          highlightColor: Colors.transparent,
        ),
        home: KitScreen(kit),
      );
}

/// The shelf can be dragged with the mouse, as every list in the game can.
class _KitScrollBehavior extends MaterialScrollBehavior {
  const _KitScrollBehavior();

  @override
  Set<PointerDeviceKind> get dragDevices => const {
        PointerDeviceKind.touch,
        PointerDeviceKind.mouse,
        PointerDeviceKind.stylus,
      };
}
