"""The video bridge: ffmpeg discovery, the worker pool and the object each page talks to (through QWebChannel)."""
import base64
import json
import ipaddress
import logging
import os
import socket
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QFile, QIODevice, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineScript

from . import ffmpeg

log = logging.getLogger("null.video")
SCRIPT_NAME = "null-video"
OBJECT_NAME = "nullVideo"
MAX_IN_FLIGHT = 6                      # per page: a page cannot queue unlimited work


def _qwebchannel_js():
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.OpenModeFlag.ReadOnly):
        try:
            return bytes(f.readAll()).decode("utf-8")
        finally:
            f.close()
    return ""


class PageBridge(QObject):
    """What a page sees as `nullVideo`. Slots return at once; results come back through `done`."""
    done = pyqtSignal(int, bool, str)
    progress = pyqtSignal(int, str, str)         # id, 'meta' | 'data' | 'end' | 'error', payload

    def __init__(self, service, page):
        super().__init__(page)
        self.svc = service
        self._busy = 0
        self._lock = threading.Lock()
        self._stop = set()
        self.destroyed.connect(self._gone)

    def _begin(self, rid):
        with self._lock:
            if self._busy >= MAX_IN_FLIGHT:
                self.done.emit(rid, False, "too many conversions in flight")
                return False
            self._busy += 1
            return True

    def _end(self):
        with self._lock:
            self._busy -= 1

    def _emit(self, rid, ok, payload):
        try:
            self.done.emit(rid, ok, payload)
        except RuntimeError:               # the page was closed while ffmpeg was still working
            pass

    @pyqtSlot(int, str, str, bool, bool, int)
    def mse(self, rid, init_b64, frag_b64, video, audio, millis):
        if not self._begin(rid):
            return
        self.svc.pool.submit(self._mse, rid, init_b64, frag_b64, video, audio, millis / 1000.0)

    def _mse(self, rid, init_b64, frag_b64, video, audio, seconds):
        try:
            out = self.svc.transcoder.mse(base64.b64decode(init_b64), base64.b64decode(frag_b64), video, audio, seconds)
            self._emit(rid, True, base64.b64encode(out).decode("ascii"))
        except Exception as e:
            log.warning("video conversion failed: %s", e)
            self._emit(rid, False, str(e)[:200])
        finally:
            self._end()

    # ---- whole files: <video src="clip.mp4"> -------------------------------------------------------------------
    @pyqtSlot(int, str, str, str)
    def prog(self, rid, url, referer, ua):
        if not self._begin_prog(rid):
            return
        self.svc.pool.submit(self._prog, rid, url, referer, ua)

    def _begin_prog(self, rid):
        with self._lock:
            if self._busy >= MAX_IN_FLIGHT:
                busy = True
            else:
                self._busy += 1
                busy = False
        if busy:
            self._send(rid, "error", "too many conversions in flight")
        return not busy

    def _gone(self, *_a):
        self._dead = True

    _dead = False

    @pyqtSlot(int)
    def cancel(self, rid):
        with self._lock:
            self._stop.add(rid)

    def _send(self, rid, kind, payload=""):
        try:
            self.progress.emit(rid, kind, payload)
        except RuntimeError:
            pass

    def _prog(self, rid, url, referer, ua):
        tmp = None
        try:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname or not _public_host(parts.hostname):
                raise ValueError("address not allowed")
            if not self.svc.allows(url, referer):
                raise ValueError("blocked by the ad blocker")
            req = urllib.request.Request(url, headers={"User-Agent": ua or "Mozilla/5.0", "Referer": referer or "", "Accept": "*/*"})
            opener = urllib.request.build_opener(_NoPrivateRedirect)
            fd, tmp = tempfile.mkstemp(prefix="null-video-", suffix=".bin")
            size = 0
            with os.fdopen(fd, "wb") as out, opener.open(req, timeout=20) as r:
                while True:
                    if rid in self._stop or self._dead:
                        return
                    data = r.read(256 * 1024)
                    if not data:
                        break
                    size += len(data)
                    if size > ffmpeg.MAX_FILE:
                        raise ValueError("file too large")
                    out.write(data)
            info = ffmpeg.probe_file(self.svc.exe, tmp)
            if not (info["video"] or info["audio"]):
                raise ValueError("no playable stream")
            self._send(rid, "meta", json.dumps(info))
            results = {}

            def run(kind):
                results[kind] = ffmpeg.stream_file(self.svc.transcoder, tmp, kind,
                                                   lambda b: self._send(rid, kind, base64.b64encode(b).decode("ascii")), lambda: rid in self._stop or self._dead)
            kinds = [k for k in ("video", "audio") if info[k]]
            threads = [threading.Thread(target=run, args=(k,), daemon=True) for k in kinds]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            if rid not in self._stop:
                ok = all(results.get(k) for k in kinds)
                self._send(rid, "end" if ok else "error", "" if ok else "conversion failed")
        except Exception as e:
            log.warning("video file conversion failed: %s", e)
            self._send(rid, "error", str(e)[:200])
        finally:
            with self._lock:
                self._busy -= 1
                self._stop.discard(rid)
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass


