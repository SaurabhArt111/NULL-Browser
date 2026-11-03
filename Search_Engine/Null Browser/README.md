# Null Browser

A desktop browser in Python (PyQt6 + Qt WebEngine / Chromium) with a built-in ad blocker, privacy controls and an optional
linked Null Search Engine.

```
pip install -r requirements.txt          # optional: pip install -r requirements-optional.txt (Rust ad-block engine)
python main.py                           # options: --safe-mode, --private, --data-dir DIR, --new-instance
python -m unittest discover tests        # unit tests (no Qt needed)
QT_QPA_PLATFORM=offscreen python main.py --data-dir /tmp/nb --new-instance --selftest /tmp/nb-out   # ~150 end-to-end checks
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
    app_accounts.py           Google sign-in that survives "Clear browsing data"
    app_pwa.py                installed web apps: install, update, shortcuts, uninstall
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
    vpn.py  vpn_qt.py         built-in VPN (proxy tunnel) and its Qt-side leak protection
    accounts.py  cookie_keeper.py   Google identity + the cookie mirror behind "stay signed in"
    pwa.py                    manifest parsing, scope rules, update fingerprints, app store
  ui/
    window.py                 MainWindow (tabs, chrome state, actions)
      window_bookmarks.py  window_menus.py  window_frame.py  window_dragdrop.py
    tab.py                    Tab (signals, lifecycle, navigation)
      page.py  findbar.py  permission_bubble.py
      tab_menu.py  tab_devtools.py  tab_permissions.py  tab_tools.py
    omnibox.py  tabbar.py  popups.py  widgets.py  theme.py  icons.py  native.py  winframe.py  autoscroll.py
    window_apps.py            profile button, VPN button, "Install app" chip, Apps menu
    pwa_window.py  pwa_install.py   window of an installed web app and its install dialog
  web/                        null:// pages (settings, history, ...) and their JSON API
tests/                        unit tests
docs/VIDEO_CODECS.md          why some videos cannot play and what to do
```

Rules the layout follows: `privacy/` and `engine/` never import `ui/`; mixins hold behaviour, the class they are mixed into holds
state and signals; nothing in the request interceptor may block.

## What is new in 3.1

**Look and feel**
* Original icon set (93 icons, `tools/gen_icons.py`) and a new app logo; no third-party icon geometry is used any more.
* Tab strip rewritten: Chrome-shaped tabs, the selected tab is always drawn on top, dragging follows the pointer and the other
  tabs glide out of the way, tabs press-select instantly, middle-click closes.
* Bookmarks bar: drag to reorder (an accent line shows where it lands), drop a link on it to bookmark it, Ctrl+click / middle-click
  open a background tab, Shift+click a new window, folder menus with "Open all", rename / delete folders, "Bookmark all tabs…".
* Mouse: Back / Forward open a history list on right-click or hold, middle-click opens the target in a new tab, Shift/Ctrl+click on
  Reload reloads without the cache, middle-click on Home opens it in a new tab.
* **Auto-scroll** (middle button) is drawn by the page itself with its own cursor. Chromium's native one showed Windows' vertical
  resize arrows; the new one shows a disc with arrows, scrolls up / down / sideways, farther = faster, and ends on click, key or wheel.

**Google account (browser level)**
* Sign in once (profile button, top right, or Settings -> Google account). The identity is kept in `account.json`, outside the web
  profile, and "Clear browsing data" / "Clear on exit" delete every cookie *except* Google's sign-in cookies, so you stay signed in.
  Switch that off in Settings -> Google account. This is not Chrome Sync: nothing is uploaded.

**VPN**
* Settings -> VPN: add a SOCKS5 / HTTP / HTTPS proxy, press Test, turn it on (the browser restarts and brings your tabs back).
  Web pages, downloads, WebSockets, DNS and Qt's own requests use the tunnel; WebRTC is limited to it; if the server dies pages fail
  instead of going out directly. Servers are not included: use your provider's endpoint, Tor, or `ssh -D 1080 user@host`.

**Apps (PWA)**
* "Install" chip in the address bar (or Menu -> Apps) opens a site in its own window with its own profile and storage, desktop /
  Start-menu shortcut, theme colour, scope-aware links (outside links open in the browser) and update checks (manifest changes are
  applied; "Update now" also drops the cache and updates service workers). Clearing browsing data never touches installed apps.
  Launch from a shortcut with `python main.py --app <id>`.

**Share nothing**
* Settings -> Privacy -> "Share nothing with anyone" (on by default) switches off Chromium's background connections (update checks,
  safe browsing pings, crash/usage reports, DNS prefetch, sync, domain reliability). Search suggestions and ad-list updates are off by
  default. The user agent no longer carries a Null Browser token.

**One tab per built-in page**
* History, Bookmarks, Downloads, Settings, About, Version and Logs open in one tab only. Using the menu, a shortcut, a link on another
  built-in page or the address bar switches to the tab that already has it (Settings sections reuse the Settings tab and navigate it).

**Google sign-in compatibility**
* Google may answer "This browser or app may not be secure" to an embedded browser. For Google's own sites only, the browser now
  announces the Chrome brand (request header + `navigator.userAgentData`) and provides `window.chrome`
  (`engine/google_compat.py`, switch in Settings -> Google account). This could not be tested against Google from the build
  environment and Google may still refuse.

**Limits you should know about**
* Qt WebEngine cannot load Chrome extensions or the Chrome Web Store, and there is no Chrome Sync service.
* The VPN is a browser-only proxy tunnel, not a system VPN, and needs a server from you. Chromium cannot authenticate to SOCKS5.
* H.264 sites (X, Reddit, Instagram, Facebook) still need the ffmpeg bridge (`pip install imageio-ffmpeg`).
* The Windows-only pieces (native frame, `.lnk` shortcuts) could not be run in the Linux test environment.

## What changed in 3.0

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
