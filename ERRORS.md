# SongSplit error codes

Every error and warning SongSplit shows carries a code like `SS-302`. Search this page for the
code to find what it means and what to do.

**Troubleshooting with an LLM:** in an error dialog, click **Copy Error Details** and paste the
result into the chat. It includes the code, the message, the app version, build, commit and
macOS version. For errors that appear in the log, copy the whole log instead: the lines just
above the code usually show what led to it.

| Range | Area | Raised by |
|---|---|---|
| SS-1xx | Setup and input files | splitter, in the log |
| SS-2xx | Analysing the recording | splitter, in the log |
| SS-3xx | Song identification (Shazam) | splitter, in the log |
| SS-4xx | Writing the output files | splitter, in the log |
| SS-5xx | Running a split | app, in the log and status |
| SS-6xx | Checking for and installing updates | app, in a dialog |
| SS-7xx | Cut warnings: the file was written, but check it | splitter, in the log |
| SS-9xx | Unexpected errors | splitter, in the log |

Errors stop the split. Warnings (`**` in the log) do not. The file is still written, but it is
worth listening to.

## SS-1xx · Setup and input

### SS-101
**ffmpeg not found.** SongSplit uses ffmpeg to read and cut audio.
Fix: `brew install ffmpeg`, then run the split again.

### SS-102
**ffprobe not found.** It comes with ffmpeg. Fix: `brew install ffmpeg`.

### SS-103
**Audio file not found.** The recording was moved, renamed or deleted after it was chosen, or
the drive it is on was disconnected. Fix: choose the file again.

### SS-104
**Playlist CSV not found.** Same causes as SS-103, for the CSV. Fix: add the CSV again.

### SS-105
**No audio file given.** Only a CSV was supplied. Fix: add the recording as well.

### SS-106
**More than one audio file given** to a single command-line run. The app splits several
recordings one after another, so this only happens on the command line. Fix: run once per file.

### SS-107
**Could not read the length of the recording.** The file is damaged, empty, still being written,
or not audio. Fix: open it in another player to check it plays; re-export it if not.

### SS-108
**Could not read the playlist CSV.** It is not UTF-8 text, or not a CSV. SongSplit expects an
[Exportify](https://exportify.net) export with columns like `Track Name`, `Artist Name(s)` and
`Duration (ms)`. Fix: export the playlist again.

## SS-2xx · Analysing the recording

### SS-201
**No songs found.** Nothing in the recording was loud enough, or long enough, to count as a song
(at least 30 seconds of sound above -40 dB). The recording may be silent, or recorded at a very
low level. Fix: check the recording has sound. On the command line, `--noise -35dB` or
`--min-song 20` loosen the thresholds.

### SS-202
**ffmpeg could not read part of the recording** while looking for a cut point. The file is
probably damaged at that position. Fix: check the recording plays through that point.

## SS-3xx · Song identification

### SS-301
**The song identification helper could not be installed or loaded.** On first use, SongSplit
installs `shazamio` into `~/.songsplit-venv`, which needs internet access. Fix: check the
connection and run again. If it keeps failing, delete `~/.songsplit-venv` and run again. To split
without identification, tick **Skip song identification (offline)**.

### SS-302
**A Shazam lookup failed three times** (warning). The song is left unidentified, so it is named
from the playlist CSV if one matches by length, or `Track N` if not. The message names the
underlying error:
- `ClientConnectorError`, `TimeoutError`, `ServerDisconnectedError`: no connection to Shazam.
  Check the internet connection.
- HTTP 429 or "Too Many Requests": Shazam is rate-limiting. Wait 15–30 minutes and run again.
- Anything else, especially on every song: Shazam may have changed its service. Updating
  `shazamio` usually fixes it: delete `~/.songsplit-venv` and run again to reinstall it.

### SS-303
**Could not cut a sample to identify** (warning). ffmpeg failed to read 12 seconds of audio at
that point, so the song is left unidentified. Usually the recording is damaged there.

## SS-4xx · Writing files

### SS-401
**Could not write a song file.** The message ends with ffmpeg's reason. Common causes: the disk
is full, the output drive was disconnected, or there is no permission to write there. Fix: free
space or choose a recording on a writable drive. The output folder is next to the recording.

### SS-402
**Could not create the output folder**, or an artist folder inside it. Same causes as SS-401.

## SS-5xx · Running a split (app)

### SS-501
**Could not start the splitter.** The app runs `songsplit.py` with `/usr/bin/python3`, which
macOS provides once the Command Line Tools are installed. Fix: run `xcode-select --install`,
then try again.

### SS-502
**The splitter stopped unexpectedly** without reporting its own code. The exit status is in the
message, and the log above usually shows why. Copy the whole log when asking for help.

### SS-503
**The splitter script is missing from the app.** The app bundle is incomplete. Fix: download
SongSplit again from the [releases page](https://github.com/jonpikereally/songsplit/releases/latest).

## SS-6xx · Updates (app)

### SS-601
**Could not reach GitHub** to check for updates. Usually no internet connection, or a firewall
or VPN blocking `api.github.com`.

### SS-602
**No releases have been published.** Nothing to update to yet.

### SS-603
**Unexpected reply from GitHub.** The message includes the HTTP status. 403 usually means
GitHub's rate limit for unauthenticated requests; wait an hour and try again.

### SS-604
**Could not download the update.** The connection dropped, or the download link stopped
working. Try again, or download it from the
[releases page](https://github.com/jonpikereally/songsplit/releases/latest).

### SS-605
**Could not unpack the update.** The download is incomplete or damaged. Try again.

### SS-606
**The update did not contain an app.** The release zip is wrong; report it.

### SS-607
**The folder containing SongSplit is not writable**, so the app cannot replace itself. Usually
SongSplit is running from a disk image or a read-only folder. Fix: move SongSplit.app into
Applications and update from there, or download the new version by hand.

### SS-608
**Could not replace the app with the update.** macOS refused the move. The original app is
put back. Fix: download the new version from the releases page and replace SongSplit.app by
hand.

## SS-7xx · Cut warnings

The file is written, but it may not be cut where you want. Listen to it.

### SS-701
**A song is more than 15 seconds shorter than expected** from the playlist or iTunes length. It
may be cut off, or it may be a shorter edit than the one in the playlist.

### SS-702
**A song runs longer than expected and no quiet point was found** near its expected end, so it
was left whole. It may be a longer version (extended mix, live), or contain the start of the next
song when two songs play back to back with no gap.

### SS-703
**Two songs play back to back with no gap and no quiet point was found** between them, so the
cut was made at the expected end of the first song. The cut may land a few seconds early or late.

## SS-9xx · Unexpected

### SS-900
**An unexpected error.** A bug in SongSplit. The log shows a Python traceback above the code;
include the whole log when reporting it.

---

Adding a code: pick the next free number in the right range, add it here, and never reuse or
renumber an existing code.
