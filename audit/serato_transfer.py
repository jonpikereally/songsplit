#!/usr/bin/env python3
"""
Copy Serato metadata (hot cues, loops, beatgrid, playcount, BPM, key) from a
Serato library onto matching hi-res files.

The hi-res copies do not start at the same instant as the Serato copies, so
every time-based value is shifted by the measured audio offset. The offset is
measured twice per track -- near the start and near the middle -- and applied
only when both agree; a disagreement means the two files are different edits,
where no single shift is correct, so that track gets only the non-timed values
and is listed for review.

Usage:  serato_transfer.py pairs.json [--apply] [--limit N]
"""
import base64, json, os, struct, subprocess, sys

import numpy as np
from mutagen.wave import WAVE
from mutagen.id3 import GEOB

FFMPEG = "/opt/homebrew/bin/ffmpeg"
APPLY = "--apply" in sys.argv
LIMIT = None
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

WIN = 60.0          # seconds of audio per measurement window
AGREE = 0.030       # the two measurements must agree within 30 ms
MIN_CONF = 0.55     # minimum normalized correlation to trust a measurement


# ---------------------------------------------------------------- alignment

def envelope(path, start, secs=WIN):
    """1 ms-resolution loudness envelope, normalized."""
    r = subprocess.run([FFMPEG, "-v", "quiet", "-ss", f"{start:.2f}", "-t", f"{secs:.2f}",
                        "-i", path, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       capture_output=True)
    x = np.frombuffer(r.stdout[: len(r.stdout) // 2 * 2], dtype="<i2").astype(np.float32)
    if len(x) < 8000 * 5:
        return None
    n = len(x) // 8
    e = np.abs(x[: n * 8]).reshape(n, 8).mean(1)
    return (e - e.mean()) / (e.std() + 1e-9)


def measure(hires, music, start, maxlag=15.0):
    """Seconds by which the hi-res audio starts LATER than the Serato copy."""
    a, b = envelope(hires, start), envelope(music, start)
    if a is None or b is None:
        return None, 0.0
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    c = np.correlate(a, b, mode="full")
    lags = np.arange(-n + 1, n)
    m = np.abs(lags) <= maxlag * 1000
    c, lags = c[m], lags[m]
    i = int(np.argmax(c))
    conf = float(c[i] / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
    return lags[i] / 1000.0, conf


def offset_for(hires, music, dur):
    """Two independent measurements; return (offset, note) or (None, why)."""
    o1, c1 = measure(hires, music, 0.0)
    mid = max(0.0, dur / 2 - WIN / 2)
    o2, c2 = measure(hires, music, mid) if dur > 2.5 * WIN else (o1, c1)
    if o1 is None or o2 is None:
        return None, "too short to measure"
    if c1 < MIN_CONF or c2 < MIN_CONF:
        return None, f"low confidence ({c1:.2f}/{c2:.2f})"
    if abs(o1 - o2) > AGREE:
        return None, f"different edit (start {o1:+.3f}s vs middle {o2:+.3f}s)"
    return (o1 + o2) / 2, f"conf {min(c1, c2):.2f}"


# ------------------------------------------------------------ serato format

def _b64_decode(b64):
    """Serato null-pads the blob to a fixed size, which can leave a stray
    trailing character; base64 length is never 1 more than a multiple of 4."""
    b64 = b64.replace(b"\n", b"").replace(b"\r", b"").rstrip(b"\x00").rstrip()
    while len(b64) % 4 == 1:
        b64 = b64[:-1]
    return base64.b64decode(b64 + b"=" * (-len(b64) % 4))


def shift_markers2(data, ms):
    """Shift every CUE / LOOP position inside a Serato Markers2 blob."""
    head = data[:2]
    payload = _b64_decode(data[2:])
    out, i = bytearray(payload[:2]), 2
    while i < len(payload):
        j = payload.find(b"\x00", i)
        if j < 0:
            break
        name = payload[i:j]
        if not name:
            break
        ln = struct.unpack(">I", payload[j + 1:j + 5])[0]
        body = bytearray(payload[j + 5:j + 5 + ln])
        if name == b"CUE" and len(body) >= 6:
            pos = struct.unpack(">I", bytes(body[2:6]))[0]
            body[2:6] = struct.pack(">I", max(0, pos + ms))
        elif name == b"LOOP" and len(body) >= 10:
            st, en = struct.unpack(">II", bytes(body[2:10]))
            body[2:10] = struct.pack(">II", max(0, st + ms), max(0, en + ms))
        out += name + b"\x00" + struct.pack(">I", len(body)) + bytes(body)
        i = j + 5 + ln
    out += b"\x00"
    enc = base64.b64encode(bytes(out)).rstrip(b"=")
    new = head + enc
    if len(new) < len(data):        # keep Serato's original null padding
        new += b"\x00" * (len(data) - len(new))
    return new


def shift_beatgrid(data, secs):
    """Shift beatgrid marker positions (float seconds)."""
    if len(data) < 6:
        return data
    n = struct.unpack(">I", data[2:6])[0]
    out, off = bytearray(data[:6]), 6
    for k in range(n):
        if k < n - 1:
            pos, beats = struct.unpack(">If", data[off:off + 8])
            out += struct.pack(">If", max(0.0, pos + secs), beats)
        else:
            pos, bpm = struct.unpack(">ff", data[off:off + 8])
            out += struct.pack(">ff", max(0.0, pos + secs), bpm)
        off += 8
    out += data[off:]
    return bytes(out)


TIMED = {"Serato Markers2", "Serato BeatGrid"}
DROP = {"Serato Overview", "Serato Markers_"}   # waveform is regenerated;
                                                # legacy markers can't be shifted safely
# Serato reads the ID3 chunk in preference to the RIFF INFO chunk, so the
# text tags have to come across as well or tracks show up blank in Serato.
# TLEN is deliberately excluded: it states the OLD file's length.
TEXT_FRAMES = ("TIT2", "TPE1", "TALB", "TCON", "TDRC", "TPUB", "TKEY", "TBPM",
               "TPE2", "TCOM", "TRCK", "TPOS")


def wanted_text(key):
    if key in TEXT_FRAMES:
        return True
    if key == "TXXX:SERATO_PLAYCOUNT":
        return True
    return key.startswith("TXXX:Spotify_") or key == "TXXX:Serato Analysis Flags"


def transfer(pair):
    m, h = pair["m"], pair["h"]
    src = WAVE(m).tags
    dur = WAVE(m).info.length
    off, note = offset_for(h, m, dur)

    dst = WAVE(h)
    if dst.tags is None:
        dst.add_tags()

    copied, timed = [], False
    for k in list(src.keys()):
        fr = src[k]
        if k.startswith("GEOB"):
            desc = fr.desc
            if desc in DROP:
                continue
            if desc in TIMED:
                if off is None:
                    continue                     # never write unshifted cues
                if desc == "Serato Markers2":
                    new = shift_markers2(fr.data, int(round(off * 1000)))
                else:
                    new = shift_beatgrid(fr.data, off)
                dst.tags.add(GEOB(encoding=0, mime=fr.mime, filename=fr.filename,
                                  desc=desc, data=new))
                copied.append(desc); timed = True
            else:
                dst.tags.add(fr); copied.append(desc)
        elif wanted_text(k):
            dst.tags.add(fr); copied.append(k.split(":")[-1])
    if APPLY:
        dst.save()
    return {"file": os.path.basename(h), "offset": off, "note": note,
            "timed": timed, "copied": copied,
            "playcount": pair.get("playcount")}


def main():
    pairs = json.load(open(sys.argv[1]))
    if LIMIT:
        pairs = pairs[:LIMIT]
    ok_timed, untimed_only, results = 0, [], []
    for i, p in enumerate(pairs, 1):
        try:
            r = transfer(p)
        except Exception as e:
            untimed_only.append((os.path.basename(p["h"]), f"ERROR {type(e).__name__}: {e}"))
            continue
        results.append(r)
        if r["timed"]:
            ok_timed += 1
        else:
            untimed_only.append((r["file"], r["note"]))
        if i % 25 == 0:
            print(f"  {i}/{len(pairs)}  cues transferred: {ok_timed}", flush=True)
    print(f"\n{'APPLIED' if APPLY else 'DRY RUN'}: {len(results)} files processed")
    print(f"  full transfer (cues+grid shifted): {ok_timed}")
    print(f"  playcount/BPM/key only          : {len(untimed_only)}")
    json.dump({"results": results, "needs_review": untimed_only},
              open("transfer_report.json", "w"), indent=1)
    if untimed_only:
        print("\n  needing review (first 15):")
        for f, why in untimed_only[:15]:
            print(f"    {f}: {why}")


main()
