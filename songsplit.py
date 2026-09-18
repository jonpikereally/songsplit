#!/usr/bin/env python3
"""
songsplit — split a concatenated WAV of songs into individual tagged files.

Detects silence gaps between songs, identifies each song by audio
fingerprint (Shazam), optionally cross-references a Spotify/Exportify
playlist CSV for metadata, and writes one tagged file per song.

It self-corrects two common problems:
  * two songs with no silence between them (split using the playlist's
    expected track length, cutting at the quietest nearby moment)
  * one song broken in two by a quiet passage (merged back together)

Usage:
    songsplit INPUT.wav [PLAYLIST.csv] [options]

Files can be given in any order; the .csv is recognized automatically.

Options:
    --out DIR            Output directory (default: "INPUT Split" next to input)
    --noise -40dB        Silence threshold (default -40dB)
    --min-silence 1.0    Minimum silence length in seconds (default 1.0)
    --min-song 30        Ignore segments shorter than this (default 30s)
    --no-shazam          Skip fingerprinting; match CSV by duration only
    --dry-run            Analyze and report, but write no files

Requires: ffmpeg + ffprobe on PATH (brew install ffmpeg).
Shazam identification installs the 'shazamio' package into a private
virtualenv at ~/.songsplit-venv on first run (needs internet).
"""

import argparse
import array
import contextlib
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request

VENV = os.path.expanduser("~/.songsplit-venv")


# ---------------------------------------------------------------- helpers

def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def find_tool(name):
    path = shutil.which(name) or (
        os.path.exists(f"/opt/homebrew/bin/{name}") and f"/opt/homebrew/bin/{name}"
    )
    if not path:
        die(f"{name} not found. Install it with: brew install ffmpeg")
    return path


def ensure_shazamio():
    """Re-exec inside a private venv that has shazamio installed."""
    try:
        import shazamio  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("SONGSPLIT_BOOTSTRAPPED"):
        die("failed to install shazamio in the private venv")
    py = os.path.join(VENV, "bin", "python3")
    if not os.path.exists(py):
        print("First run: creating private venv and installing shazamio ...")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)
        subprocess.run([py, "-m", "pip", "install", "-q", "shazamio"], check=True)
    env = dict(os.environ, SONGSPLIT_BOOTSTRAPPED="1")
    os.execve(py, [py] + sys.argv, env)


