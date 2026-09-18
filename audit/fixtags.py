#!/usr/bin/env python3
"""
Re-identify the files in a folder and rewrite their tags to match the audio.

For each file: fingerprint at several points, require agreement, pull album /
date / genre from the iTunes Search API, then rewrite tags losslessly and
rename to "<Title>.wav".  Anything whose samples disagree is left untouched
and reported, so a bad split never gets a confident new label.

Usage:  fixtags.py "/path/to/folder" [--apply]
Without --apply it only reports what it would do.
"""
import asyncio, json, os, re, subprocess, sys, time, unicodedata
import urllib.parse, urllib.request

os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
from shazamio import Shazam

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
SAMPLES = (0.15, 0.45, 0.75)
DELAY = 2.5

# Identifications confirmed by ear, where Shazam's catalogue data is wrong.
# Keyed by current filename.
OVERRIDES = {
    # Shazam's catalogue entry for this one was junk; identified by ear.
    "Fat Bottomed Girls - Remastered.wav": ("I Don't Know Why", "NOTD & Astrid S"),
    # Shazam reports the explicit title; the drive uses the clean title.
    "Break My Heart.wav": ("Forget You", "CeeLo Green"),
}


def nrm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|feat\.?.*|featuring.*", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def safe(s):
    return re.sub(r'[/\\:*?"<>|]', "", s or "").strip()


def artist_tokens(s):
    out = set()
    for p in re.split(r"[;,&/]| feat\.? | featuring | with | x ", (s or "").lower()):
        p = unicodedata.normalize("NFKD", p).encode("ascii", "ignore").decode()
        p = re.sub(r"[^a-z0-9]", "", p)
        if p:
            out.add(p)
    return out


def itunes(artist, title):
    """Album/date/genre for this song. The ARTIST must match too -- matching
    on title alone returns another act's song of the same name (Norah Jones's
    'Don't Know Why', Lily Allen's album for CeeLo's 'F**k You')."""
    want = artist_tokens(artist)
    q = urllib.parse.urlencode({"term": f"{artist} {title}", "entity": "song", "limit": "10"})
    try:
        time.sleep(0.4)
        with urllib.request.urlopen(f"https://itunes.apple.com/search?{q}", timeout=10) as r:
            for res in json.load(r).get("results", []):
                if nrm(res.get("trackName")) != nrm(title):
                    continue
                if not (artist_tokens(res.get("artistName")) & want):
                    continue          # same title, wrong act -- skip it
                return {"album": res.get("collectionName"),
                        "date": (res.get("releaseDate") or "")[:10],
                        "genre": res.get("primaryGenreName")}
    except Exception:
        pass
    return {}


async def main():
    folder = sys.argv[1]
    apply = "--apply" in sys.argv
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".wav"))
    sh = Shazam()
    plan, skipped = [], []

    for name in files:
        path = os.path.join(folder, name)
        dur = float(subprocess.run([FFPROBE, "-v", "quiet", "-show_entries",
                                    "format=duration", "-of", "csv=p=0", path],
                                   capture_output=True, text=True).stdout or 0)
        if name in OVERRIDES:
            title, artist = OVERRIDES[name]
            plan.append((name, title, artist, itunes(artist, title), dur))
            continue
        hits = []
        for fr in SAMPLES:
            clip = "/tmp/fixtag.ogg"
            subprocess.run([FFMPEG, "-y", "-v", "quiet", "-ss", str(max(2, dur * fr)),
                            "-t", "12", "-i", path, "-ac", "1", "-ar", "44100", clip],
                           capture_output=True)
            await asyncio.sleep(DELAY)
            try:
                t = (await asyncio.wait_for(sh.recognize(clip), 30)).get("track", {}) or {}
            except Exception:
                t = {}
            if t:
                hits.append((t.get("title"), t.get("subtitle")))
        ids = {nrm(h[0]) for h in hits}
        if not hits:
            skipped.append((name, "no identification"))
            continue
        if len(ids) > 1:
            skipped.append((name, "samples disagree: " + " / ".join(f"{a} - {t}" for t, a in hits)))
            continue
        title, artist = hits[0]
        extra = itunes(artist, title)
        plan.append((name, title, artist, extra, dur))

    print(f"{len(plan)} to retag, {len(skipped)} skipped\n")
    for name, title, artist, extra, dur in plan:
        m, s = divmod(int(dur), 60)
        print(f"  {name}  [{m}:{s:02d}]")
        print(f"      -> {artist} - {title}")
        print(f"         album={extra.get('album')}  date={extra.get('date')}  genre={extra.get('genre')}")
        if apply:
            dest = os.path.join(folder, safe(title) + ".wav")
            n = 2
            while os.path.exists(dest) and os.path.abspath(dest) != os.path.abspath(os.path.join(folder, name)):
                dest = os.path.join(folder, f"{safe(title)} ({n}).wav")
                n += 1
            tmp = os.path.join(folder, ".tmp_" + name)
            cmd = [FFMPEG, "-y", "-v", "error", "-i", os.path.join(folder, name),
                   "-c", "copy", "-write_id3v2", "1",
                   "-metadata", f"title={title}", "-metadata", f"artist={artist}",
                   "-metadata", f"album={extra.get('album') or ''}",
                   "-metadata", f"date={extra.get('date') or ''}",
                   "-metadata", f"genre={extra.get('genre') or ''}", tmp]
            subprocess.run(cmd, check=True)
            os.replace(tmp, os.path.join(folder, name))
            os.rename(os.path.join(folder, name), dest)
            print(f"         WROTE {os.path.basename(dest)}")
    if skipped:
        print("\nLEFT ALONE:")
        for name, why in skipped:
            print(f"  {name}: {why}")

asyncio.run(main())
