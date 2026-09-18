#!/usr/bin/env python3
"""
Make the embedded TITLE state the version, so a remix is distinguishable from
the original inside Serato (which shows the tag, not the filename).

Strictly ADDITIVE: a title only gains version information it was missing.
Nothing is stripped ("Extended Steve Aoki Remix" keeps "Extended") and purely
cosmetic differences -- capitalisation, curly vs straight apostrophes, spacing
-- are left alone, because rewriting those is churn, not classification.

Also credits the remixer as a SECONDARY artist where the fingerprint named
one, so the primary artist -- and therefore the folder -- is unchanged.

Usage: classify_remixes.py [--apply]
"""
import json, os, re, subprocess, sys
from mutagen.wave import WAVE
from mutagen.id3 import TIT2, TPE1, TALB, TDRC, TCON

H = "/Volumes/Jons 16TB HDD/hi res"
APPLY = "--apply" in sys.argv

VERSION_KW = re.compile(
    r"remix|radio edit|club edit|acoustic|single version|extended|bootleg|"
    r"mashup|rework|flip|instrumental|\bversion revisited\b|\bpartial\b", re.I)

# remixers established by audio fingerprint earlier in this session
REMIXER = {
    "Lana Del Rey/Summertime Sadness - Cedric Gervais Remix.wav": "Cedric Gervais",
    "Marvin Gaye/Sexual Healing - Kygo Remix.wav": "Kygo",
    "Marvin Gaye/Sexual Healing - Kygo Remix - partial.wav": "Kygo",
    "Tove Lo/Habits (Stay High) - Hippie Sabotage Remix.wav": "Hippie Sabotage",
    "Tove Lo/Habits (Stay High) - Hippie Sabotage Remix - partial.wav": "Hippie Sabotage",
    "The Chainsmokers/Don't Let Me Down - Illenium Remix.wav": "ILLENIUM",
    "Kid Cudi/Pursuit Of Happiness - Steve Aoki Remix.wav": "Steve Aoki",
    "Kid Cudi/Pursuit Of Happiness - Steve Aoki Remix - partial.wav": "Steve Aoki",
    "Cardi B/I Like It - Dillon Francis Remix.wav": "Dillon Francis",
    "Kid Cudi/Day 'N' Nite - Crookers Remix.wav": "Crookers",
}

# tags proven wrong by fingerprint (the file is NOT the version the tag claims)
CORRECT_TAG = {
    "Kid Cudi/Day 'N' Nite.wav": "Day 'N' Nite",
}

# filename should gain the remix credit its tag already carries
RENAME = {
    "Madism/Pumped Up Kicks.wav": "Pumped Up Kicks (Madism Remix).wav",
}

# tag and filename disagree about which recording this is -- needs a human ear
SKIP = {
    "Laidback Luke/Show Me Love - Radio Edit.wav",
    "Enur/Calabria 2007 (feat. Natasja) [Radio Edit].wav",
}


def riff(p):
    r = subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "quiet", "-show_entries",
                        "format_tags=artist,album,date,genre", "-of", "json", p],
                       capture_output=True, text=True)
    return (json.loads(r.stdout or "{}").get("format", {}) or {}).get("tags", {}) or {}


changes = []
for root, _d, names in os.walk(H):
    for n in sorted(names):
        if not n.lower().endswith(".wav"):
            continue
        p = os.path.join(root, n)
        rel = os.path.relpath(p, H)
        if rel in SKIP:
            continue
        stem = n[:-4]
        try:
            t = WAVE(p).tags
        except Exception:
            continue
        cur = str(t["TIT2"]) if t and "TIT2" in t else None
        cur_art = str(t["TPE1"]) if t and "TPE1" in t else None

        new_title = None
        if rel in CORRECT_TAG:
            if cur != CORRECT_TAG[rel]:
                new_title = CORRECT_TAG[rel]
        elif VERSION_KW.search(stem) and (cur is None or not VERSION_KW.search(cur)):
            # the tag is missing the version; a " (2)" disambiguating suffix is
            # a filesystem artifact and must not become part of the title
            new_title = re.sub(r" \(\d+\)$", "", stem)
            if cur == new_title:
                new_title = None

        rx = REMIXER.get(rel)
        new_art = cur_art
        if rx and cur_art and rx.lower() not in cur_art.lower():
            new_art = f"{cur_art}, {rx}"

        if new_title or new_art != cur_art:
            changes.append((p, rel, cur, new_title, cur_art, new_art))

print(f"{len(changes)} files to update, {len(RENAME)} to rename, {len(SKIP)} skipped\n")
for p, rel, cur, nt, ca, na in changes:
    print(f"  {rel}")
    if nt:
        print(f"      title : {cur!r} -> {nt!r}")
    if na != ca:
        print(f"      artist: {ca!r} -> {na!r}")
if SKIP:
    print("\nskipped (tag and filename name different recordings -- check by ear):")
    for s in SKIP:
        print(f"  {s}")

if APPLY:
    for p, rel, cur, nt, ca, na in changes:
        a = WAVE(p)
        if a.tags is None:
            a.add_tags()
        tg = a.tags
        if "TPE1" not in tg:            # don't leave Serato a blank artist
            rt = riff(p)
            for k, F in (("artist", TPE1), ("album", TALB), ("date", TDRC), ("genre", TCON)):
                if rt.get(k):
                    tg.add(F(encoding=3, text=rt[k]))
        if nt:
            tg.add(TIT2(encoding=3, text=nt))
        if na and na != ca:
            tg.add(TPE1(encoding=3, text=na))
        a.save()
    for rel, newname in RENAME.items():
        src = os.path.join(H, rel)
        if os.path.exists(src):
            os.rename(src, os.path.join(os.path.dirname(src), newname))
    print(f"\nAPPLIED: updated {len(changes)} tags, renamed {len(RENAME)} file(s)")
else:
    print("\nDRY RUN -- pass --apply")
