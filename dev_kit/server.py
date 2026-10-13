"""The launcher's web server: the page, and the few things the page asks for.

It listens on this machine only (127.0.0.1) and answers one page — its own.

    GET    /                          the kit (the Flutter build)
    GET    /api/hello                 {app, version, dataDir, ...}; also "I am open"
    GET    /api/library               {items: [...]}
    GET    /library/<id>/<file>       the file an item is drawn from
    POST   /api/inspect/vox           body: the .vox   -> {models: [...]}
    POST   /api/preview/vox           body: the .vox   -> one model's mesh, unsaved
    POST   /api/import/vox            body: the .vox   -> the new item
    POST   /api/import/sprite         body: the .png   -> the new item
    GET    /api/inspect/item/<id>     the models in an added .vox
    GET    /api/preview/item/<id>     one of them, as a mesh
    POST   /api/change/<id>           the choices made again -> the item
    POST   /api/trash/<id>            take it off the shelf, into the trash
    GET    /api/trash                 {items: [...]}
    POST   /api/restore/<key>         out of the trash, back on the shelf
    DELETE /api/trash/<key>           delete one for good
    DELETE /api/trash                 empty the trash
    GET    /api/state                 the garden as last left
    PUT    /api/state
    POST   /api/open-folder           show a folder: ?which=files|program|trash|item
    GET    /api/update                where an update stands
    POST   /api/update/check          ask for the latest release
    POST   /api/update/apply          download it and restart into it
    POST   /api/log                   body: something the page tripped over
"""
import json
import logging
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from dev_kit import paths
from dev_kit.library import Refused
from dev_kit.version import VERSION

APP = "pixel-pomo-dev-kit"

log = logging.getLogger("dev_kit")

# A .vox is at most 256^3 voxels of four bytes each plus a palette — far under
# this; it is here so a wrong file cannot fill the memory.
MAX_BODY = 96 * 1024 * 1024

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".css": "text/css; charset=utf-8",
    ".symbols": "text/plain",
}


class KitServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows lets a second program bind a port that is already listening when
    # this is on, and then neither of them gets the requests.
    allow_reuse_address = False

    def __init__(self, library, web_dir, port=0, on_open_folder=None, updates=None):
        super().__init__(("127.0.0.1", port), _Handler)
        self.library = library
        self.web_dir = Path(web_dir)
        self.on_open_folder = on_open_folder or paths.open_in_file_manager
        self.updates = updates         # updater.Updates, or None: no UPDATE here
        self.lock = threading.Lock()   # one change to the library at a time
        self.last_seen = None          # when the page last said it was open
        self.page_complaints = 0       # how much the page has written to the log

    @property
    def port(self):
        return self.server_address[1]

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def serve_in_background(self):
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PixelPomoDevKit/" + VERSION

    def log_message(self, fmt, *args):  # the launcher keeps its own log
        pass

    # ---- answering ---------------------------------------------------------

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Never cached: the window keeps its profile between runs, and a
        # cached page would be last version's kit talking to this version's
        # launcher.
        self.send_header("Cache-Control", "no-store")
        if status >= 400:
            # a refusal may come before the request's body was read; what is
            # left of it must not be taken for the next request
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, value, status=200):
        self._send(status, json.dumps(value).encode("utf-8"), "application/json")

    def _refuse(self, message, status=400):
        self._json({"error": message}, status)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            raise Refused("That file is too large for the kit.")
        return self.rfile.read(length)

    def _ours(self):
        """Is this request from the kit's own page?

        The server is on this machine only, but any web page open in any
        browser on it can still aim a request at 127.0.0.1. The Host check
        stops a foreign name being pointed here; the Origin check stops
        another site's script adding or deleting the artist's files.
        """
        own = {f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}"}
        if self.headers.get("Host") not in own:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{host}" for host in own}

    # ---- the verbs ---------------------------------------------------------

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def _handle(self):
        try:
            if not self._ours():
                return self._refuse("Not the Dev Kit's own page.", 403)
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if path.startswith("/api/"):
                return self._api(path[5:], query)
            if self.command not in ("GET", "HEAD"):
                return self._refuse("Nothing to do that to.", 405)
            if path.startswith("/library/"):
                return self._library_file(path[9:])
            return self._static(path)
        except Refused as exc:
            self._refuse(str(exc))
        except (BrokenPipeError, ConnectionError):
            pass   # the window closed mid-answer
        except Exception as exc:  # noqa: BLE001 - the page must get an answer
            log.exception("%s %s", self.command, self.path)
            self._refuse(f"The Dev Kit tripped over that: {exc}", 500)

    @staticmethod
    def _int(query, key, default=None):
        if key not in query:
            return default
        try:
            return int(query[key])
        except ValueError:
            raise Refused(f"'{key}' has to be a whole number.") from None

    @staticmethod
    def _float(query, key):
        if key not in query:
            return None
        try:
            return float(query[key])
        except ValueError:
            raise Refused(f"'{key}' has to be a number.") from None

    def _api(self, name, query):
        server, library, verb = self.server, self.server.library, self.command
        if name == "hello" and verb == "GET":
            if server.last_seen is None:
                log.info("the page is open")
            server.last_seen = time.monotonic()
            return self._json({
                "app": APP, "version": VERSION, "dataDir": str(library.data),
                "programDir": str(paths.program_dir()),
                "build": ("installed" if paths.installed()
                          else "portable" if paths.frozen() else "source"),
                "trash": len(library.trashed())})
        if name == "library" and verb == "GET":
            return self._json({"items": library.items()})
        if name == "state" and verb == "GET":
            state = library.load_state()
            if state is None:
                return self._refuse("Nothing saved yet.", 404)
            return self._send(200, state, "application/json")
        if name == "state" and verb == "PUT":
            with server.lock:
                library.save_state(self._body())
            return self._json({"ok": True})

        # ---- adding ----
        if name == "inspect/vox" and verb == "POST":
            return self._json({"models": library.inspect_vox(
                self._body(), query.get("file", "model.vox"))})
        if name == "preview/vox" and verb == "POST":
            return self._json(library.preview_vox(
                self._body(), query.get("file", "model.vox"),
                self._int(query, "model", 0)))
        if name == "import/vox" and verb == "POST":
            body = self._body()
            started = time.monotonic()
            with server.lock:
                item = library.import_vox(
                    body, query.get("file", "model.vox"), query.get("name", ""),
                    category=query.get("category", "outer"),
                    model=self._int(query, "model", 0), turn=self._int(query, "turn", 0),
                    wide=self._float(query, "wide"), long=self._float(query, "long"))
            log.info("added %s from %s: %d boxes in %.1f s", item["id"], item["source"],
                     item["boxes"], time.monotonic() - started)
            return self._json(item)
        if name == "import/sprite" and verb == "POST":
            with server.lock:
                item = library.import_sprite(
                    self._body(), query.get("file", "sprite.png"), query.get("name", ""),
                    kind=query.get("kind", "sprite"),
                    category=query.get("category", "flowers"),
                    target=query.get("target"))
            log.info("added %s from %s", item["id"], item["source"])
            return self._json(item)

        # ---- what is already there ----
        if name.startswith("inspect/item/") and verb == "GET":
            return self._json({"models": library.inspect_item(name[13:])})
        if name.startswith("preview/item/") and verb == "GET":
            return self._json(library.preview_item(name[13:], self._int(query, "model", 0)))
        if name.startswith("change/") and verb == "POST":
            with server.lock:
                item = library.change(
                    name[7:], name=query.get("name"), category=query.get("category"),
                    kind=query.get("kind"), model=self._int(query, "model"),
                    turn=self._int(query, "turn"), size=query.get("size"),
                    wide=self._float(query, "wide"), long=self._float(query, "long"))
            log.info("changed %s", item["id"])
            return self._json(item)

        # ---- the trash ----
        if name == "trash" and verb == "GET":
            return self._json({"items": library.trashed()})
        if name == "trash" and verb == "DELETE":
            with server.lock:
                count = library.empty_trash()
            log.info("emptied the trash: %d", count)
            return self._json({"deleted": count})
        if name.startswith("trash/") and verb == "POST":
            with server.lock:
                item = library.trash(name[6:])
            log.info("to the trash: %s", item["trashKey"])
            return self._json(item)
        if name.startswith("trash/") and verb == "DELETE":
            with server.lock:
                library.delete(name[6:])
            log.info("deleted for good: %s", name[6:])
            return self._json({"ok": True})
        if name.startswith("restore/") and verb == "POST":
            with server.lock:
                item = library.restore(name[8:])
            log.info("out of the trash: %s", item["id"])
            return self._json(item)

        if name == "open-folder" and verb == "POST":
            which = query.get("which", "files")
            if which == "program":
                folder = paths.program_dir()
            elif which == "trash":
                library.bin.mkdir(parents=True, exist_ok=True)
                folder = library.bin
            elif which == "item":
                folder = library.folder_of(query.get("id", ""))
            else:
                folder = library.data
            if not server.on_open_folder(folder):
                raise Refused(f"The folder would not open. It is {folder}")
            return self._json({"ok": True, "folder": str(folder)})

        # ---- updates ----
        if name.startswith("update"):
            updates = server.updates
            if updates is None:
                return self._refuse("This Dev Kit cannot check for updates.", 404)
            if name == "update" and verb == "GET":
                return self._json(updates.status())
            if name == "update/check" and verb == "POST":
                return self._json(updates.check())
            if name == "update/apply" and verb == "POST":
                try:
                    return self._json(updates.apply())
                except ValueError as exc:
                    raise Refused(str(exc)) from None

        if name == "log" and verb == "POST":
            # the page's own errors, so a kit that misbehaved leaves a trace
            # where someone can read it; bounded, so a loop cannot fill a disk
            text = self._body()[:4000].decode("utf-8", "replace")
            if server.page_complaints < 200:
                server.page_complaints += 1
                log.warning("page: %s", text)
            return self._json({"ok": True})
        return self._refuse("The Dev Kit has no such thing.", 404)

    def _library_file(self, rest):
        item_id, _, name = rest.partition("/")
        path = self.server.library.file_path(item_id, name)
        if path is None:
            return self._refuse("That file is not in the library.", 404)
        self._send(200, path.read_bytes(),
                   TYPES.get(path.suffix.lower(), "application/octet-stream"))

    def _static(self, path):
        root = self.server.web_dir.resolve()
        target = (root / path.lstrip("/")).resolve()
        if target.is_dir():
            target = target / "index.html"
        # resolve() has already folded any `..`; what is left must be inside
        if root not in target.parents or not target.is_file():
            return self._refuse("No such page.", 404)
        kind = TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0]
        self._send(200, target.read_bytes(), kind or "application/octet-stream")
