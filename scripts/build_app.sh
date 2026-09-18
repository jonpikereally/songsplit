#!/bin/sh
# Build SongSplit.app from src/ (native Cocoa front end + bundled songsplit.py).
# Usage: scripts/build_app.sh [OUTPUT_DIR]   (default: build/)
#
# Stamps the bundle with:
#   CFBundleShortVersionString  from the VERSION file        (e.g. 1.1.0)
#   CFBundleVersion             commit count = build number  (e.g. 14)
#   SongSplitBuildDate          UTC build time
#   SongSplitGitCommit          short commit hash, "+" if the tree had edits
set -e
cd "$(dirname "$0")/.."
OUT="${1:-build}"
APP="$OUT/SongSplit.app"
PLIST="$APP/Contents/Info.plist"

VERSION="$(tr -d '[:space:]' < VERSION)"
BUILD="$(git rev-list --count HEAD 2>/dev/null || echo 0)"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo local)"
if git rev-parse --git-dir >/dev/null 2>&1 && [ -n "$(git status --porcelain)" ]; then
  COMMIT="$COMMIT+"
fi
DATE="$(date -u +'%Y-%m-%d %H:%M UTC')"

# Minimum macOS the app runs on. Must match LSMinimumSystemVersion in
# src/Info.plist. Without an explicit target, swiftc uses the build machine's
# own macOS version, and the app refuses to launch on anything older.
MIN_MACOS="$(/usr/libexec/PlistBuddy -c "Print :LSMinimumSystemVersion" src/Info.plist)"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
# Universal binary: one slice per architecture, joined with lipo.
swiftc -O -target "arm64-apple-macos$MIN_MACOS"  src/main.swift -o "$OUT/SongSplit-arm64"
swiftc -O -target "x86_64-apple-macos$MIN_MACOS" src/main.swift -o "$OUT/SongSplit-x86_64"
lipo -create "$OUT/SongSplit-arm64" "$OUT/SongSplit-x86_64" -output "$APP/Contents/MacOS/SongSplit"
rm -f "$OUT/SongSplit-arm64" "$OUT/SongSplit-x86_64"
cp src/Info.plist "$PLIST"
cp songsplit.py "$APP/Contents/Resources/songsplit.py"

# App icon: src/icon/AppIcon.png (1024x1024, from src/icon/make_icon.py) -> AppIcon.icns
ICONSET="$OUT/AppIcon.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" src/icon/AppIcon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z "$((s*2))" "$((s*2))" src/icon/AppIcon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

PB=/usr/libexec/PlistBuddy
$PB -c "Set :CFBundleShortVersionString $VERSION" "$PLIST"
$PB -c "Set :CFBundleVersion $BUILD" "$PLIST"
$PB -c "Add :SongSplitBuildDate string '$DATE'" "$PLIST"
$PB -c "Add :SongSplitGitCommit string $COMMIT" "$PLIST"

codesign --force --sign - "$APP"
echo "Built $APP — version $VERSION, build $BUILD ($COMMIT), $DATE, macOS $MIN_MACOS+ ($(lipo -archs "$APP/Contents/MacOS/SongSplit"))"
