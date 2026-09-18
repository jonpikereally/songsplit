#!/usr/bin/env python3
"""
SongSplit — a window for splitting a concatenated WAV into tagged songs.

Wraps songsplit.py: the splitting logic is unchanged, this just runs it and
shows progress instead of a Terminal window. Files can be dropped on the app
icon (they arrive as argv) or chosen here.
"""
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
SPLITTER = os.path.join(HERE, "songsplit.py")
PY = "/usr/bin/python3"

BG = "#1e1f22"
PANEL = "#2a2c30"
INK = "#e8e9ec"
MUTED = "#9aa0a8"
ACCENT = "#2f9e7f"


class App:
    def __init__(self, root, initial):
        self.root = root
        self.proc = None
        self.q = queue.Queue()
        self.wavs = [f for f in initial if not f.lower().endswith(".csv")]
        self.csvs = [f for f in initial if f.lower().endswith(".csv")]
        self.out_dir = None

        root.title("SongSplit")
        root.configure(bg=BG)
        root.geometry("720x560")
        root.minsize(620, 460)

        style = ttk.Style()
        try:
            style.theme_use("aqua")
        except tk.TclError:
            pass

        wrap = tk.Frame(root, bg=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=16)

        tk.Label(wrap, text="SongSplit", bg=BG, fg=INK,
                 font=("Helvetica Neue", 22, "bold")).pack(anchor="w")
        tk.Label(wrap, text="Split one long WAV into separate, tagged songs.",
                 bg=BG, fg=MUTED, font=("Helvetica Neue", 12)).pack(anchor="w", pady=(0, 12))

        # --- files ---------------------------------------------------------
        box = tk.Frame(wrap, bg=PANEL, highlightbackground="#3a3d42",
                       highlightthickness=1)
        box.pack(fill="x", pady=(0, 12))
        self.file_lbl = tk.Label(box, text="", bg=PANEL, fg=INK, justify="left",
                                 anchor="w", font=("Helvetica Neue", 12), wraplength=640)
        self.file_lbl.pack(fill="x", padx=14, pady=(12, 4))
        self.csv_lbl = tk.Label(box, text="", bg=PANEL, fg=MUTED, justify="left",
                                anchor="w", font=("Helvetica Neue", 11), wraplength=640)
        self.csv_lbl.pack(fill="x", padx=14, pady=(0, 10))

        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(row, text="Choose audio…", command=self.pick_wav).pack(side="left")
        ttk.Button(row, text="Add playlist CSV…", command=self.pick_csv).pack(side="left", padx=8)
        ttk.Button(row, text="Clear", command=self.clear).pack(side="left")

        # --- options -------------------------------------------------------
        opts = tk.Frame(wrap, bg=BG)
        opts.pack(fill="x", pady=(0, 10))
        self.dry = tk.BooleanVar(value=False)
        self.noshazam = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Preview only (write nothing)",
                        variable=self.dry).pack(side="left")
        ttk.Checkbutton(opts, text="Skip song identification (offline)",
                        variable=self.noshazam).pack(side="left", padx=16)

        # --- action --------------------------------------------------------
        act = tk.Frame(wrap, bg=BG)
        act.pack(fill="x", pady=(0, 10))
        self.go = ttk.Button(act, text="Split", command=self.start)
        self.go.pack(side="left")
        self.stop_btn = ttk.Button(act, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        self.reveal = ttk.Button(act, text="Show in Finder", command=self.show_finder,
                                 state="disabled")
        self.reveal.pack(side="left")
        self.status = tk.Label(act, text="Ready", bg=BG, fg=MUTED,
                               font=("Helvetica Neue", 11))
        self.status.pack(side="right")

        self.bar = ttk.Progressbar(wrap, mode="determinate", maximum=100)
        self.bar.pack(fill="x", pady=(0, 10))

        # --- log -----------------------------------------------------------
        logwrap = tk.Frame(wrap, bg=BG)
        logwrap.pack(fill="both", expand=True)
        self.log = tk.Text(logwrap, bg="#141517", fg="#c9ccd1", bd=0,
                           font=("SF Mono", 11), wrap="none", padx=12, pady=10,
                           insertbackground=INK, highlightthickness=1,
                           highlightbackground="#3a3d42")
        sb = ttk.Scrollbar(logwrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("song", foreground="#7fd1b0")
        self.log.tag_configure("warn", foreground="#e0a458")
        self.log.tag_configure("dim", foreground=MUTED)

        self.refresh()
        self.root.after(80, self.drain)

    # ---------------------------------------------------------------- files
    def refresh(self):
        if self.wavs:
            names = [os.path.basename(w) for w in self.wavs]
            self.file_lbl.config(text="  •  ".join(names), fg=INK)
        else:
            self.file_lbl.config(text="No audio chosen — drop a WAV on the app icon, "
                                      "or use “Choose audio…”", fg=MUTED)
        self.csv_lbl.config(
            text=("Playlist: " + ", ".join(os.path.basename(c) for c in self.csvs))
            if self.csvs else "No playlist CSV (song titles still come from audio "
                              "identification)")
        self.go.config(state="normal" if self.wavs else "disabled")

    def pick_wav(self):
        f = filedialog.askopenfilenames(
            title="Choose the audio to split",
            filetypes=[("Audio", "*.wav *.aif *.aiff *.flac *.mp3"), ("All files", "*.*")])
        if f:
            self.wavs = list(f)
            self.refresh()

    def pick_csv(self):
        f = filedialog.askopenfilenames(title="Choose playlist CSV",
                                        filetypes=[("CSV", "*.csv")])
        if f:
            self.csvs = list(f)
            self.refresh()

    def clear(self):
        self.wavs, self.csvs = [], []
        self.refresh()

    def show_finder(self):
        if self.out_dir and os.path.isdir(self.out_dir):
            subprocess.run(["open", self.out_dir])

    # ------------------------------------------------------------- running
    def write(self, text, tag=None):
        self.log.config(state="normal")
        self.log.insert("end", text, tag or ())
        self.log.see("end")
        self.log.config(state="disabled")

    def start(self):
        if self.proc or not self.wavs:
            return
        self.log.config(state="normal"); self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.out_dir = None
        self.reveal.config(state="disabled")
        self.go.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.bar.config(mode="indeterminate")
        self.bar.start(14)
        self.status.config(text="Working…", fg=INK)
        threading.Thread(target=self.run_all, daemon=True).start()

    def run_all(self):
        for i, wav in enumerate(self.wavs, 1):
            if len(self.wavs) > 1:
                self.q.put(("line", f"\n=== {i}/{len(self.wavs)}  "
                                    f"{os.path.basename(wav)} ===\n", "dim"))
            cmd = [PY, "-u", SPLITTER, wav] + self.csvs
            if self.dry.get():
                cmd.append("--dry-run")
            if self.noshazam.get():
                cmd.append("--no-shazam")
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True,
                                             bufsize=1)
            except Exception as e:
                self.q.put(("line", f"could not start: {e}\n", "warn"))
                break
            for line in self.proc.stdout:
                tag = None
                if re.match(r"\s*\d+\.\s", line):
                    tag = "song"
                if "**" in line or "failed" in line.lower() or "error" in line.lower():
                    tag = "warn"
                m = re.search(r"written to: (.+)$", line.strip())
                if m:
                    self.q.put(("out", m.group(1), None))
                self.q.put(("line", line, tag))
            rc = self.proc.wait()
            self.proc = None
            if rc != 0:
                self.q.put(("line", f"\nstopped (exit {rc})\n", "warn"))
                break
        self.q.put(("done", None, None))

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.write("\nstopping…\n", "warn")

    def drain(self):
        try:
            while True:
                kind, payload, tag = self.q.get_nowait()
                if kind == "line":
                    self.write(payload, tag)
                elif kind == "out":
                    self.out_dir = payload
                elif kind == "done":
                    self.bar.stop()
                    self.bar.config(mode="determinate", value=100)
                    self.go.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self.status.config(text="Finished", fg=ACCENT)
                    if self.out_dir:
                        self.reveal.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(80, self.drain)


def main():
    args = [a for a in sys.argv[1:] if os.path.exists(a)]
    root = tk.Tk()
    App(root, args)
    root.lift()
    root.attributes("-topmost", True)
    root.after(400, lambda: root.attributes("-topmost", False))
    root.mainloop()


if __name__ == "__main__":
    main()
