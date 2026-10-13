# -*- mode: python ; coding: utf-8 -*-
# The Dev Kit as one program: the launcher and its window (pywebview), the page
# shown in it, and the game's voxel converter. Build it with `python build.py`,
# which makes the page first.
import os
import sys

HERE = os.path.dirname(os.path.abspath(SPEC))

# The page: app/build/web, as `flutter build web` left it.
_WEB = os.path.join(HERE, 'app', 'build', 'web')
if not os.path.exists(os.path.join(_WEB, 'main.dart.js')):
    raise SystemExit(f'the page is not built ({_WEB}) - run `python build.py`')

# The game's converters, resolved RELATIVE to this spec (DevKit/ -> Pixel
# Pomo/ -> App/), bundled so the packaged kit works with no game checkout.
_TOOLS = os.path.normpath(os.path.join(HERE, os.pardir, 'App', 'flutter', 'tools'))
_CONVERTERS = [os.path.join(_TOOLS, name) for name in ('vox_to_boxes.py', 'obj_to_boxes.py')]
_missing = [p for p in _CONVERTERS if not os.path.exists(p)]
if _missing:
    raise SystemExit(f'the game\'s converters are missing: {_missing} - is the App '
                     f'folder still a sibling of DevKit?')


def _page_files():
    """Every file of the page the kit can actually load, as PyInstaller datas.

    The Flutter build carries three renderers; this page is compiled for one
    (canvaskit). The other two, the debug symbol tables and an experimental
    text engine are two thirds of the folder and are never requested.
    """
    out = []
    for folder, _, names in os.walk(_WEB):
        rel = os.path.relpath(folder, _WEB).replace(os.sep, '/')
        if rel.startswith('canvaskit/experimental_webparagraph'):
            continue
        for name in names:
            if name.endswith('.symbols') or name == '.last_build_id':
                continue
            if rel == 'canvaskit' and name.startswith(('skwasm', 'wimp')):
                continue
            out.append((os.path.join(folder, name),
                        os.path.normpath(os.path.join('web', rel))))
    return out


sys.path.insert(0, HERE)
from dev_kit.version import VERSION as _VERSION  # noqa: E402

_ICO = os.path.join(HERE, 'assets', 'icon.ico')
_ICNS = os.path.join(HERE, 'assets', 'icon.icns')
_PNG = os.path.join(HERE, 'assets', 'icon.png')
_NAME = 'PixelPomoDevKit'

a = Analysis(
    ['run_dev_kit.py'],
    pathex=['.'],
    binaries=[],
    # icon.ico: handed to the window as its title-bar icon (window.icon_path);
    # icon.png: the logo on the setup window (installer.setup_page)
    datas=_page_files() + [(p, '.') for p in _CONVERTERS] + [(_ICO, '.'), (_PNG, '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # the launcher is a web server, a file store and a web view; these are
    # pulled in by habit and never used
    excludes=['tkinter', 'PIL', 'numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICNS if sys.platform == 'darwin' else _ICO,
)

# macOS wants a .app bundle, not a bare executable (see the Art Kit's spec).
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name=f'{_NAME}.app',
        icon=_ICNS,
        bundle_identifier='com.pixelpomo.devkit',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': _VERSION,
            'CFBundleVersion': _VERSION,
            # No NSDocumentsFolderUsageDescription, on purpose: the kit keeps
            # the artist's files in its own install folder and never opens
            # Documents, Desktop or Downloads, so macOS has nothing to ask.
        },
    )
