import 'dart:async';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

import 'pick.dart';

Future<List<PickedFile>> pickFiles({required String accept, bool multiple = false}) {
  final done = Completer<List<PickedFile>>();
  final input = web.HTMLInputElement()
    ..type = 'file'
    ..accept = accept
    ..multiple = multiple
    ..id = 'devkit-file'
    ..style.display = 'none';
  // In the page, not just in memory: some browsers only deliver `cancel` (and
  // Safari only opens the dialog at all) for an input that is attached.
  web.document.body!.append(input);

  Future<void> read() async {
    final list = input.files;
    final out = <PickedFile>[];
    for (var i = 0; list != null && i < list.length; i++) {
      final file = list.item(i)!;
      try {
        final buffer = await file.arrayBuffer().toDart;
        out.add(PickedFile(file.name, Uint8List.view(buffer.toDart)));
      } catch (_) {
        // picked, then moved or locked before it could be read
        throw PickError('${file.name} could not be read. Is it still where it was?');
      }
    }
    done.complete(out);
  }

  input.addEventListener(
      'change',
      ((web.Event _) {
        read().catchError((Object e) {
          if (!done.isCompleted) done.completeError(e);
        }).whenComplete(() => input.remove());
      }).toJS);
  input.addEventListener(
      'cancel',
      ((web.Event _) {
        input.remove();
        if (!done.isCompleted) done.complete(const []);
      }).toJS);
  input.click();
  return done.future;
}
