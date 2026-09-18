#!/usr/bin/env python3
"""
Finish and harden the split-library audit.

Three phases, all resume-safe:
  1. Re-verify flagged suspects with THREE samples per file, so a file that
     contains two songs is distinguishable from a genuinely mislabeled one.
  2. Audit files never reached in the first pass.
  3. Retry files whose lookup failed (rate limited), with 3 samples each.

Results append to verify.jsonl. Re-running skips finished files, so if
Shazam throttles us again the next run simply picks up where this stopped.
"""
import asyncio, difflib, glob, json, os, re, subprocess, sys, time, unicodedata

os.dup2(os.open(os.devnull, os.O_WRONLY), 2)      # silence decoder chatter
from shazamio import Shazam

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = "/Volumes/Jons 16TB HDD/hi res"
AUDIT = os.path.join(HERE, "audit.jsonl")          # first-pass results
OUT = os.path.join(HERE, "verify.jsonl")
LOG = os.path.join(HERE, "verify.log")

DELAY = 3.0          # between lookups; deliberately gentle
TIMEOUT = 30
SAMPLES = (0.15, 0.40, 0.72)   # fractions through the song to fingerprint
GIVE_UP_AFTER = 25   # consecutive failures => throttled, stop and save


def log(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    with open(LOG, "a") as fh:
        fh.write(line + "\n")


def nrm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|feat\.?.*|featuring.*|with .*| - .*", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def artist_set(s):
    out = set()
    for p in re.split(r"[;,&/]| feat\.? | featuring | with | x ", (s or "").lower()):
        p = unicodedata.normalize("NFKD", p).encode("ascii", "ignore").decode()
        p = re.sub(r"[^a-z0-9]", "", p)
        if p:
            out.add(p)
    return out


def same_song(tag_t, tag_a, sz_t, sz_a):
    if not sz_t:
        return None
    if nrm(tag_t) == nrm(sz_t):
        return True
    shared = artist_set(tag_a) & artist_set(sz_a)
    sim = difflib.SequenceMatcher(None, nrm(tag_t), nrm(sz_t)).ratio()
    if shared and (sim >= 0.55 or nrm(tag_t) in nrm(sz_t) or nrm(sz_t) in nrm(tag_t)):
        return True
    return False


def probe(f):
    r = subprocess.run(["/opt/homebrew/bin/ffprobe", "-v", "quiet", "-show_entries",
                        "format=duration:format_tags=title,artist", "-of", "json", f],
                       capture_output=True, text=True)
    d = json.loads(r.stdout or "{}").get("format", {})
    tg = d.get("tags", {}) or {}
    return float(d.get("duration", 0) or 0), tg.get("title"), tg.get("artist")


class Throttled(Exception):
    pass


class Runner:
    def __init__(self):
        self.sh = Shazam()
        self.fails = 0

    async def listen(self, f, dur, frac):
        clip = os.path.join("/tmp", f"verify_{os.getpid()}.ogg")
        subprocess.run(["/opt/homebrew/bin/ffmpeg", "-y", "-v", "quiet",
                        "-ss", str(max(2.0, dur * frac)), "-t", "12", "-i", f,
                        "-ac", "1", "-ar", "44100", clip], capture_output=True)
        await asyncio.sleep(DELAY)
        try:
            t = (await asyncio.wait_for(self.sh.recognize(clip), TIMEOUT)).get("track", {}) or {}
            self.fails = 0
            return {"title": t.get("title"), "artist": t.get("subtitle")} if t else None
        except Exception:
            self.fails += 1
            if self.fails >= GIVE_UP_AFTER:
                raise Throttled()
            return None
        finally:
            try:
                os.unlink(clip)
            except OSError:
                pass

    async def check(self, rel, fracs):
        f = os.path.join(ROOT, rel)
        if not os.path.exists(f):
            return {"path": rel, "verdict": "GONE"}
        dur, tt, ta = probe(f)
        hits = []
        for fr in fracs:
            h = await self.listen(f, dur, fr)
            hits.append({"at": round(fr, 2), **(h or {"title": None, "artist": None})})
        ids = [h for h in hits if h["title"]]
        if not ids:
            verdict = "noid"
        elif any(same_song(tt, ta, h["title"], h["artist"]) for h in ids):
            distinct = {nrm(h["title"]) for h in ids}
            verdict = "ok" if len(distinct) == 1 else "TWO_SONGS"
        else:
            distinct = {nrm(h["title"]) for h in ids}
            verdict = "MISLABELED" if len(distinct) == 1 else "TWO_SONGS"
        return {"path": rel, "dur": round(dur, 1), "tag_title": tt, "tag_artist": ta,
                "hits": hits, "verdict": verdict}


async def main():
    prior = {}
    if os.path.exists(AUDIT):
        for line in open(AUDIT):
            try:
                r = json.loads(line)
                prior[r["path"]] = r["verdict"]
            except Exception:
                pass
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try:
                done.add(json.loads(line)["path"])
            except Exception:
                pass

    all_files = [f.split("/hi res/")[1]
                 for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.wav"), recursive=True))]
    suspects = [p for p, v in prior.items() if v == "SUSPECT"]
    noids = [p for p, v in prior.items() if v == "noid"]
    unseen = [p for p in all_files if p not in prior]

    queue = ([(p, SAMPLES) for p in suspects if p not in done]
             + [(p, SAMPLES) for p in noids if p not in done]
             + [(p, SAMPLES[:2]) for p in unseen if p not in done])
    log(f"start: {len(suspects)} suspects, {len(noids)} unidentified, "
        f"{len(unseen)} never audited -> {len(queue)} files to do")

    r = Runner()
    counts = {}
    try:
        for i, (rel, fracs) in enumerate(queue, 1):
            rec = await r.check(rel, fracs)
            counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
            with open(OUT, "a") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if rec["verdict"] in ("MISLABELED", "TWO_SONGS"):
                log(f"  {rec['verdict']}: {rel}")
            if i % 20 == 0:
                log(f"  {i}/{len(queue)}  {counts}")
    except Throttled:
        log(f"THROTTLED by Shazam after {GIVE_UP_AFTER} straight failures — "
            f"progress saved, re-run this script later to continue")
        return
    log(f"COMPLETE: {counts}")


asyncio.run(main())
