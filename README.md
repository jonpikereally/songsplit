# SongSplit

Split one long WAV recording of back-to-back songs into individual, tagged files.

- Finds the silence gaps between songs
- Identifies each song by audio fingerprint (Shazam)
- Optionally cross-references a Spotify playlist CSV (e.g. from [Exportify](https://exportify.net)) for metadata
- Self-corrects two songs with no gap between them, and one song split in two by a quiet passage

## Install

Download `SongSplit-x.y.z.zip` from the [latest release](https://github.com/jonpikereally/songsplit/releases/latest),
unzip it, and drag `SongSplit.app` to Applications. The app isn't notarized, so the first time
you open it, right-click the app and choose **Open**.

The app checks GitHub for a newer release each time it starts, and you can also choose
**SongSplit ▸ Check for Updates…**. Installing an update replaces the app in place and relaunches it.
The window's top-right corner and the About panel show the version, build number, build time and commit.

## Requirements

- macOS, Python 3
- `ffmpeg` / `ffprobe` on your PATH: `brew install ffmpeg`
- Internet on first run: Shazam support installs `shazamio` into `~/.songsplit-venv`

## Tags

Each song is written as a WAV with two sets of tags: an ID3 v2.3 tag, which DJ software (djay,
Serato, rekordbox, Traktor) reads, and a RIFF INFO list for everything else. Both hold title,
artist, album, year and genre.

Songs split before 1.5.1 have only the INFO list, so DJ software shows them blank. To fix them,
choose **File ▸ Add DJ Tags to Existing Files…** in the app and pick the folder. Songs that
already have an ID3 tag, such as ones carrying Serato cue points, are left untouched. On the
command line: `./songsplit.py --retag FOLDER` (add `--dry-run` to preview).

## Error codes

Every error and warning carries a code like `SS-302`, listed with causes and fixes in
[ERRORS.md](ERRORS.md). Error dialogs in the app have a **Copy Error Details** button that copies
the code, message, app version and macOS version, ready to paste into a chat with an LLM. When
adding a new error, give it the next free code in its range and document it there; the Build
workflow fails otherwise (`scripts/check_error_codes.py`).

## Command line

```sh
./songsplit.py INPUT.wav [PLAYLIST.csv] [options]
```

| Option | Default | |
|---|---|---|
| `--out DIR` | `INPUT Split` | Output directory |
| `--noise` | `-40dB` | Silence threshold |
| `--min-silence` | `1.0` | Minimum silence length (s) |
| `--min-song` | `30` | Ignore segments shorter than this (s) |
| `--no-shazam` | | Match CSV by duration only |
| `--artist-in-name` | | Name files `Artist - Title.wav` instead of `Title.wav` |
| `--artist-folders` | | Put each song in a folder named after its artist |
| `--dry-run` | | Analyze and report, write nothing |

## Mac app

`src/main.swift` is a native drag-and-drop front end that runs `songsplit.py` and shows progress.

```sh
scripts/build_app.sh        # builds build/SongSplit.app
```

The build is stamped with the version from `VERSION`, the commit count as the build number,
the short commit hash, and the build time. The app icon comes from `src/icon/AppIcon.png`;
regenerate it with `python3 src/icon/make_icon.py` (needs Pillow) after editing that script.

### Cutting a release

Every push to `main` and every pull request builds the app on a macOS runner (`.github/workflows/build.yml`)
and attaches `SongSplit.zip` to the run, so any commit's build can be downloaded from the Actions tab.

To publish a release, set `VERSION` to the new number on `main` and push a matching tag:

```sh
git tag -a v1.2.0 -m "What changed" && git push origin v1.2.0
```

The `Release` workflow (`.github/workflows/release.yml`) builds and zips the app and publishes a GitHub
release with the zip attached. That release is what the in-app update check looks for. The tag's
annotation message becomes the top of the release notes.

No terminal needed: on GitHub open **Actions ▸ Release ▸ Run workflow** and press the green button. The
workflow tags `vX.Y.Z` from the `VERSION` file, builds the app, and publishes the release. Drafting a
release named `vX.Y.Z` on the Releases page works too; the workflow then attaches the zip to it.

`scripts/release.sh 1.2.0 "What changed"` does the same thing from a Mac with `gh` logged in.

`songsplit_gui.py` is an older Tkinter front end with the same purpose.

## Library tools (`audit/`)

One-off scripts used to check and tidy a split library: re-verifying tags against the audio,
fixing mislabeled files, marking remixes, sorting by artist, and copying Serato metadata.
