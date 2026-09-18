#!/bin/sh
# Cut a release: bump VERSION, tag vX.Y.Z, build SongSplit.app, zip it, and
# publish a GitHub release with the zip attached. The app's update checker
# looks for exactly this: a release whose tag is vX.Y.Z with a .zip asset.
#
# Usage: scripts/release.sh X.Y.Z ["what changed"]
# Needs: gh (logged in), a clean working tree.
set -e
cd "$(dirname "$0")/.."
V="$1"
case "$V" in
  "" | *[!0-9.]* ) echo "usage: $0 X.Y.Z [notes]   (e.g. 1.2.0)"; exit 1;;
esac
if [ -n "$(git status --porcelain)" ]; then
  echo "Commit or stash your changes first (git status is not clean)."; exit 1
fi
if git rev-parse "v$V" >/dev/null 2>&1; then
  echo "Tag v$V already exists."; exit 1
fi

echo "$V" > VERSION
git add VERSION
git diff --cached --quiet || git commit -m "Release $V"
git tag -a "v$V" -m "SongSplit $V"

scripts/build_app.sh build
ZIP="build/SongSplit-$V.zip"
rm -f "$ZIP"
ditto -c -k --keepParent build/SongSplit.app "$ZIP"

git push
git push origin "v$V"

NOTES="${2:-}"
NOTES="$NOTES

**Install:** unzip, drag SongSplit.app to Applications. The app isn't notarized, so the first time, right-click it and choose Open.
**Requires:** ffmpeg on your PATH (\`brew install ffmpeg\`). Song identification installs its own helper on first run.
**Build:** $(git rev-list --count HEAD) ($(git rev-parse --short HEAD)), $(date -u +'%Y-%m-%d %H:%M UTC')"

gh release create "v$V" "$ZIP" --title "SongSplit $V" --notes "$NOTES"
echo "Released v$V"
