#!/bin/sh
# Pixel Pomo Dev Kit - install on a Mac with no warning to click through.
#
#     curl -fsSL https://github.com/hero-999-dev/pixel_pomo_dev_kit/releases/latest/download/install-mac.sh | sh
#
# Why a line in Terminal and not a download to double-click: the kit is not
# signed with an Apple Developer ID, and macOS marks everything a BROWSER
# downloads as quarantined - which is what brings up "cannot be opened", the
# trip to System Settings and "Open Anyway" (the Art Kit's READ-ME-FIRST-MAC
# is two pages of exactly that). A file fetched by curl is not quarantined,
# so the same app opens like any other.
#
# The script only fetches and opens. The kit itself then asks where it should
# be installed (it suggests /Applications/PixelPomoDevKit) and keeps your
# files in that folder - not in Documents, Desktop or Downloads, the three
# places macOS asks permission for.
#
# NOT YET RUN ON A MAC. Written from Apple's documented behaviour.
set -eu

REPO="hero-999-dev/pixel_pomo_dev_kit"

case "$(uname -s)" in
  Darwin) ;;
  *) echo "This installs the Mac build. On Windows, download PixelPomoDevKit.exe." >&2; exit 1 ;;
esac

case "$(uname -m)" in
  arm64) CHIP="apple-silicon" ;;
  x86_64) CHIP="intel" ;;
  *) echo "Unknown Mac processor: $(uname -m)" >&2; exit 1 ;;
esac

ZIP="PixelPomoDevKit-macos-$CHIP.zip"
URL="https://github.com/$REPO/releases/latest/download/$ZIP"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/PixelPomoDevKit.XXXXXX")"
# the setup copies the kit to where you choose; what was fetched is thrown
# away once the setup window has closed
trap 'rm -rf "$WORK"' EXIT

echo "Pixel Pomo Dev Kit - fetching the $CHIP build..."
if ! curl -fL --progress-bar -o "$WORK/$ZIP" "$URL"; then
  echo "" >&2
  echo "The download failed: $URL" >&2
  echo "Check the connection and run the same line again." >&2
  exit 1
fi

# ditto, not unzip: it keeps the app bundle's links and executable bits
ditto -x -k "$WORK/$ZIP" "$WORK/kit"
APP="$WORK/kit/PixelPomoDevKit.app"
if [ ! -d "$APP" ]; then
  echo "The download did not contain PixelPomoDevKit.app." >&2
  exit 1
fi

# curl leaves no quarantine mark; this is for a Mac set up to add one anyway
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Opening the setup - choose where the Dev Kit should live."
# -W: wait until the setup window is closed, so the fetched copy is still
# there while the kit copies itself to the folder you chose
open -W "$APP"
echo "Done. The Dev Kit is in the folder you chose; open it from there."
