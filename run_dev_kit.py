"""What PyInstaller freezes into PixelPomoDevKit.exe / .app."""
from dev_kit.app import main

if __name__ == "__main__":
    raise SystemExit(main())
