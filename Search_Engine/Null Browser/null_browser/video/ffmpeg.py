"""Finding ffmpeg and running the conversions.

Everything that touches a subprocess lives here so the rest of the code only sees bytes in, bytes out. ffmpeg is looked for, in order:
the `video_ffmpeg_path` setting, the NULL_FFMPEG environment variable, `ffmpeg` on PATH, and the binary shipped with the optional
`imageio-ffmpeg` package (`pip install imageio-ffmpeg`, which is what requirements.txt installs).
"""
import logging
import os
import re
import shutil
import subprocess
import threading
import time

log = logging.getLogger("null.video")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)          # no console window flashing up on Windows
MAX_INPUT = 48 * 1024 * 1024
MAX_FILE = 200 * 1024 * 1024
# Height steps used when this computer cannot convert as fast as the video plays (None = keep the source size)
LADDER = (None, 720, 540, 432, 360, 288)


def find(explicit=""):
    """Path of an ffmpeg executable, or ""."""
    for cand in (explicit, os.environ.get("NULL_FFMPEG", "")):
        if cand and os.path.isfile(cand):
            return cand
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return ""


def _run(args, timeout=15, data=None):
    return subprocess.run(args, input=data, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)


def inspect(exe):
    """{'version': str, 'vp9': bool, 'vp8': bool, 'opus': bool} for this ffmpeg (all False if it cannot run)."""
    out = {"version": "", "vp9": False, "vp8": False, "opus": False}
    try:
        text = _run([exe, "-hide_banner", "-encoders"]).stdout.decode("utf-8", "replace")
        out.update(vp9="libvpx-vp9" in text, vp8=bool(re.search(r"\blibvpx\b", text)), opus="libopus" in text)
        ver = _run([exe, "-version"]).stdout.decode("utf-8", "replace").splitlines()
        out["version"] = ver[0].replace("ffmpeg version", "").strip().split(" ")[0] if ver else ""
    except Exception:
        log.debug("ffmpeg inspection failed", exc_info=True)
    return out


def usable(caps):
    return bool(caps) and (caps.get("vp9") or caps.get("vp8")) and caps.get("opus")


class Transcoder:
    """Converts fragmented MP4 (H.264 / HEVC + AAC) into WebM (VP9 or VP8 + Opus) pieces a SourceBuffer accepts.

    It keeps an eye on how long a piece took against how long it plays and steps the picture size down (and back up) so playback
    never falls behind on a slow computer."""

    def __init__(self, exe, caps):
        self.exe, self.caps = exe, caps
        self.threads = max(1, min(4, (os.cpu_count() or 2)))
        self._lock = threading.Lock()
        self._step = 0
        self._slow = self._fast = 0
        self.stats = {"pieces": 0, "seconds_media": 0.0, "seconds_work": 0.0, "max_height": 0}

    @property
    def max_height(self):
        return LADDER[self._step]

    def _adapt(self, media_s, work_s):
        if media_s <= 0.2:
            return
        ratio = work_s / media_s
        with self._lock:
            self.stats["pieces"] += 1
            self.stats["seconds_media"] += media_s
            self.stats["seconds_work"] += work_s
            if ratio > 0.8:
                self._slow, self._fast = self._slow + 1, 0
                if self._slow >= 2 and self._step < len(LADDER) - 1:
                    self._step, self._slow = self._step + 1, 0
                    log.info("Video conversion is slow (%.2fx real time): limiting height to %s", ratio, LADDER[self._step])
            elif ratio < 0.3:
                self._fast, self._slow = self._fast + 1, 0
                if self._fast >= 6 and self._step > 0:
                    self._step, self._fast = self._step - 1, 0
            else:
                self._slow = self._fast = 0

    def _video_args(self):
        h = self.max_height
        scale = ["-vf", f"scale=-2:'min(ih,{h})':flags=fast_bilinear"] if h else []
        if self.caps.get("vp9"):
            return scale + ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1", "-crf", "33", "-b:v", "0",
                            "-lag-in-frames", "0", "-g", "240", "-threads", str(self.threads)]
        return scale + ["-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-crf", "10", "-b:v", "3M",
                        "-lag-in-frames", "0", "-g", "240", "-threads", str(self.threads)]

    def mse(self, init, fragments, video, audio, media_s=0.0):
        """init + fragments are the bytes the page appended (fMP4); returns WebM bytes (a header and clusters), or raises."""
        if len(init) + len(fragments) > MAX_INPUT:
            raise ValueError("segment too large")
        args = [self.exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "mp4", "-i", "pipe:0", "-copyts"]
        args += self._video_args() if video else ["-vn"]
        args += ["-c:a", "libopus", "-b:a", "128k", "-ar", "48000"] if audio else ["-an"]
        args += ["-f", "webm", "pipe:1"]
        t0 = time.perf_counter()
        p = _run(args, timeout=120, data=init + fragments)
        work = time.perf_counter() - t0
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError(p.stderr.decode("utf-8", "replace")[-300:] or f"ffmpeg exit {p.returncode}")
        if video:
            self._adapt(media_s, work)
        return p.stdout


_DUR = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_file(exe, path):
    """{'duration': seconds (0 if unknown), 'video': bool, 'audio': bool} for a media file."""
    p = _run([exe, "-hide_banner", "-i", path], timeout=30)          # exits non-zero without an output file: the report is on stderr
    text = p.stderr.decode("utf-8", "replace")
    m = _DUR.search(text)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    return {"duration": dur, "video": bool(re.search(r"Stream #\d+:\d+.*: Video:", text)) and "attached pic" not in text,
            "audio": bool(re.search(r"Stream #\d+:\d+.*: Audio:", text))}


def stream_file(tc, path, kind, on_chunk, stopped):
    """Convert one track kind ("video" or "audio") of a media file to WebM, calling on_chunk(bytes) as the output appears. Returns False if it was stopped or failed."""
    args = [tc.exe, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path]
    if kind == "video":
        args += tc._video_args() + ["-an"]
    else:
        args += ["-vn", "-c:a", "libopus", "-b:a", "128k", "-ar", "48000"]
    args += ["-f", "webm", "pipe:1"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    err = []
    threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True).start()
    try:
        while True:
            if stopped():
                proc.kill()
                return False
            data = proc.stdout.read(256 * 1024)
            if not data:
                break
            on_chunk(data)
        return proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
