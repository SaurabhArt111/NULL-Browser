# Videos on X, Reddit, Instagram and Facebook (H.264 / AAC)

## The problem

Null Browser shows web pages with **Qt WebEngine** (Chromium). The `PyQt6-WebEngine` package from PyPI is built **without
proprietary codecs**, so it cannot decode **H.264 video or AAC audio**. Qt's documentation says native support needs a build
configured with `-webengine-proprietary-codecs` (<https://doc-snapshots.qt.io/qtwebengine/qtwebengine-features.html>).

| Site | Video format | Plays natively with the pip build? |
|---|---|---|
| YouTube | VP9 / AV1 + Opus | yes |
| X / Twitter, Reddit, Instagram, Facebook, Twitch, many others | H.264 + AAC | no: the player shows "try again" |

## What Null Browser does: the video bridge (`null_browser/video/`)

When the engine cannot decode H.264 and **ffmpeg** is available, Null Browser converts the video while you watch it:

* A small script (`video/shim.js`) runs in each page. It tells the site's player that H.264 / AAC are supported. The player (hls.js,
  dash.js, Shaka and the sites' own players all use *Media Source Extensions*) then hands every fragment it downloads to the
  browser, which converts it with ffmpeg to **VP9 + Opus** and gives it back to the real video element. Pieces are
  converted as they arrive, a few times faster than real time on a normal computer.
* Plain `<video src="clip.mp4">` files (X "GIFs", Reddit fallback videos ...) are downloaded by the browser, checked against the
  ad-block lists, converted and streamed to the element while the conversion runs.
* Pages talk to the browser through Qt's web channel, so the sites' Content-Security-Policy is not involved. A page cannot make the
  browser fetch addresses on your own computer or network (those are refused), at most 6 conversions per page run at once, and
  nothing is exposed to pages when the setting is off or ffmpeg is missing.
* If this computer cannot convert as fast as the video plays, the picture size is stepped down automatically (720 -> 540 -> 432 ... pixels high) and
  raised again when there is spare time.

### Setting it up

1. `pip install imageio-ffmpeg` (it is in `requirements.txt`; the package ships an ffmpeg program), **or** install ffmpeg yourself and put it on PATH,
   **or** set the `NULL_FFMPEG` environment variable / the `video_ffmpeg_path` setting to the executable.
   The ffmpeg must include the `libvpx-vp9` (or `libvpx`) and `libopus` encoders; the common builds do.
2. Settings -> Privacy and security -> **Play H.264 video** (on by default). Reload open pages after changing it.

### Limits (please read)

* It uses CPU while a video plays (software VP9 encoding). On a slow computer it drops to a smaller picture.
* The first seconds of a video start a little later than on a native build, and quality is slightly below the original.
* DRM-protected video (Netflix, Prime Video ...) is not touched.
* Frames inside an iframe only work if the browser exposes the web channel to that frame; embedded players in other sites may
  still show "try again".
* It was tested against hls.js (MPEG-TS HLS), dash.js, Shaka Player, raw Media Source use and plain mp4 files with generated
  H.264 / AAC streams. It could not be tested against the live X / Reddit / Instagram / Facebook sites; they change their players often.

## Native decoding instead

Build Qt WebEngine with `-webengine-proprietary-codecs` and install the matching PyQt6-WebEngine against it, or use a distribution package
that ships it. H.264 / AAC are patent-encumbered; licensing is your responsibility. After switching builds the start-up check passes and
the bridge steps aside by itself (the shim does nothing when the engine can already decode H.264).

## Checking by hand

In DevTools (F12) on any page:

```js
MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E"')   // true with the bridge or a native build
```
The log line `Media codecs: {...}` and `Video bridge ready: ffmpeg ...` at start-up show what was detected.
