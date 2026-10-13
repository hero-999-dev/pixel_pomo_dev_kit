"""The kit's icon: Pixel Pomo's tomato with a voxel block beside it.

    python -m dev_kit.branding        (needs Pillow)

The Art Kit's icon is the tomato and a brush; this is the same tomato, cell
for cell, and where the brush stood, a box drawn the way the garden draws
one — flat sides and a brighter top. Written as a letter grid, like the game's
own sprites, and rendered from it into every file that needs an icon:

    assets/icon.png .ico .icns      the program (PixelPomoDevKit.spec)
    app/web/favicon.png, icons/     the window (it shows the page's own icon)
"""
from pathlib import Path

ICON = [
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    ".........GGGG...................",
    ".........GGGG...................",
    ".....GGGGGGGGGGGG...............",
    ".....GGGGGGGGGGGG...............",
    "...RRRRRRRRRRRRRRRRR............",
    "...RRRRRRRRRRRRRRRRR............",
    ".RRRRLLLLRRRRRRRRRRRR..TTTTTTTT.",
    ".RRRRLLLLRRRRRRRRRRRR..TTTTTTTT.",
    ".RRRRLLLLRRRRRRRRRRRR..TTTTTTTT.",
    ".RRRRLLLLRRRRRRRRRRRR..TTTTTTTT.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    ".RRRRRRRRRRRRRRRRRRRR..SSSSSSKK.",
    "...DDDDDDDDDDDDDDDDD...SSSSSSKK.",
    "...DDDDDDDDDDDDDDDDD...SSSSSSKK.",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
]

COLOURS = {
    "G": "3DE38A",  # leaf
    "R": "E53945",  # tomato
    "L": "FF6B6B",  # highlight
    "D": "9B1B23",  # underside
    "T": "9CCBFF",  # the box's top, lit by the sky
    "S": "58A6FF",  # its side - the blue of the kit's 3D label
    "K": "2F6FB8",  # the side turned away
}

TILE = (0x16, 0x16, 0x16, 255)   # the game's DARK background


def _rgba(h):
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def render(size):
    """The bare sprite at `size` px, every cell a crisp block."""
    from PIL import Image
    cells = len(ICON)
    img = Image.new("RGBA", (cells, cells))
    img.putdata([_rgba(COLOURS[ch]) if ch in COLOURS else (0, 0, 0, 0)
                 for line in ICON for ch in line])
    return img.resize((size, size), Image.NEAREST)


def tile(size, rounded=True):
    """The sprite on the game's dark tile — for the Dock and for the window,
    where a bare sprite floats oddly among solid icons."""
    from PIL import Image, ImageDraw
    cells = len(ICON)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    radius = round(size * 200 / 1024) if rounded else 0
    ImageDraw.Draw(out).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=TILE)
    per_cell = (size * 3 // 4) // cells
    if per_cell >= 1:
        sprite = render(per_cell * cells)
    else:   # 16 px cannot hold 32 cells whole; that one size alone is smoothed
        sprite = render(cells * 4).resize((size * 3 // 4,) * 2, Image.LANCZOS)
    off = (size - sprite.width) // 2
    out.alpha_composite(sprite, (off, off))
    return out


def write_icon_files(root):
    root = Path(root)
    assets, web = root / "assets", root / "app" / "web"
    assets.mkdir(parents=True, exist_ok=True)
    (web / "icons").mkdir(parents=True, exist_ok=True)
    written = []

    def save(img, path, **kw):
        img.save(path, **kw)
        written.append(path)

    save(render(512), assets / "icon.png")
    save(render(256), assets / "icon.ico",
         sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    save(tile(1024), assets / "icon.icns",
         append_images=[tile(n) for n in (16, 32, 64, 128, 256, 512)])
    save(tile(32, rounded=False), web / "favicon.png")
    for n in (192, 512):
        save(tile(n), web / "icons" / f"Icon-{n}.png")
        save(tile(n, rounded=False), web / "icons" / f"Icon-maskable-{n}.png")
    return written


if __name__ == "__main__":
    for p in write_icon_files(Path(__file__).resolve().parent.parent):
        print(p)
