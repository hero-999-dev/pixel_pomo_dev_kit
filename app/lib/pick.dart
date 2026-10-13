// Asking the artist for a file. The real one is the browser's own file dialog
// (pick_web.dart); the stub is what the unit tests compile against, where there
// is no browser to ask.
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show visibleForTesting;

import 'pick_stub.dart' if (dart.library.js_interop) 'pick_web.dart' as impl;

class PickedFile {
  final String name;
  final Uint8List bytes;
  const PickedFile(this.name, this.bytes);
}

/// A picked file that could not be read, in words for the artist.
class PickError implements Exception {
  final String message;
  const PickError(this.message);
  @override
  String toString() => message;
}

/// Open the file dialog for [accept] (an `<input accept>` list, e.g. ".vox").
/// Empty when the artist cancels; throws [PickError] for a file that was
/// picked and then could not be read.
Future<List<PickedFile>> pickFiles({required String accept, bool multiple = false}) =>
    (pickFilesForTest ?? impl.pickFiles)(accept: accept, multiple: multiple);

/// A test stands in for the file dialog here; nothing else sets it.
@visibleForTesting
Future<List<PickedFile>> Function({required String accept, bool multiple})? pickFilesForTest;
