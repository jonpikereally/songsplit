#!/usr/bin/env python3
"""
Reorganize the hi-res library into one folder per artist.

Artist comes from the ID3 tag where present (written by the Serato transfer)
and falls back to the RIFF INFO tag. Files are filed under the PRIMARY artist,
matching the existing Serato library layout ("A Touch of Class", not
"A Touch Of Class, Pete Konemann"), and folder names reuse the spelling
already used over there so the two libraries stay consistent.

Usage: sort_by_artist.py [--apply]
"""
import json, os, re, shutil, subprocess, sys, unicodedata
from mutagen.wave import WAVE

HIRES = "/Volumes/Jons 16TB HDD/hi res"
MUSIC = "/Volumes/Jons Playback SSD/DJ JRJP aug 25/Music"
APPLY = "--apply" in sys.argv


def primary_artist(s):
    """First credited artist: 'Ariana Grande, Zedd' -> 'Ariana Grande'."""
    if not s:
        return None
    s = re.split(r"\s*[;,]\s*|\s+&\s+|\s+feat\.?\s+|\s+featuring\s+|\s+with\s+|\s+/\s+",
                 s.strip())[0]
    return s.strip() or None


def key(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def safe(s):
    s = re.sub(r'[/\\:*?"<>|]', "", s or "").strip().rstrip(".")
    return s or "Unknown Artist"


def read_artist(path):
    try:
        t = WAVE(path).tags
        if t and "TPE1" in t:
            a = str(t["TPE1"]).strip()
            if a:
                return a, "id3"
    except Exception:
        pass
    r = subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "quiet", "-show_entries",
                        "format_tags=artist", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    a = (r.stdout or "").strip()
    return (a, "riff") if a else (None, None)


# folder spellings already used in the Serato library
canon = {}
if os.path.isdir(MUSIC):
    for d in os.listdir(MUSIC):
        if os.path.isdir(os.path.join(MUSIC, d)) and not d.startswith("."):
            canon[key(d)] = d

files = []
for root, _dirs, names in os.walk(HIRES):
    for n in names:
        if n.lower().endswith(".wav") and not n.startswith("."):
            files.append(os.path.join(root, n))
files.sort()

plan, noartist = [], []
for f in files:
    raw, src = read_artist(f)
    p = primary_artist(raw)
    if not p:
        noartist.append(f)
        continue
    folder = canon.get(key(p), safe(p))
    plan.append({"src": f, "artist": folder, "name": os.path.basename(f), "from": src})

# resolve destination collisions
taken, moves = set(), []
for item in plan:
    d = os.path.join(HIRES, item["artist"])
    base, ext = os.path.splitext(item["name"])
    dest = os.path.join(d, base + ext)
    n = 2
    while dest.lower() in taken or (os.path.exists(dest) and os.path.abspath(dest) != os.path.abspath(item["src"])):
        dest = os.path.join(d, f"{base} ({n}){ext}")
        n += 1
    taken.add(dest.lower())
    moves.append((item["src"], dest, item["artist"]))

artists = sorted({a for _s, _d, a in moves})
reused = sum(1 for _s, _d, a in moves if key(a) in canon)
print(f"files: {len(files)}   with artist tag: {len(moves)}   without: {len(noartist)}")
print(f"artist folders to create: {len(artists)}   (name reused from Serato library: {reused} files)")
big = {}
for _s, _d, a in moves:
    big[a] = big.get(a, 0) + 1
print("\nlargest folders:")
for a, c in sorted(big.items(), key=lambda x: -x[1])[:8]:
    print(f"   {c:3}  {a}")
if noartist:
    print(f"\nno artist tag ({len(noartist)}) -- these stay where they are:")
    for f in noartist[:10]:
        print("   ", f.replace(HIRES + "/", ""))

json.dump({"moves": moves, "noartist": noartist}, open("sort_plan.json", "w"), indent=1)

if APPLY:
    done = 0
    for src, dest, _a in moves:
        if os.path.abspath(src) == os.path.abspath(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        done += 1
        if done % 200 == 0:
            print(f"  moved {done}/{len(moves)}", flush=True)
    # drop folders that are now empty
    removed = 0
    for root, dirs, names in os.walk(HIRES, topdown=False):
        if root == HIRES:
            continue
        left = [n for n in os.listdir(root) if n not in (".DS_Store",)]
        if not left:
            for n in os.listdir(root):
                os.remove(os.path.join(root, n))
            os.rmdir(root)
            removed += 1
    print(f"\nAPPLIED: moved {done} files, removed {removed} empty folders")
else:
    print("\nDRY RUN -- pass --apply to move the files")
