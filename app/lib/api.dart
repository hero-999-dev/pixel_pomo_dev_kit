// The kit's side of its conversation with the launcher.
//
// The launcher (the Python program the artist actually starts) serves this
// page and keeps everything that has to outlive it: the imported files and the
// garden, in the artist's own folder. It also does the jobs that belong on its
// side — turning a .vox into box meshes with the game's own converter, and
// updating the program.
import 'dart:convert' show jsonDecode, utf8;
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:pixel_pomo/engine/garden_engine.dart' show BoxMesh;

import 'kit.dart';

/// Something the launcher refused, in words meant for the artist.
class KitError implements Exception {
  final String message;
  const KitError(this.message);
  @override
  String toString() => message;
}

/// One model inside a .vox file.
class VoxModel {
  final int x, y, z, voxels;
  const VoxModel(this.x, this.y, this.z, this.voxels);
  String get size => '${x}x${y}x$z';
}

/// Where an update stands, as the launcher tells it.
class UpdateStatus {
  /// idle, checking, none, available, downloading, ready or failed.
  final String state;
  final String version, latest, notes, message, page;
  final double progress;

  /// False for a kit that cannot swap itself (run from source, or not
  /// installed): it can still say that a newer version exists.
  final bool canUpdate;

  const UpdateStatus(
      {this.state = 'idle',
      this.version = '',
      this.latest = '',
      this.notes = '',
      this.message = '',
      this.page = '',
      this.progress = 0,
      this.canUpdate = false});

  bool get available => state == 'available';

  static UpdateStatus fromJson(Object? json) {
    if (json is! Map) return const UpdateStatus();
    String s(String key) => json[key] is String ? json[key] as String : '';
    return UpdateStatus(
      state: s('state').isEmpty ? 'idle' : s('state'),
      version: s('version'),
      latest: s('latest'),
      notes: s('notes'),
      message: s('message'),
      page: s('page'),
      progress: json['progress'] is num ? (json['progress'] as num).toDouble() : 0,
      canUpdate: json['canUpdate'] == true,
    );
  }
}

class KitApi {
  final http.Client _client;
  final Uri _base;

  /// [base] is the page's own address; the launcher answers under `api/` and
  /// `library/` beside it.
  KitApi(Uri base, [http.Client? client])
      : _base = base,
        _client = client ?? http.Client();

  Uri _at(String path, [Map<String, String>? query]) =>
      _base.resolve(path).replace(queryParameters: query);

  Future<dynamic> _json(Future<http.Response> request) async {
    final http.Response r;
    try {
      r = await request;
    } catch (_) {
      throw const KitError('The Dev Kit is not answering. Close this window and start it again.');
    }
    dynamic body;
    try {
      body = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      body = null;
    }
    if (r.statusCode >= 400) {
      throw KitError(body is Map && body['error'] is String
          ? body['error'] as String
          : 'The Dev Kit answered ${r.statusCode}.');
    }
    return body;
  }

  /// `{version, dataDir, programDir, build, trash}` — and proof that it is the
  /// launcher answering.
  Future<Map<String, dynamic>> hello() async =>
      (await _json(_client.get(_at('api/hello')))) as Map<String, dynamic>;

  List<ImportedFile> _files(dynamic body) => [
        for (final entry in (body as Map)['items'] as List) ?ImportedFile.fromJson(entry),
      ];

  Future<List<ImportedFile>> library() async =>
      _files(await _json(_client.get(_at('api/library'))));

  /// The bytes of an imported item's own file.
  Future<Uint8List> fileOf(ImportedFile f) async {
    // the sprite's own name: it may hold a space, an accent, a '#'
    final r = await _client
        .get(_base.resolve('library/${f.id}/${Uri.encodeComponent(f.file)}'));
    if (r.statusCode != 200) throw KitError('${f.name}: its file is missing from the library.');
    return r.bodyBytes;
  }

  // ---- adding ----------------------------------------------------------------

  List<VoxModel> _models(dynamic body) => [
        for (final m in (body as Map)['models'] as List)
          VoxModel(m['x'] as int, m['y'] as int, m['z'] as int, m['voxels'] as int),
      ];

  BoxMesh _mesh(dynamic body) {
    try {
      return BoxMesh.fromJson(body as Map<String, dynamic>);
    } catch (_) {
      throw const KitError('The Dev Kit converted the model but the result could not be read.');
    }
  }

  /// What is in a .vox before it is converted: one entry a model.
  Future<List<VoxModel>> inspectVox(Uint8List bytes, String fileName) async => _models(
      await _json(_client.post(_at('api/inspect/vox', {'file': fileName}), body: bytes)));

  /// One model of a .vox as the game would draw it at its original size,
  /// unturned — to show before anything is added.
  Future<BoxMesh> previewVox(Uint8List bytes, String fileName, int model) async =>
      _mesh(await _json(_client.post(
          _at('api/preview/vox', {'file': fileName, 'model': '$model'}),
          body: bytes)));

