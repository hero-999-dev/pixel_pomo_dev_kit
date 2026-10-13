#!/usr/bin/env python3
"""Try the program as built, without its window.

    python smoke.py [path to the program]      (default: the one in dist/)

Starts the packaged kit on a folder of its own, then asks it what an artist's
first minute asks: is it the version the source says, does it serve its page,
and does a .vox go in as a model - which is the converter bundled from the
game doing its work inside the frozen program. On the release runners this is
the only time a Mac build is ever run before someone downloads it.

It does not open a window, so it says nothing about the window.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dev_kit.version import VERSION  # noqa: E402

PORT = 8799


def built_program():
    if sys.platform == "darwin":
        return HERE / "dist" / "PixelPomoDevKit.app" / "Contents" / "MacOS" / "PixelPomoDevKit"
    return HERE / "dist" / ("PixelPomoDevKit.exe" if os.name == "nt" else "PixelPomoDevKit")


def a_small_vox():
    """A 4 x 2 x 3 block, as MagicaVoxel would save it."""
    def chunk(name, content=b"", children=b""):
        return name + struct.pack("<ii", len(content), len(children)) + content + children
    cells = [(x, y, z) for x in range(4) for y in range(2) for z in range(3)]
    body = chunk(b"SIZE", struct.pack("<iii", 4, 2, 3))
    body += chunk(b"XYZI", struct.pack("<i", len(cells)) + b"".join(
        struct.pack("<BBBB", x, y, z, 3) for x, y, z in cells))
    body += chunk(b"RGBA", b"".join(struct.pack("<BBBB", k, 255 - k, 7, 255)
                                    for k in range(1, 256)) + b"\0\0\0\0")
    return b"VOX " + struct.pack("<i", 200) + chunk(b"MAIN", children=body)


def ask(path, body=None):
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=body,
                                     method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=60) as answer:
        return answer.read()


def main(argv):
    program = Path(argv[0]) if argv else built_program()
    if not program.is_file():
        print(f"there is no program at {program}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as data:
        env = {**os.environ, "DEVKIT_DATA": data, "DEVKIT_NO_WINDOW": "1",
               "DEVKIT_PORT": str(PORT)}
        kit = subprocess.Popen([str(program)], env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
        try:
            hello = None
            for _ in range(120):
                if kit.poll() is not None:
                    break
                try:
                    hello = json.loads(ask("/api/hello"))
                    break
                except (urllib.error.URLError, OSError, ValueError):
                    time.sleep(0.5)
            if hello is None:
                log = Path(data) / "devkit.log"
                print(f"the program never answered (exit code {kit.poll()})", file=sys.stderr)
                if log.is_file():
                    print(log.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
                return 1
            print("answers as", hello.get("app"), hello.get("version"))
            assert hello.get("version") == VERSION, f"expected {VERSION}"

            page = ask("/")
            assert b"flutter" in page.lower(), "the page is not the kit's"
            script = ask("/main.dart.js")
            print(f"serves its page ({len(script) / 1e6:.1f} MB of it)")
            assert len(script) > 500_000, "main.dart.js is not whole"

            item = json.loads(ask("/api/import/vox?file=block.vox&name=Block&turn=45&wide=2&long=1",
                                  a_small_vox()))
            item = item.get("item", item)
            print("converted a .vox:", json.dumps(item)[:300])
            mesh = json.loads(ask(f"/library/{item['id']}/mesh.json"))
            assert mesh.get("boxes"), "the mesh has no boxes"
            assert mesh.get("turn") == 45, f"turn is {mesh.get('turn')}, not 45"
            kept = Path(data) / "library" / item["id"] / "block.vox"
            assert kept.read_bytes() == a_small_vox(), "the picked file was not kept as it was"
            print(f"kept the file as {kept.name}; the mesh has {len(mesh['boxes'])} "
                  f"box(es) and is turned {mesh['turn']} degrees")
        finally:
            stop(kit)
    print("the built program works")
    return 0


def stop(kit):
    """End the kit and what it started. The one-file program is two
    processes - the unpacker and the kit it unpacked - and on Windows ending
    the first leaves the second running, on the port and holding its log."""
    kit.terminate()
    if os.name == "nt":
        # the second one is whoever is listening on the port (taskkill /T
        # would be shorter, and is refused on a machine without WMI access)
        listing = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                 text=True, check=False).stdout
        for line in listing.splitlines():
            words = line.split()
            if (len(words) == 5 and words[1] == f"127.0.0.1:{PORT}"
                    and words[3] == "LISTENING" and words[4].isdigit()):
                try:
                    os.kill(int(words[4]), 15)
                except OSError:
                    pass
    try:
        kit.wait(timeout=20)
    except subprocess.TimeoutExpired:
        kit.kill()
        kit.wait(timeout=20)
    time.sleep(1)   # Windows lets go of the files a moment after the process


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