ALLOW_PRIVATE = False                  # tests only: the self-test serves its media from 127.0.0.1


def _public_host(host):
    """False for anything that resolves to this computer or a private network (a page must not use us to probe those)."""
    if ALLOW_PRIVATE:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


class _NoPrivateRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname or ""
        if urllib.parse.urlsplit(newurl).scheme not in ("http", "https") or not _public_host(host):
            raise urllib.error.URLError("redirect to a non-public address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class VideoService:
    """Owns ffmpeg and the pool. `enabled` is false (and nothing is exposed to pages) unless the setting is on and ffmpeg works."""

    def __init__(self, settings):
        self.settings = settings
        self.exe, self.caps, self.transcoder = "", {}, None
        self.pool = ThreadPoolExecutor(max_workers=max(2, min(3, (os.cpu_count() or 2))), thread_name_prefix="null-video")
        self._js = None
        self.adblock = None                 # set by the app: used to apply the ad-block rules to files fetched on a page's behalf
        self.safe = False
        self.refresh()

    def refresh(self):
        self.exe = ffmpeg.find(self.settings.get("video_ffmpeg_path") or "")
        self.caps = ffmpeg.inspect(self.exe) if self.exe else {}
        self.transcoder = ffmpeg.Transcoder(self.exe, self.caps) if ffmpeg.usable(self.caps) else None
        if self.transcoder:
            log.info("Video bridge ready: ffmpeg %s (%s), VP9=%s, threads=%d", self.caps.get("version"), self.exe, self.caps.get("vp9"), self.transcoder.threads)
        else:
            log.info("Video bridge unavailable: %s", self.reason())

    def reason(self):
        if not self.exe:
            return "ffmpeg not found (pip install imageio-ffmpeg)"
        if not ffmpeg.usable(self.caps):
            return "this ffmpeg has no VP8/VP9 + Opus encoder"
        return ""

    @property
    def enabled(self):
        return bool(self.settings.get("video_transcode")) and self.transcoder is not None and not self.safe

    def info(self):
        return {"on": bool(self.settings.get("video_transcode")), "ready": self.transcoder is not None, "ffmpeg": self.exe,
                "version": self.caps.get("version", ""), "reason": self.reason(), "stats": dict(self.transcoder.stats) if self.transcoder else {}}

    def allows(self, url, page_url):
        """Would the ad blocker let this page load this media file? (We fetch it ourselves, so the interceptor never sees it.)"""
        try:
            return self.adblock is None or self.adblock.allows_fetch(url, page_url)
        except Exception:
            return True

    def script_source(self):
        if self._js is None:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "shim.js"), encoding="utf-8") as f:
                shim = f.read()
            self._js = "(function(){\n" + _qwebchannel_js() + "\n;" + shim + "\n})();" if _qwebchannel_js() else ""
        return self._js

    def install_script(self, profile):
        coll = profile.scripts()
        for sc in coll.find(SCRIPT_NAME):
            coll.remove(sc)
        src = self.script_source() if self.enabled else ""
        if not src:
            return
        sc = QWebEngineScript()
        sc.setName(SCRIPT_NAME)
        sc.setSourceCode(src)
        sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        sc.setRunsOnSubFrames(True)
        coll.insert(sc)

    def attach(self, page):
        """Expose the bridge to `page` (or take it away again when the feature is off)."""
        world = QWebEngineScript.ScriptWorldId.MainWorld
        if not self.enabled:
            if getattr(page, "_null_video", None):
                page.setWebChannel(None, world)
                page._null_video = None
            return
        if getattr(page, "_null_video", None):
            return
        bridge = PageBridge(self, page)
        channel = QWebChannel(page)
        channel.registerObject(OBJECT_NAME, bridge)
        page.setWebChannel(channel, world)
        page._null_video = (bridge, channel)
