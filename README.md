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
| `--dry-run` | | Analyze and report, write nothing |

## Mac app

`src/main.swift` is a native drag-and-drop front end that runs `songsplit.py` and shows progress.

```sh
scripts/build_app.sh        # builds build/SongSplit.app
```

The build is stamped with the version from `VERSION`, the commit count as the build number,
the short commit hash, and the build time.

### Cutting a release

```sh
scripts/release.sh 1.2.0 "What changed"
```

This bumps `VERSION`, commits, tags `v1.2.0`, builds and zips the app, pushes, and publishes a
GitHub release with the zip attached. That release is what the in-app update check looks for.

`songsplit_gui.py` is an older Tkinter front end with the same purpose.

## Library tools (`audit/`)

One-off scripts used to check and tidy a split library: re-verifying tags against the audio,
fixing mislabeled files, marking remixes, sorting by artist, and copying Serato metadata.
