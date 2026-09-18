# SongSplit

Split one long WAV recording of back-to-back songs into individual, tagged files.

- Finds the silence gaps between songs
- Identifies each song by audio fingerprint (Shazam)
- Optionally cross-references a Spotify playlist CSV (e.g. from [Exportify](https://exportify.net)) for metadata
- Self-corrects two songs with no gap between them, and one song split in two by a quiet passage

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

`songsplit_gui.py` is an older Tkinter front end with the same purpose.

## Library tools (`audit/`)

One-off scripts used to check and tidy a split library: re-verifying tags against the audio,
fixing mislabeled files, marking remixes, sorting by artist, and copying Serato metadata.