  /// [wide] x [long] is a footprint in tiles to fit the model into; without
  /// them it keeps its original size, 16 voxels to a tile.
  Future<ImportedFile> importVox(Uint8List bytes,
      {required String fileName,
      required String name,
      required KitCategory category,
      required int model,
      required int turn,
      double? wide,
      double? long}) async {
    final body = await _json(_client.post(
        _at('api/import/vox', {
          'file': fileName,
          'name': name,
          'category': category.name,
          'model': '$model',
          'turn': '$turn',
          if (wide != null && long != null) ...{'wide': '$wide', 'long': '$long'},
        }),
        body: bytes));
    return _imported(body);
  }

  Future<ImportedFile> importSprite(Uint8List bytes,
      {required String fileName,
      required String name,
      required ImportKind kind,
      required KitCategory category,
      String? target}) async {
    final body = await _json(_client.post(
        _at('api/import/sprite', {
          'file': fileName,
          'name': name,
          'kind': kind.name,
          'category': category.name,
          'target': ?target,
        }),
        body: bytes));
    return _imported(body);
  }

  ImportedFile _imported(dynamic body) {
    final file = ImportedFile.fromJson(body);
    if (file == null) throw const KitError('The Dev Kit saved the file but could not read it back.');
    return file;
  }

  // ---- what is already there ---------------------------------------------------

  /// The models in the .vox an added model was made from.
  Future<List<VoxModel>> inspectItem(String id) async =>
      _models(await _json(_client.get(_at('api/inspect/item/$id'))));

  Future<BoxMesh> previewItem(String id, int model) async =>
      _mesh(await _json(_client.get(_at('api/preview/item/$id', {'model': '$model'}))));

  /// Make the choices again for something already added. A model is converted
  /// afresh from the kit's copy of the file; what is not passed stays.
  Future<ImportedFile> change(String id,
      {String? name,
      KitCategory? category,
      ImportKind? kind,
      int? model,
      int? turn,
      bool? fitted,
      double? wide,
      double? long}) async {
    final body = await _json(_client.post(_at('api/change/$id', {
      'name': ?name,
      'category': ?category?.name,
      'kind': ?kind?.name,
      'model': ?model?.toString(),
      'turn': ?turn?.toString(),
      'size': ?(fitted == null ? null : (fitted ? 'fit' : 'original')),
      if (fitted == true && wide != null && long != null) ...{'wide': '$wide', 'long': '$long'},
    })));
    return _imported(body);
  }

  // ---- the trash -----------------------------------------------------------------

  Future<List<ImportedFile>> trash() async => _files(await _json(_client.get(_at('api/trash'))));

  /// Take something off the shelf. Its folder moves to the trash, whole.
  Future<void> moveToTrash(String id) => _json(_client.post(_at('api/trash/$id')));

  Future<ImportedFile> restore(String trashKey) async =>
      _imported(await _json(_client.post(_at('api/restore/$trashKey'))));

  /// Delete one thing in the trash for good.
  Future<void> deleteForever(String trashKey) =>
      _json(_client.delete(_at('api/trash/$trashKey')));

  Future<void> emptyTrash() => _json(_client.delete(_at('api/trash')));

  // ---- the garden, folders, updates ------------------------------------------------

  Future<KitState> loadState() async {
    final r = await _client.get(_at('api/state'));
    return KitState.decode(r.statusCode == 200 ? utf8.decode(r.bodyBytes) : null);
  }

  Future<void> saveState(KitState state) =>
      _json(_client.put(_at('api/state'), body: utf8.encode(state.encode())));

  /// Show a folder in Explorer / Finder: `files` (everything the artist
  /// added), `program`, `trash`, or `item` with the [id] of one added thing.
  Future<void> openFolder([String which = 'files', String? id]) =>
      _json(_client.post(_at('api/open-folder', {'which': which, 'id': ?id})));

  Future<UpdateStatus> updateStatus() async =>
      UpdateStatus.fromJson(await _json(_client.get(_at('api/update'))));

  /// Ask for the latest release; the answer is the status.
  Future<UpdateStatus> checkUpdate() async =>
      UpdateStatus.fromJson(await _json(_client.post(_at('api/update/check'))));

  /// Start downloading the update. The kit closes and reopens by itself.
  Future<UpdateStatus> applyUpdate() async =>
      UpdateStatus.fromJson(await _json(_client.post(_at('api/update/apply'))));

  /// Leave a line in the launcher's log. Never throws: this is what is called
  /// when something has already gone wrong.
  Future<void> log(String text) async {
    try {
      await _client.post(_at('api/log'), body: utf8.encode(text));
    } catch (_) {}
  }
}
