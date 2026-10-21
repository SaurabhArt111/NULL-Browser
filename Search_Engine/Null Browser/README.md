# Null Browser

A desktop browser in Python (PyQt6 + Qt WebEngine / Chromium) with a built-in ad blocker, privacy controls and an optional
linked Null Search Engine.

```
pip install -r requirements.txt          # optional: pip install -r requirements-optional.txt (Rust ad-block engine)
python main.py                           # options: --safe-mode, --private, --data-dir DIR, --new-instance
python -m unittest discover tests        # unit tests (no Qt needed)
QT_QPA_PLATFORM=offscreen python main.py --data-dir /tmp/nb --new-instance --selftest /tmp/nb-out   # 75 end-to-end checks
```

## Layout

```
main.py                       entry point (adds the package to the path)
null_browser/
  main.py                     start-up: flags, scheme registration, single-instance hand-over
  app.py                      BrowserApp: shared services and windows
    app_profiles.py           persistent / private web profiles
    app_session.py            save + restore windows and tabs
    app_policies.py           theme, page settings, per-site policy, permission shim, zoom
    app_instances.py          second launch -> running instance (local socket)
    app_data.py               clear browsing data, memory saver
  video/                      H.264 / AAC playback bridge (ffmpeg): shim.js in the page, service.py, ffmpeg.py
  engine/                     the Chromium side
    flags.py                  every Chromium switch, decided in one place
    codecs.py                 H.264 / AAC detection (see docs/VIDEO_CODECS.md)
  privacy/                    the ad blocker
    filters.py                list management, engine build (Rust / wheel / pure Python), compiled-engine cache
    sanitize.py               scriptlet policy applied to list text before any engine sees it
    interceptor.py            QWebEngineUrlRequestInterceptor (runs on Chromium's IO thread: keep it cheap)
    media_hosts.py            media CDNs that skip the filter engine
    cookies.py                third-party cookie policy with related-sites groups
    cosmetic.py               element hiding (stylesheet + MutationObserver, no polling)
    scriptlets.py, pyabp.py   scriptlet resources and the pure-Python engine
  core/                       settings, database, downloads, permissions, search, notifications, crash guard
  ui/
    window.py                 MainWindow (tabs, chrome state, actions)
      window_bookmarks.py  window_menus.py  window_frame.py  window_dragdrop.py
    tab.py                    Tab (signals, lifecycle, navigation)
      page.py  findbar.py  permission_bubble.py
      tab_menu.py  tab_devtools.py  tab_permissions.py  tab_tools.py
    omnibox.py  tabbar.py  popups.py  widgets.py  theme.py  icons.py  native.py  winframe.py  autoscroll.py
  web/                        null:// pages (settings, history, ...) and their JSON API
tests/                        unit tests
docs/VIDEO_CODECS.md          why some videos cannot play and what to do
```

Rules the layout follows: `privacy/` and `engine/` never import `ui/`; mixins hold behaviour, the class they are mixed into holds
state and signals; nothing in the request interceptor may block.

## What changed in this release

**Flicker and lag**
* Removed the colour veil that faded over the page on every tab switch.
* The load bar no longer appears/disappears (it used to resize the page area, causing a re-layout and repaint on every navigation:
  8 page resizes over 4 navigations before, 0 after).
* The page background colour is only re-applied when it actually changes.
* "Open in app" deep-link prompts only appear for real clicks / typed addresses, not for background redirects.
* GPU rasterisation is now really enabled (the old code only said it was) and the interpreter switches threads more often so the
  request interceptor cannot starve the UI thread.

**Ad blocking without breaking pages**
* `privacy/sanitize.py` cleans the filter lists once, for every engine: drops scriptlets that rewrite requests or timers on video / social
  sites, removes duplicates (the same rule arrived from two lists and ran twice), merges `json-prune` rules into one, and scopes
  response wrappers that used to run on every fetch. On the bundled lists: 44 dropped, 39 duplicates removed, 100 `json-prune`
  rules merged into 82, 72 generic-hide exceptions expanded. A Facebook-style `JSON.parse` benchmark is about 32x faster with the
  policy than with the raw rules. Turn it off in Settings -> "Keep video sites safe from scriptlets".
* Generic element hiding (class / id based) was silently dead on every site because the PyPI engine mis-read one Brave exception
  rule; it works now, and ads are hidden in about 50 ms after they appear.
* Media CDN requests skip the filter engine (see `privacy/media_hosts.py`); scripts and frames from those hosts are still filtered.
* The third-party cookie filter raised an exception on every call (and the error was swallowed); it works now and is memoised.
* The permission shim only patches what you explicitly blocked.

**Videos**
* Videos on X, Reddit, Instagram and Facebook are H.264 + AAC, which the PyPI Qt WebEngine cannot decode. New in this release: the
  **video bridge** converts them to VP9 + Opus with ffmpeg while you watch (`pip install imageio-ffmpeg`, then Settings -> Play H.264 video).
  See `docs/VIDEO_CODECS.md` for how it works and its limits.

**Native look**
* The crash guard that switches the Windows native frame (snap, resize, animations) off after a start that did not finish now does so for one start only and shows a
  "Turn on now" button; the earlier flag is reset by this release.

## Known limits

* H.264 / AAC: needs ffmpeg and CPU; see docs/VIDEO_CODECS.md.
* Windows-only visual behaviour (the native-frame hack, GPU drivers) could not be tested in the build environment; the self-test runs
  headless on Linux.
* `$removeparam` rules need the Rust engine from `requirements-optional.txt`.
