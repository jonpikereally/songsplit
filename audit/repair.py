#!/usr/bin/env python3
"""Split the two genuine two-song files and retag the mislabeled ones."""
import array, json, os, re, subprocess, sys, time
import urllib.parse, urllib.request

FFMPEG = "/opt/homebrew/bin/ffmpeg"
ROOT = "/Volumes/Jons 16TB HDD/hi res"
APPLY = "--apply" in sys.argv


def safe(s):
    return re.sub(r'[/\\:*?"<>|]', "", s or "").strip()


def quietest(path, lo, hi):
    """Time of the quietest 0.4s window in [lo, hi] -- the natural cut point."""
    r = subprocess.run([FFMPEG, "-v", "quiet", "-ss", f"{lo:.2f}", "-t", f"{hi - lo:.2f}",
                        "-i", path, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       capture_output=True)
    s = array.array("h")
    s.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    win = 3200
    if len(s) < win:
        return (lo + hi) / 2
    cum = [0]
    for v in s:
        cum.append(cum[-1] + v * v)
    best_i, best = 0, float("inf")
    for i in range(0, len(s) - win, 200):
        e = cum[i + win] - cum[i]
        if e < best:
            best_i, best = i, e
    return lo + (best_i + win / 2) / 8000.0


def itunes(artist, title):
    def toks(s):
        return {re.sub(r"[^a-z0-9]", "", p) for p in re.split(r"[;,&/]", (s or "").lower())} - {""}
    want = toks(artist)
    q = urllib.parse.urlencode({"term": f"{artist} {title}", "entity": "song", "limit": "10"})
    try:
        time.sleep(0.4)
        with urllib.request.urlopen(f"https://itunes.apple.com/search?{q}", timeout=10) as r:
            for res in json.load(r).get("results", []):
                a, b = res.get("trackName", "").lower(), title.lower()
                if a[:12] != b[:12]:
                    continue
                if not (toks(res.get("artistName")) & want):
                    continue
                return {"album": res.get("collectionName"),
                        "date": (res.get("releaseDate") or "")[:10],
                        "genre": res.get("primaryGenreName")}
    except Exception:
        pass
    return {}


# iTunes only offers compilations for some tracks; pin the canonical album.
# Anything not listed here is left blank rather than guessed.
META_OVERRIDE = {
    "I Write Sins Not Tragedies": {"album": "A Fever You Can't Sweat Out",
                                   "date": "2005-09-27", "genre": "Alternative"},
    "Say It (Illenium Remix)": {},      # not in the catalogue; leave album blank
}


def write(src, dest, title, artist, start=None, end=None):
    meta = META_OVERRIDE.get(title)
    if meta is None:
        meta = itunes(artist, title)
    cmd = [FFMPEG, "-y", "-v", "error", "-i", src]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-c", "copy", "-write_id3v2", "1",
            "-metadata", f"title={title}", "-metadata", f"artist={artist}",
            "-metadata", f"album={meta.get('album') or ''}",
            "-metadata", f"date={meta.get('date') or ''}",
            "-metadata", f"genre={meta.get('genre') or ''}", dest]
    print(f"    -> {os.path.basename(dest)}   [{artist} - {title}]")
    print(f"       album={meta.get('album')} date={meta.get('date')} genre={meta.get('genre')}")
    if APPLY:
        subprocess.run(cmd, check=True)


def uniq(folder, title):
    dest = os.path.join(folder, safe(title) + ".wav")
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{safe(title)} ({n}).wav")
        n += 1
    return dest


# ---- 1. Track 92: two complete Panic! At The Disco songs ------------------
src = os.path.join(ROOT, "N O P Q R S #02 Split/Track 92.wav")
folder = os.path.dirname(src)
cut = quietest(src, 198, 212)
print(f"Track 92 -> split at {cut:.2f}s")
write(src, uniq(folder, "But It's Better If You Do"), "But It's Better If You Do",
      "Panic! At The Disco", end=cut)
write(src, uniq(folder, "I Write Sins Not Tragedies"), "I Write Sins Not Tragedies",
      "Panic! At The Disco", start=cut)

# ---- 2. Back On 74 (2): 35s tail of one song + a full second song ---------
src = os.path.join(ROOT, "L M 1 Split/Back On 74 (2).wav")
folder = os.path.dirname(src)
cut = quietest(src, 30, 43)
print(f"\nBack On 74 (2) -> split at {cut:.2f}s")
write(src, os.path.join(folder, "Back On 74 (partial fragment).wav"), "Back On 74",
      "Jungle", end=cut)
write(src, uniq(folder, "My Feeling (Kick 'n Deep Mix)"), "My Feeling (Kick 'n Deep Mix)",
      "Junior Jack", start=cut)

# ---- 3. retags (whole file is one song, wrong label) ----------------------
print()
for rel, title, artist in [
    ("E F Split/Say It (feat. Tove Lo) (2).wav", "Say It (Illenium Remix)", "Flume, ILLENIUM, Tove Lo"),
    ("N O P Q R S #02 Split/Little Bit of Love.wav", "deja vu", "Olivia Rodrigo"),
]:
    src = os.path.join(ROOT, rel)
    folder = os.path.dirname(src)
    dest = uniq(folder, title)
    print(f"{rel}")
    write(src, dest, title, artist)
    if APPLY:
        os.unlink(src)

print("\nDRY RUN -- pass --apply to write" if not APPLY else "\nDONE")
