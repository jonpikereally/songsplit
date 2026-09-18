#!/usr/bin/env python3
"""Fingerprint a file every N seconds to map which song plays where."""
import asyncio, json, os, subprocess, sys

os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
from shazamio import Shazam

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
STEP = float(os.environ.get("STEP", 20))
DELAY = 2.2

FILES = [
    "N O P Q R S #02 Split/Track 92.wav",
    "L M 2 Split/Animals (2).wav",
    "E F Split/Say It (feat. Tove Lo) (2).wav",
    "L M 1 Split/Back On 74 (2).wav",
    "N O P Q R S #02 Split/Fat Bottomed Girls - Remastered.wav",
    "N O P Q R S #02 Split/Little Bit of Love.wav",
    "Abyss.wav",
]
ROOT = "/Volumes/Jons 16TB HDD/hi res"


async def main():
    sh = Shazam()
    out = {}
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f"\n== {rel}: NOT FOUND")
            continue
        dur = float(subprocess.run([FFPROBE, "-v", "quiet", "-show_entries",
                                    "format=duration", "-of", "csv=p=0", path],
                                   capture_output=True, text=True).stdout or 0)
        print(f"\n== {rel}  [{int(dur//60)}:{int(dur%60):02d}]", flush=True)
        marks = []
        t = 3.0
        while t < dur - 8:
            clip = "/tmp/scan.ogg"
            subprocess.run([FFMPEG, "-y", "-v", "quiet", "-ss", str(t), "-t", "11",
                            "-i", path, "-ac", "1", "-ar", "44100", clip],
                           capture_output=True)
            await asyncio.sleep(DELAY)
            try:
                tr = (await asyncio.wait_for(sh.recognize(clip), 30)).get("track", {}) or {}
            except Exception:
                tr = {}
            label = f"{tr.get('subtitle')} - {tr.get('title')}" if tr else "(no match)"
            marks.append((round(t), label))
            print(f"   {int(t//60)}:{int(t%60):02d}  {label}", flush=True)
            t += STEP
        out[rel] = {"dur": dur, "marks": marks}
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "scan.json"), "w"), ensure_ascii=False, indent=1)

asyncio.run(main())