@contextlib.contextmanager
def quiet_stderr():
    """Hide the noisy 'skipping junk' chatter from shazamio's decoder."""
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def norm(s):
    """Normalize a title/artist for fuzzy comparison."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|feat\..*|with .*| - .*", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


# ---------------------------------------------------------------- analysis

def probe_duration(ffprobe, path):
    r = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def detect_segments(ffmpeg, path, total, noise, min_silence, min_song,
                    lead_pad=0.3, tail_pad=1.5):
    """Return (start, end) spans, one per song, with the silence between
    songs trimmed away: each span begins lead_pad before its music starts
    and ends tail_pad after its fade-out drops below the threshold."""
    r = subprocess.run(
        [ffmpeg, "-i", path, "-af",
         f"silencedetect=noise={noise}:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(m) for m in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]

    # Where does the music begin?  Skip any silence at the very start.
    first = 0.0
    if starts and starts[0] < 0.1 and ends:
        first = max(0.0, ends[0] - lead_pad)

    # Trailing silence at EOF gives a silence_start with no silence_end.
    last = total
    if len(starts) > len(ends):
        last = min(total, starts[-1] + tail_pad)

    # Between-song silences (only those following a song-length chunk).
    gaps = []
    cur = 0.0
    for s, e in zip(starts, ends):
        if s - cur >= min_song:
            gaps.append((s, e))
        cur = e

    segments = []
    a = first
    for s, e in gaps:
        b = min(s + tail_pad, total)
        if b - a >= min_song:
            segments.append((a, b))
        a = max(e - lead_pad, 0.0)
    if last - a >= min_song:
        segments.append((a, last))
    return segments


def quietest_point(ffmpeg, path, center, radius=8.0):
    """Return the time of the quietest 0.5s window within center +/- radius,
    for cutting between songs that have no real silence gap."""
    start = max(0.0, center - radius)
    r = subprocess.run(
        [ffmpeg, "-v", "quiet", "-ss", f"{start:.3f}", "-t", f"{2 * radius:.3f}",
         "-i", path, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
        capture_output=True, check=True)
    samples = array.array("h")
    samples.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    if len(samples) < 8000:
        return center
    win = 4000  # 0.5s at 8kHz
    best_i, best_e = 0, float("inf")
    # slide in 50ms steps using a running sum of squares
    sq = [s * s for s in samples]
    cum = [0]
    for v in sq:
        cum.append(cum[-1] + v)
    for i in range(0, len(samples) - win, 400):
        e = cum[i + win] - cum[i]
        if e < best_e:
            best_i, best_e = i, e
    return start + (best_i + win / 2) / 8000.0


def load_playlist(path):
    tracks = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not row.get("Track Name"):
                continue
            tracks.append({
                "title": row.get("Track Name", ""),
                "album": row.get("Album Name", ""),
                "artist": row.get("Artist Name(s)", "").replace(";", ", "),
                "date": row.get("Release Date", ""),
                "genre": (row.get("Genres", "") or "").split(",")[0],
                "dur": int(row["Duration (ms)"]) / 1000.0 if row.get("Duration (ms)") else None,
            })
    return tracks


class Identifier:
    """Shazam lookups, one event loop reused across calls."""

    def __init__(self, ffmpeg, path):
        import asyncio
        from shazamio import Shazam
        self.ffmpeg = ffmpeg
        self.path = path
        self.loop = asyncio.new_event_loop()
        self.shazam = Shazam()

    def identify(self, t):
        """Identify the song playing at time t. Returns dict or None."""
        clip = os.path.join(tempfile.gettempdir(), f"songsplit_clip_{os.getpid()}.ogg")
        subprocess.run(
            [self.ffmpeg, "-y", "-v", "quiet", "-ss", f"{t:.2f}", "-t", "12",
             "-i", self.path, "-ac", "1", "-ar", "44100", clip], check=True)
        out = None
        for attempt in range(3):        # transient failures are usually rate limits
            try:
                with quiet_stderr():
                    out = self.loop.run_until_complete(self.shazam.recognize(clip))
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    (Shazam lookup at {t:.0f}s failed after 3 tries: {e})")
                else:
                    time.sleep(4 * (attempt + 1))    # back off, then retry
        with contextlib.suppress(OSError):
            os.unlink(clip)
        if out is None:
            return None
        tr = out.get("track")
        if not tr:
            return None
        meta = {m.get("title"): m.get("text")
                for s in tr.get("sections", []) for m in s.get("metadata", [])}
        return {
            "title": tr.get("title"),
            "artist": tr.get("subtitle"),
            "album": meta.get("Album"),
            "date": meta.get("Released"),
            "genre": (tr.get("genres") or {}).get("primary", ""),
        }


_itunes_cache = {}


def itunes_enrich(ident):
    """Look up expected duration (and fill missing album/genre/date) for a
    Shazam-identified song via the free iTunes Search API."""
    key = (norm(ident.get("title")), norm(ident.get("artist")))
    if key in _itunes_cache:
        return _itunes_cache[key]
    q = urllib.parse.urlencode({
        "term": f"{ident.get('artist', '')} {ident.get('title', '')}",
        "entity": "song", "limit": "5"})
    result = None
    try:
        time.sleep(0.4)  # stay well under iTunes' rate limit
        with urllib.request.urlopen(
                f"https://itunes.apple.com/search?{q}", timeout=10) as r:
            data = json.load(r)
        for res in data.get("results", []):
            rt, ra = norm(res.get("trackName")), norm(res.get("artistName"))
            if rt == key[0] and (ra in key[1] or key[1] in ra):
                result = {
                    "dur": (res.get("trackTimeMillis") or 0) / 1000.0 or None,
                    "album": res.get("collectionName"),
                    "genre": res.get("primaryGenreName"),
                    "date": (res.get("releaseDate") or "")[:10],
                }
                break
    except Exception:
        pass  # offline or API hiccup: just skip enrichment
    _itunes_cache[key] = result
    return result


def match_csv(tracks, seg_len=None, ident=None):
    """Find the best playlist row for a Shazam result (by name) or a
    segment length (by duration)."""
    if ident:
        nt, na = norm(ident.get("title")), norm(ident.get("artist"))
        for t in tracks:
            if norm(t["title"]) == nt and (na in norm(t["artist"]) or norm(t["artist"]) in na):
                return t
        for t in tracks:  # title-only fallback
            if norm(t["title"]) == nt:
                return t
    if seg_len is not None:
        # Duration matching only. Accept it ONLY when exactly one playlist
        # track fits the length -- with a big CSV several tracks land within
        # a few seconds of each other, and guessing between them produces
        # confidently mislabeled files.
        near = [t for t in tracks if t["dur"] and abs(t["dur"] - seg_len) <= 3.0]
        if len(near) == 1:
            return near[0]
    return None


def same_song(x, y):
    """True if two analyzed segments look like the same track."""
    for key in ("row", "ident"):
        a, b = x.get(key), y.get(key)
        if a and b and norm(a["title"]) == norm(b["title"]) \
                and norm(a["artist"]) == norm(b["artist"]):
            return True
    return False


# ---------------------------------------------------------------- output

def safe_name(s):
    return re.sub(r'[/\\:*?"<>|]', "", s).strip()


def track_path(meta, num, out_dir, artist_in_name=False, artist_folders=False):
    """Where a track goes: 'Title.wav', or 'Artist - Title.wav' with
    --artist-in-name, inside 'out_dir/Artist/' with --artist-folders.
    Returns the path relative to out_dir; picks a '(2)' suffix if it exists."""
    artist = meta.get("artist") or "Unknown Artist"
    title = meta.get("title") or f"Track {num}"
    stem = f"{safe_name(artist)} - {safe_name(title)}" if artist_in_name else safe_name(title)
    folder = safe_name(artist) if artist_folders else ""
    rel = os.path.join(folder, f"{stem}.wav")
    n = 2
    while os.path.exists(os.path.join(out_dir, rel)):   # avoid clobbering a duplicate title
        rel = os.path.join(folder, f"{stem} ({n}).wav")
        n += 1
    return rel


def write_track(ffmpeg, src, a, b, is_last, meta, num, out_dir,
                artist_in_name=False, artist_folders=False):
    artist = meta.get("artist") or "Unknown Artist"
    title = meta.get("title") or f"Track {num}"
    name = track_path(meta, num, out_dir, artist_in_name, artist_folders)
    dest = os.path.join(out_dir, name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cmd = [ffmpeg, "-y", "-v", "error", "-i", src, "-ss", f"{a:.3f}"]
    if not is_last:
        cmd += ["-to", f"{b:.3f}"]
    cmd += ["-c", "copy", "-write_id3v2", "1",
            "-metadata", f"title={title}", "-metadata", f"artist={artist}"]
    for key in ("album", "date", "genre"):
        if meta.get(key):
            cmd += ["-metadata", f"{key}={meta[key]}"]
    cmd.append(dest)
    subprocess.run(cmd, check=True)
    return name


# ---------------------------------------------------------------- main

def analyze_segment(a, b, ident_fn, tracks):
    ident = ident_fn(a) if ident_fn else None
    row = match_csv(tracks, b - a, ident)
    if ident and not row:
        # No playlist to consult: get expected duration (and fill metadata
        # gaps) from the iTunes Search API instead.
        extra = itunes_enrich(ident)
        if extra:
            ident["dur"] = extra["dur"]
            for k in ("album", "genre", "date"):
                ident[k] = ident.get(k) or extra[k]
    return {"a": a, "b": b, "ident": ident, "row": row}


def expected_dur(item):
    return (item["row"] or {}).get("dur") or (item["ident"] or {}).get("dur")


def main():
    ap = argparse.ArgumentParser(description="Split a concatenated WAV into tagged songs.")
    ap.add_argument("files", nargs="+",
                    help="audio file to split, and optionally a playlist .csv (any order)")
    ap.add_argument("--csv")
    ap.add_argument("--out")
    ap.add_argument("--noise", default="-40dB")
    ap.add_argument("--min-silence", type=float, default=1.0)
    ap.add_argument("--min-song", type=float, default=30.0)
    ap.add_argument("--lead-pad", type=float, default=0.3,
                    help="seconds of silence kept before each song (default 0.3)")
    ap.add_argument("--tail-pad", type=float, default=1.5,
                    help="seconds of silence kept after each fade-out (default 1.5)")
    ap.add_argument("--no-shazam", action="store_true")
    ap.add_argument("--artist-in-name", action="store_true",
                    help="name files 'Artist - Title.wav' instead of 'Title.wav'")
    ap.add_argument("--artist-folders", action="store_true",
                    help="put each song in a folder named after its artist")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Sort positional files by type: .csv -> playlist, anything else -> audio.
    args.input = None
    csvs = [args.csv] if args.csv else []
    for f in args.files:
        if f.lower().endswith(".csv"):
            csvs.append(f)
        elif args.input is None:
            args.input = f
        else:
            die(f"more than one audio file given: {args.input!r} and {f!r}")
    if args.input is None:
        die("no audio file given (only a .csv?)")
    if not os.path.exists(args.input):
        die(f"input not found: {args.input}")
    for c in csvs:
        if not os.path.exists(c):
            die(f"playlist csv not found: {c}")

    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if not args.no_shazam:
        ensure_shazamio()

    total = probe_duration(ffprobe, args.input)
    print(f"Input: {args.input}  ({total:.1f}s)")
    print(f"Detecting silence (threshold {args.noise}, min {args.min_silence}s) ...")
    segments = detect_segments(ffmpeg, args.input, total,
                               args.noise, args.min_silence, args.min_song,
                               args.lead_pad, args.tail_pad)
    if not segments:
        die("no song segments found — try a higher --noise like -35dB")
    print(f"Found {len(segments)} raw segments.")

    tracks = []
    for c in csvs:
        tracks.extend(load_playlist(c))
    if csvs:
        print(f"Loaded {len(tracks)} playlist tracks from {len(csvs)} CSV file(s).")

    ident_fn = None
    if not args.no_shazam:
        print("Identifying songs via Shazam ...")
        identifier = Identifier(ffmpeg, args.input)
        # Sample near the START of each segment (so if two songs are merged
        # in one segment, we identify the first one).
        ident_fn = lambda a: identifier.identify(a + 25)

    items = [analyze_segment(a, b, ident_fn, tracks) for a, b in segments]

    # -- repair pass 1: merge a song that silence-detection broke in two
    merged = []
    for it in items:
        if merged and same_song(merged[-1], it):
            exp = expected_dur(merged[-1])
            if exp is None or (it["b"] - merged[-1]["a"]) <= exp + 20:
                print(f"  merged split-up song at {merged[-1]['a']:.0f}s "
                      f"({(merged[-1].get('row') or merged[-1].get('ident'))['title']})")
                merged[-1]["b"] = it["b"]
                continue
        merged.append(it)

    # -- repair pass 2: split segments that contain two or more songs
    final = []
    for it in merged:
        while True:
            exp = expected_dur(it)
            if not exp or (it["b"] - it["a"]) <= exp + 45:
                break
            cut = quietest_point(ffmpeg, args.input, it["a"] + exp + 1.5)
            first = dict(it, b=cut)
            title = (it["row"] or it["ident"] or {}).get("title", "?")
            print(f"  no silence gap after '{title}' — "
                  f"splitting at quietest point {cut:.1f}s")
            final.append(first)
            it = analyze_segment(cut, it["b"], ident_fn, tracks)
        final.append(it)

    out_dir = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.input)),
        os.path.splitext(os.path.basename(args.input))[0] + " Split")
    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    print()
    for i, it in enumerate(final, 1):
        a, b, ident, row = it["a"], it["b"], it["ident"], it["row"]
        seg_len = b - a
        meta = dict(row) if row else (dict(ident) if ident else {})
        if row and ident:            # playlist wins for album/date
            meta["title"] = row["title"]
            meta["artist"] = row["artist"]

        src_note = ("playlist+shazam" if row and ident else
                    "playlist" if row else
                    "shazam" if ident else "unidentified")
        exp = meta.get("dur")
        short = exp and seg_len < exp - 15
        label = f"{meta.get('artist', '?')} - {meta.get('title', '?')}"
        print(f"  {i:02d}. [{a:8.2f} - {b:8.2f}] {seg_len:6.1f}s  {label}  ({src_note})"
              + ("  ** shorter than expected — possibly cut off" if short else ""))

        if not args.dry_run:
            write_track(ffmpeg, args.input, a, b, i == len(final), meta, i, out_dir,
                        args.artist_in_name, args.artist_folders)

    if not args.dry_run:
        print(f"\nDone. {len(final)} files written to: {out_dir}")


if __name__ == "__main__":
    main()
