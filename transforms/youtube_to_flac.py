#!/usr/bin/env python3
"""
Download a copied YouTube URL as tagged audio with embedded cover art.

Copy any YouTube / YouTube Music link and the audio is fetched in the
background, tagged (artist / title / album / year) and given embedded cover
art. Anything that isn't a YouTube URL passes through untouched, so this is
safe to leave selected while you use the clipboard normally.

Set AUDIO_MODE below to choose the output format.

Works on Windows and macOS. Requires the yt-dlp and ffmpeg binaries:

    macOS     brew install yt-dlp ffmpeg
    Windows   winget install yt-dlp.yt-dlp Gyan.FFmpeg

If ClipCommand is launched from Finder / Explorer it does not inherit your
shell PATH, so the binaries are also looked for in the usual install locations.
Set YTDLP_PATH / FFMPEG_PATH below (or in transforms.ini) to point at them
explicitly if they live somewhere unusual.

Note on quality: YouTube only ever serves lossy audio. FLAC here is lossless
with respect to the download, not to the original recording, so it cannot
recover anything YouTube already discarded — it only costs space. Re-encoding
to MP3 adds a second generation of loss on top of the first. Copying out the
AAC stream (the m4a default) avoids both.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_DIR       = "~/Music/YouTube"  # where finished tracks land
FILENAME_FORMAT  = "%(artist,uploader)s - %(track,title)s.%(ext)s"

# m4a  — YouTube's own AAC stream, copied out without re-encoding. Smallest
#        files, no second generation of loss. Best choice for most players.
# flac — lossless container. Same audio as m4a but ~4x the size; use it only
#        for a player that handles AAC badly.
# mp3  — re-encodes to MP3. Bigger than m4a and loses a little more; only
#        worth it for something that genuinely cannot play AAC.
AUDIO_MODE       = "m4a"

SQUARE_COVER     = 1      # 1 = centre-crop cover art to a square (looks right on a DAP)
CLEAN_TAGS       = 1      # 1 = keep only real music tags, drop the YouTube description
COMPRESSION      = 8      # FLAC compression level 0–12; higher = smaller, slower
NO_PLAYLIST      = 1      # 1 = grab only the video, even if the URL has a list= param
SKIP_DUPLICATES  = 1      # 1 = remember downloads and never fetch the same track twice
KEEP_URL         = 1      # 1 = leave the URL on the clipboard; 0 = replace with status
NOTIFY           = 1      # 1 = desktop notification when a download finishes

YTDLP_PATH       = ""     # explicit path to yt-dlp  (leave blank to auto-detect)
FFMPEG_PATH      = ""     # explicit path to ffmpeg  (leave blank to auto-detect)

# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

TAG = "[youtube_to_flac]"

_IS_WIN = sys.platform.startswith("win")

# Popen kwargs that keep a console window from flashing up on Windows.
_QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if _IS_WIN else {}

_YOUTUBE_URL = re.compile(
    r"https?://(?:[\w-]+\.)*(?:youtube\.com|youtu\.be|youtube-nocookie\.com)/\S*",
    re.IGNORECASE,
)

# URLs currently downloading — stops a re-copy kicking off a second fetch.
_in_flight = set()
_lock = threading.Lock()


# ── Binary discovery ──────────────────────────────────────────────────────────

def _candidate_dirs(name: str) -> list:
    """Where a Homebrew / winget / scoop / choco install typically puts things."""
    home = Path.home()
    if _IS_WIN:
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        progs = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        return [
            Path("C:/Tools"),
            local / "Microsoft/WinGet/Links",
            home / "scoop/shims",
            Path("C:/ProgramData/chocolatey/bin"),
            progs / name / "bin",
        ]
    return [
        Path("/opt/homebrew/bin"),      # Apple silicon
        Path("/usr/local/bin"),         # Intel / manual install
        home / ".local/bin",
        Path("/opt/local/bin"),         # MacPorts
    ]


def _find_binary(name: str, override: str) -> str:
    """Resolve a binary, tolerating the empty PATH of a Finder/Explorer launch."""
    if override:
        p = Path(override).expanduser()
        if p.is_file():
            return str(p)

    found = shutil.which(name)
    if found:
        return found

    exe = f"{name}.exe" if _IS_WIN else name
    for folder in _candidate_dirs(name):
        p = folder / exe
        if p.is_file():
            return str(p)
    return ""


# ── Notification ──────────────────────────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    """Best-effort desktop notification. Never raises — this is a nicety.

    Both strings can contain a video title, i.e. arbitrary text off the
    internet, so they are quoted for the target shell rather than interpolated
    raw.
    """
    if not NOTIFY:
        return

    def _clean(s: str) -> str:
        # Collapse to one line and drop control characters.
        return " ".join(str(s).split())[:200]

    try:
        if _IS_WIN:
            # PowerShell single-quoted strings are literal; '' is an escaped
            # quote. This also stops $ from interpolating.
            def _ps(s: str) -> str:
                return "'" + _clean(s).replace("'", "''") + "'"

            ps = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                "$n.Visible=$true;"
                f"$n.ShowBalloonTip(6000,{_ps(title)},{_ps(message)},'Info');"
                "Start-Sleep -Seconds 6;$n.Dispose()"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                timeout=20, **_QUIET,
            )
        else:
            def _as(s: str) -> str:
                return _clean(s).replace("\\", "").replace('"', "'")

            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{_as(message)}" with title "{_as(title)}"'],
                timeout=20,
            )
    except Exception:
        pass


# ── Download ──────────────────────────────────────────────────────────────────

def _build_command(url: str, ytdlp: str, ffmpeg: str, out_dir: Path) -> list:
    mode = str(AUDIO_MODE).strip().lower()
    if mode not in ("m4a", "flac", "mp3"):
        mode = "m4a"

    # Preferring the mp4a stream lets yt-dlp copy the audio straight out
    # instead of re-encoding it. Falls back to whatever is on offer.
    fmt = "bestaudio[acodec^=mp4a]/bestaudio/best" if mode == "m4a" else "bestaudio/best"

    cmd = [
        ytdlp,
        "--format", fmt,
        "--extract-audio",
        "--audio-format", mode,
        "--audio-quality", "0",
        "--embed-thumbnail",
        # YouTube serves WebP thumbnails, which will not embed into FLAC —
        # convert to JPEG first or the artwork silently goes missing.
        "--convert-thumbnails", "jpg",
        "--embed-metadata",
        "--no-embed-chapters",
        # Plain YouTube videos have no artist/track fields; fall back to the
        # uploader and video title so tags are never empty.
        "--parse-metadata", "%(artist,uploader)s:%(meta_artist)s",
        "--parse-metadata", "%(track,title)s:%(meta_title)s",
        "--parse-metadata", "%(album,playlist_title,title)s:%(meta_album)s",
        "--parse-metadata", "%(release_year,upload_date>%Y)s:%(meta_date)s",
        "--output", str(out_dir / FILENAME_FORMAT),
        "--no-overwrites",
        "--retries", "5",
        "--fragment-retries", "5",
        "--no-color",
        "--newline",
    ]

    if mode == "flac":
        cmd += ["--postprocessor-args", f"ffmpeg:-compression_level {COMPRESSION}"]
    if CLEAN_TAGS:
        # --embed-metadata otherwise writes the whole video description into the
        # file. Blanking a field only makes yt-dlp fall back to the next source,
        # so comment has to be overwritten with something non-empty to pin it.
        cmd += ["--parse-metadata", ":(?P<meta_synopsis>)",
                "--parse-metadata", "%(webpage_url)s:%(meta_comment)s"]
    if ffmpeg:
        cmd += ["--ffmpeg-location", str(Path(ffmpeg).parent)]
    if NO_PLAYLIST:
        cmd.append("--no-playlist")
    if SKIP_DUPLICATES:
        cmd += ["--download-archive", str(out_dir / ".downloaded.txt")]
    if SQUARE_COVER:
        cmd += ["--postprocessor-args",
                "ThumbnailsConvertor+ffmpeg_o:-vf crop=ih:ih"]

    cmd.append(url)
    return cmd


def _run_download(url: str, ytdlp: str, ffmpeg: str, out_dir: Path) -> None:
    """Runs on a worker thread so the ClipCommand UI stays responsive."""
    log_file = out_dir / "download.log"
    try:
        result = subprocess.run(
            _build_command(url, ytdlp, ffmpeg, out_dir),
            capture_output=True, text=True, **_QUIET,
        )
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp}  {url}  (exit {result.returncode}) =====\n")
            fh.write(result.stdout or "")
            fh.write(result.stderr or "")

        if result.returncode == 0:
            track = "Track downloaded"
            for line in reversed((result.stdout or "").splitlines()):
                if "Destination:" in line or "has already been downloaded" in line:
                    track = Path(line.split("Destination:")[-1].strip()).stem
                    break
            _notify("ClipCommand — FLAC ready", track)
        else:
            stderr = result.stderr or ""
            tail = stderr.strip().splitlines()
            reason = tail[-1] if tail else "See download.log"
            # YouTube changes its signature scheme regularly and a yt-dlp more
            # than a few months old fails this way rather than saying so.
            if any(s in stderr for s in ("No video formats found",
                                         "nsig extraction failed",
                                         "Signature extraction failed",
                                         "Please report this issue")):
                reason = "yt-dlp looks out of date — update it and retry."
            _notify("ClipCommand — download failed", reason)
    except Exception as exc:
        _notify("ClipCommand — download error", str(exc))
    finally:
        with _lock:
            _in_flight.discard(url)


# ── Transform ─────────────────────────────────────────────────────────────────

def transform(text: str) -> str:
    match = _YOUTUBE_URL.search(text or "")
    if not match:
        return text                      # not a YouTube link — leave it alone

    url = match.group(0).rstrip(".,);]'\"")

    ytdlp = _find_binary("yt-dlp", YTDLP_PATH)
    if not ytdlp:
        return (f"{TAG} yt-dlp not found. Install it "
                f"({'winget install yt-dlp.yt-dlp' if _IS_WIN else 'brew install yt-dlp'}) "
                f"or set YTDLP_PATH in transforms.ini.")

    ffmpeg = _find_binary("ffmpeg", FFMPEG_PATH)
    if not ffmpeg:
        return (f"{TAG} ffmpeg not found — required for FLAC conversion. Install it "
                f"({'winget install Gyan.FFmpeg' if _IS_WIN else 'brew install ffmpeg'}) "
                f"or set FFMPEG_PATH in transforms.ini.")

    out_dir = Path(OUTPUT_DIR).expanduser()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"{TAG} Cannot create {out_dir}: {exc}"

    with _lock:
        if url in _in_flight:
            return text if KEEP_URL else f"{TAG} Already downloading that URL."
        _in_flight.add(url)

    # Download off the GUI thread — transform() is called on it, and the
    # clipboard poller is blocked until we return.
    threading.Thread(
        target=_run_download, args=(url, ytdlp, ffmpeg, out_dir), daemon=True
    ).start()

    return text if KEEP_URL else f"{TAG} ⬇ Downloading to {out_dir} …"
