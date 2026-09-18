#!/bin/sh
# Build SongSplit.app from src/ (native Cocoa front end + bundled songsplit.py).
# Usage: scripts/build_app.sh [OUTPUT_DIR]   (default: build/)
set -e
cd "$(dirname "$0")/.."
OUT="${1:-build}"
APP="$OUT/SongSplit.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O src/main.swift -o "$APP/Contents/MacOS/SongSplit"
cp src/Info.plist "$APP/Contents/Info.plist"
cp songsplit.py "$APP/Contents/Resources/songsplit.py"
codesign --force --sign - "$APP"
echo "Built $APP"
