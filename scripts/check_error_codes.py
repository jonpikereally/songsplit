#!/usr/bin/env python3
"""Fail if any user-visible error lacks an SS-nnn code, or a code is not in ERRORS.md.

Every error SongSplit shows must carry a code so it can be looked up and
pasted into an LLM chat. Run by the Build workflow; also runs locally:

    python3 scripts/check_error_codes.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


py, swift, md = read("songsplit.py"), read("src/main.swift"), read("ERRORS.md")
problems = []

# Splitter: every die()/warn() call starts with a code.
for m in re.finditer(r"\b(die|warn)\(\s*([^,\n]*)", py):
    if py[max(0, m.start() - 4):m.start()] == "def ":
        continue                                   # the definitions themselves
    if not m.group(2).lstrip().startswith('"SS-'):
        line = py.count("\n", 0, m.start()) + 1
        problems.append(f"songsplit.py:{line}: {m.group(1)}() without an SS- code")
# Splitter: no bare "error:" prints that bypass die().
for m in re.finditer(r'print\(f?"error:', py):
    line = py.count("\n", 0, m.start()) + 1
    problems.append(f"songsplit.py:{line}: error printed without die() and a code")

# App: every UpdateError is constructed with a code; errors go through errorAlert/fail.
for m in re.finditer(r'UpdateError\("(?!SS-\d{3}")', swift):
    line = swift.count("\n", 0, m.start()) + 1
    problems.append(f"src/main.swift:{line}: UpdateError without an SS- code")
for m in re.finditer(r'\balert\("(Couldn|Could not|Can)', swift):
    line = swift.count("\n", 0, m.start()) + 1
    problems.append(f"src/main.swift:{line}: error shown with alert() instead of errorAlert()")

# Every code used is documented, and every documented code is used.
used = set(re.findall(r"SS-\d{3}", py + swift))
documented = set(re.findall(r"^### (SS-\d{3})", md, re.M))
problems += [f"{c} is used but not documented in ERRORS.md" for c in sorted(used - documented)]
problems += [f"{c} is documented in ERRORS.md but never used" for c in sorted(documented - used)]

if problems:
    print("Error-code check failed:")
    print("\n".join("  " + p for p in problems))
    sys.exit(1)
print(f"Error-code check passed: {len(documented)} codes, all used and documented.")
