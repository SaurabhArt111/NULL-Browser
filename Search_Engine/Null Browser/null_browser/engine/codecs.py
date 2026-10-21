"""What can this Qt WebEngine build decode?

The wheels from PyPI (PyQt6-WebEngine / PySide6) are built *without* proprietary codecs: no H.264, AAC or HEVC. VP9, AV1, Opus
and MP3 work. X (Twitter), Reddit, and most Instagram and Facebook videos are H.264/AAC, so on such an engine their players
show "something went wrong - try reloading" however many times you retry. That is a property of the engine build, not of a
page or a setting, so the browser checks once per start and says so instead of leaving the user guessing.

Qt's documentation: H.264 / MP3 playback needs Qt WebEngine configured with `-webengine-proprietary-codecs`.
"""
import json
import logging

log = logging.getLogger("null.codecs")

PROBE_JS = r"""(function(){
 var v=document.createElement('video'), ms=window.MediaSource;
 function ok(t){ return !!(ms && ms.isTypeSupported(t)) || v.canPlayType(t) !== ''; }
 return JSON.stringify({
  h264: ok('video/mp4; codecs="avc1.42E01E"'), aac: ok('audio/mp4; codecs="mp4a.40.2"'), hevc: ok('video/mp4; codecs="hvc1.1.6.L93.B0"'),
  vp9: ok('video/webm; codecs="vp9"'), av1: ok('video/mp4; codecs="av01.0.05M.08"'), opus: ok('audio/webm; codecs="opus"')});
})()"""

HOW_TO_FIX = (
    "Videos on X, Reddit, Instagram and Facebook are H.264 / AAC, which the Qt WebEngine build you installed cannot decode "
    "(YouTube and other VP9 / AV1 sites are not affected).\n\n"
    "Null Browser can play them anyway by converting them on the fly with ffmpeg (Settings -> Privacy and security -> Play H.264 video). "
    "That needs ffmpeg: run `pip install imageio-ffmpeg`, or install ffmpeg and put it on PATH. For native decoding you need a Qt WebEngine "
    "built with proprietary codecs (configure option -webengine-proprietary-codecs); see docs/VIDEO_CODECS.md.")


def probe(page, callback):
    """Run the probe on `page` (any loaded http(s)/about page) and call callback(dict)."""
    def done(raw):
        try:
            callback(json.loads(raw))
        except Exception:
            log.debug("codec probe failed", exc_info=True)
    page.runJavaScript(PROBE_JS, done)


def lacks_h264(report):
    return bool(report) and not report.get("h264")
