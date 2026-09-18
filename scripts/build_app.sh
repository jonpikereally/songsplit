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

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O src/main.swift -o "$APP/Contents/MacOS/SongSplit"
cp src/Info.plist "$PLIST"
cp songsplit.py "$APP/Contents/Resources/songsplit.py"

PB=/usr/libexec/PlistBuddy
$PB -c "Set :CFBundleShortVersionString $VERSION" "$PLIST"
$PB -c "Set :CFBundleVersion $BUILD" "$PLIST"
$PB -c "Add :SongSplitBuildDate string '$DATE'" "$PLIST"
$PB -c "Add :SongSplitGitCommit string $COMMIT" "$PLIST"

codesign --force --sign - "$APP"
echo "Built $APP — version $VERSION, build $BUILD ($COMMIT), $DATE"
