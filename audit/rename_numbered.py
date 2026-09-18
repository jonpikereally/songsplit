#!/usr/bin/env python3
"""
Remove "(2)" / "(3)" suffixes from hi-res filenames.

Three cases:
  * the suffixed file is now alone in its artist folder -> just drop the number
  * it is a genuinely different version (remix, acoustic, edit) -> give it that
    name, taken from its audio fingerprint
  * it is a short excerpt of the same recording -> name it "... - partial"
Files that are the same recording at the same length can't both lose the
suffix (the names would collide); those are reported, not touched.

Usage: rename_numbered.py [--apply]
"""
import json, os, re, sys

H = "/Volumes/Jons 16TB HDD/hi res"
APPLY = "--apply" in sys.argv

# Identified by fingerprint: these files are a DIFFERENT recording from their
# sibling, so they get a distinguishing name instead of a number.
VERSIONS = {
 "Cardi B/I Like It - Dillon Francis Remix.wav":            "I Like It.wav",
 "Cardi B/I Like It - Dillon Francis Remix (2).wav":        "I Like It - Dillon Francis Remix.wav",
 "Foo Fighters/Everlong (2).wav":                           "Everlong - Acoustic Version.wav",
 "Kid Cudi/Day 'N' Nite - Crookers Remix (2).wav":          "Day 'N' Nite.wav",
 "Kid Cudi/Pursuit Of Happiness (Nightmare) (2).wav":       "Pursuit Of Happiness - Steve Aoki Remix.wav",
 "Kid Cudi/Pursuit Of Happiness (Nightmare) (3).wav":       "Pursuit Of Happiness - Steve Aoki Remix - partial.wav",
 "Lana Del Rey/Summertime Sadness (2).wav":                 "Summertime Sadness - Cedric Gervais Remix.wav",
 "Marvin Gaye/Sexual Healing (2).wav":                      "Sexual Healing - Kygo Remix.wav",
 "Marvin Gaye/Sexual Healing (3).wav":                      "Sexual Healing - Kygo Remix - partial.wav",
 "The Chainsmokers/Don't Let Me Down.wav":                  "Don't Let Me Down - Illenium Remix.wav",
 "The Chainsmokers/Don't Let Me Down (2).wav":              "Don't Let Me Down.wav",
 "Tove Lo/Habits (Stay High) (2).wav":                      "Habits (Stay High) - Hippie Sabotage Remix.wav",
 "Tove Lo/Habits (Stay High) (3).wav":                      "Habits (Stay High) - Hippie Sabotage Remix - partial.wav",
 # short excerpts of the same recording; the full copy takes the plain name
 "Ariana Grande/Dangerous Woman.wav":                       "Dangerous Woman - partial.wav",
 "Ariana Grande/Dangerous Woman (2).wav":                   "Dangerous Woman.wav",
 "James Taylor/How Sweet It Is (To Be Loved By You) - 2019 Remaster.wav":
     "How Sweet It Is (To Be Loved By You) - 2019 Remaster - partial.wav",
 "James Taylor/How Sweet It Is (To Be Loved By You) - 2019 Remaster (2).wav":
     "How Sweet It Is (To Be Loved By You) - 2019 Remaster.wav",
 "KAROL G/Tusa.wav":                                        "Tusa - partial.wav",
 "KAROL G/Tusa (2).wav":                                    "Tusa.wav",
 "Marvin Gaye/I Heard It Through The Grapevine.wav":        "I Heard It Through The Grapevine - partial.wav",
 "Marvin Gaye/I Heard It Through The Grapevine (2).wav":    "I Heard It Through The Grapevine.wav",
 "Ryan Gosling/I'm Just Ken (From Barbie The Album) (2).wav":
     "I'm Just Ken (From Barbie The Album) - partial.wav",
 "Luther Vandross/Never Too Much (3).wav":                  "Never Too Much - partial.wav",
 "Martin Solveig/Hello (feat. Dragonette) (2).wav":         "Hello (feat. Dragonette) - partial.wav",
}

NUM = re.compile(r"^(.*) \((\d+)\)\.wav$")


def plan():
    renames, blocked = [], []
    claimed = set()

    # explicit version/partial renames first
    for rel, newname in VERSIONS.items():
        src = os.path.join(H, rel)
        if not os.path.exists(src):
            continue
        dest = os.path.join(os.path.dirname(src), newname)
        renames.append((src, dest))
        claimed.add(dest.lower())

    handled = {os.path.join(H, r).lower() for r in VERSIONS}
    for root, _d, names in os.walk(H):
        for n in sorted(names):
            if not n.lower().endswith(".wav"):
                continue
            src = os.path.join(root, n)
            if src.lower() in handled:
                continue
            m = NUM.match(n)
            if not m:
                continue
            dest = os.path.join(root, m.group(1) + ".wav")
            free = (not os.path.exists(dest) or dest.lower() in
                    {s.lower() for s, _ in renames}) and dest.lower() not in claimed
            if free:
                renames.append((src, dest))
                claimed.add(dest.lower())
            else:
                blocked.append(src)
    return renames, blocked


renames, blocked = plan()
print(f"renames: {len(renames)}    left alone (name would collide): {len(blocked)}\n")
for s, d in renames:
    print(f"  {s.replace(H+'/',''):58} -> {os.path.basename(d)}")
if blocked:
    print(f"\nSAME RECORDING AS ITS SIBLING -- cannot drop the number without a clash:")
    for s in blocked:
        print(f"  {s.replace(H+'/','')}")

if APPLY:
    # two-phase so swaps (A->B, B->A) can't clobber
    tmp = []
    for i, (s, d) in enumerate(renames):
        t = os.path.join(os.path.dirname(s), f".rn{i}.tmp")
        os.rename(s, t)
        tmp.append((t, d))
    for t, d in tmp:
        os.rename(t, d)
    print(f"\nAPPLIED: renamed {len(renames)} files")
else:
    print("\nDRY RUN -- pass --apply")
