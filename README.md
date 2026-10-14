# Null Browser

A desktop browser with its own interface, its own built-in pages, its own permission system and ad blocker, and a
linked local search engine (Null Search). It is a rewrite of the earlier PyQt prototype, not a patch on it.

**What it is, honestly.** Pages are rendered by Chromium through Qt WebEngine, the same arrangement as
many other non-Google browsers. Writing a rendering engine from scratch is a multi-year, multi-hundred-engineer job and
was not attempted. Everything *around* the engine (tabs, address bar, history, bookmarks, downloads, settings, site
permissions, ad blocking, error handling, notifications, the search link) is Null Browser's own code.

## Quick start

| OS | Run |
|---|---|
| Windows | double-click **`setup_and_run.bat`** (first run: creates `.venv`, installs dependencies, starts the browser). Afterwards use **`run_browser.bat`**. |
| macOS / Linux | `python3 -m venv .venv && . .venv/bin/activate && pip install -r "Search_Engine/Null Browser/requirements.txt" -r "Search_Engine/Null Search Engine/requirements.txt" && python "Search_Engine/Null Browser/main.py"` |

Needs Python 3.10 or newer (3.12 / 3.13 recommended) and an internet connection for the first install. Setup installs prebuilt
packages only (nothing is compiled, so locked-down PCs work), and Null Search is optional: if its packages can't install,
setup counts a warning and the browser still starts. If something misbehaves, run
`python main.py --debug` (in `Search_Engine/Null Browser`) for verbose logging.

Command line: `main.py [URL ...] [--private] [--safe-mode] [--data-dir DIR] [--debug] [--new-instance]`.
`--data-dir` gives a portable profile.

## What's new in this version

- **Native window behaviour (Windows).** The frameless window is now a real Windows window underneath: Aero Snap, drag-to-restore from maximised,
  Snap Layouts on the maximise button (Windows 11), drop shadow, rounded corners, edge/corner resizing and the system open / minimise / maximise / close
  animations all behave like Chrome. If native set-up ever fails the old Qt-only edge handling is used automatically (`ui/winframe.py`).
- **Transitions.** New tabs slide open, switching tabs cross-fades, toolbar / tab-strip / window buttons fade their hover state, menus and tooltips ease in,
  and the built-in pages fade in. Pages no longer flash black before first paint (page background follows the theme / white like Chrome).
- **Smooth scrolling.** Chromium's eased scrolling and GPU rasterisation are switched on at start-up (Settings → System → *Smooth scrolling* / *graphics acceleration*; needs a restart).
- **Middle-click auto-scroll cursor.** The resize-arrow cursor is replaced with Chrome's round anchor icon and direction arrows (`ui/autoscroll.py`).
- **Diagnostics.** `Search_Engine\Null Browser\diagnose.bat` runs the browser in several configurations (clean profile and yours) and writes `diagnose_report.txt`.
- **Fail-safe.** If a start-up never finishes, the next start switches these window effects off automatically (and says so in an info bar) instead of
  looping into safe mode. `--enhanced` turns them back on, `--no-native-frame` keeps the animations but skips the Windows native frame.
  Native crashes are written to `logs/native-crash.log` in the data folder (the path is printed as `Data folder:` by `python main.py --debug`).
- **Resizing.** The bookmarks bar is rebuilt once when you stop dragging an edge instead of on every pixel.

- **Chrome-style window.** The title bar and tab strip are one: `[tab ×] [tab ×] [+]  …  [–] [▢] [✕]`. Drag the empty strip to move the window,
  double-click it to maximise, drag the edges to resize (Snap layouts and Aero-snap still work through the system move / resize).
- **Tab tear-off.** Drag a tab out of the strip and it becomes its own window that follows the cursor; drop it on another browser window's tab
  strip (a purple insertion marker shows where) to merge it back. Also *Move tab to new window* in the tab menu. Dragging the only tab moves the window.
- **Hover hints everywhere.** Every toolbar button, tab button, menu item and every control on the built-in pages has a tooltip with a name,
  the keyboard shortcut and a one-line suggestion.
- **Feather icons** (MIT, © Cole Bemis, https://feathericons.com) used consistently in the Qt UI and the built-in pages. Settings now has a proper gear; the sun is only the theme button.
- **Customisable New Tab** (`null://newtab`, *Customize* button): background (colour, gradient, or your own image), clock, greeting, search box style, shortcut grid
  (add / edit / remove / reorder, top sites), compact / glass cards. Saved in your profile.
- **Sign-ins are kept.** Cookies, local storage and site data persist across restarts until *you* clear them. *Clear browsing data* offers the
  Chrome time-range list and ticks only *Cached images and files* by default; cookies and site data are removed only when you tick them. (Settings → Privacy has a switch if you prefer memory-only cookies.)
- **Fixed:** `Unsafe attempt to load URL null://newtab/ … Domains, protocols and ports must match` in DevTools (the internal scheme no longer uses an opaque local origin).
- **Null Search rebuilt** — see below.

## What you get

**Built-in pages** (real web pages served from inside the browser on `null://`, so they have proper layout, search and
dark mode): `null://history`, `bookmarks`, `downloads`, `settings`, `about`, `version`, `logs`, `newtab`. Chrome-style
names also work: `chrome://settings`, `edge://history`, `about:settings`, and the address-bar shortcuts `@history foo`,
`@bookmarks foo`, `@settings`.

- **History** – grouped by day, search, per-item delete, multi-select, *Clear browsing data* with time range.
- **Bookmarks** – folders, bookmarks bar, edit dialog, import / export (Netscape HTML, compatible with Chrome/Edge/Brave/Firefox).
- **Downloads** – live progress, pause / resume / cancel, open file, show in folder, missing-file detection, dangerous-file warning, native completion notification.
- **Settings** – the sidebar structure of Chrome's settings, with search across all pages: You, Privacy and security, Site settings, Performance, Appearance, Search engine, Default browser, On startup, Languages, Downloads, Accessibility, System, Reset.
- **Developer tools** – the real Chromium DevTools (Elements, Console, Network, Sources, Performance) docked right / bottom or in its own window (`F12`, `Ctrl+Shift+I`, *Inspect* in the context menu), plus a rendered-DOM source viewer, remote-debugging port, and `null://logs`.

**Browser behaviour:** pinned / draggable tabs, audio indicators and mute, tab search, reopen closed tab, session restore,
Memory Saver (discards inactive tabs), per-site zoom, find in page, print / save as PDF, full-screen video, InPrivate
windows (separate off-the-record profile, dark purple theme, nothing written to disk), single-instance forwarding,
system-tray mode, a live Chrome-style omnibox (history, bookmarks, search suggestions, `@engine` shortcuts, `?` to force search).

**Ad & tracker blocking:** built-in, no extension needed. Shield button shows blocked count, with a per-site off switch and custom rules.
Sends *Do Not Track* and *Global Privacy Control*.

**Native feel:** Windows taskbar identity and dark title bar, system toast / Notification Center for downloads and for website
notifications you allowed, native print dialog, theme follows the OS dark-mode setting live.

## Search: Google, linked with Null Search

Google is the default address-bar engine. Null Search (`Search_Engine/Null Search Engine/`, see its own README) is linked in:

- The browser starts it in the background on launch and stops it on exit (Settings → Search engine → start / stop / port).
- Type **`@null query`** to use it for one search, **`@google`**, **`@ddg`**, **`@bing`**, **`@brave`** likewise, or pick any of them as the default. Add your own engine with `%s`.
- *Index my bookmarks in Null Search* crawls your bookmarked pages into its local index.
- Null Search is now a meta-search engine plus a personal full-text index (SQLite FTS5 / BM25): web results from DuckDuckGo and Wikipedia
  (optionally Brave, Google or SearxNG) fused with Reciprocal Rank Fusion, instant answers (calculator, units, time, colours, hashes), a Wikipedia knowledge panel,
  Images and News tabs, search operators, a polite SSRF-safe crawler, and a UI with dark mode. It is honest about its limits: it does not own a web-scale crawl.
- Null Search is optional. If it is stopped or unavailable, normal browsing and other search engines continue working; searches that would have used Null Search fall back to Google.

## Site permissions

All 38 settings from your list (plus a few Chromium extras) exist with exactly your defaults (Location / Camera / Microphone Ask, Motion sensors Allow,
Pop-ups Block, Automatic downloads Allow, …), each with a global default plus per-site exceptions
(`null://settings/content`, or the lock icon in the address bar). Ask prompts appear as a native bubble / dialog; decisions
are remembered per site (forgotten when private windows close).

Not every Chromium feature can be controlled from Qt, so each setting carries a badge saying how it is enforced:

| Badge | Meaning | Settings |
|---|---|---|
| Enforced | Qt asks the browser and Null Browser decides | Location, Camera, Microphone, Notifications, Clipboard, Fonts, Screen sharing, Cursor lock |
| Enforced | Applied through engine settings, request filtering or the cookie filter | JavaScript, Images, Pop-ups, Intrusive ads, Sound, Automatic downloads, Insecure content, Cookies, Autoplay |
| Enforced (API gate) | The JS API is removed (Block) or put behind a native prompt (Ask) before page scripts run | MIDI, USB, Serial, HID, File editing, Motion sensors, Background sync, Payment handlers, AR, VR, Hand tracking, Your device use, Window management, Auto picture-in-picture, Web app installations, Apps on device, Protected content IDs, Third-party sign-in |
| Applies after restart | Chromium command-line flag | JavaScript optimization & security |
| Saved only | Qt exposes no hook yet | Scrolling and zooming shared tabs, Local network |

The API gate works by wrapping or removing the page-visible JavaScript APIs, which is effective against ordinary sites but is not
a security boundary against deliberately hostile code. It is off in safe mode.

## Self error handling

- Every Python exception (main thread, worker threads, Qt slots) is logged, kept for `null://logs`, and shown as a small toast, never a crash.
- A burst of errors offers to restart in **safe mode**; three failed starts in a row enter safe mode automatically.
- Renderer crashes show an "Aw, Snap" page with Reload instead of a blank tab. Network, DNS, TLS and unsafe-port errors get explanatory pages; HTTPS-first upgrades fall back to HTTP only when the secure connection fails.
- Settings and database files that fail to load are moved aside (`*.corrupt-<time>`) and rebuilt, so a damaged profile can't stop startup.
- Native crashes write a traceback to `logs/native-crash.log`. Logs rotate in the data folder (Settings → System → *Open data folder*).

## Verification

`python main.py --selftest OUTDIR` launches the whole browser headless and runs 60+ end-to-end checks (internal pages render
with no JS errors, address-bar parsing, every shim gate with real prompts, permission persistence, ad blocking, pop-up
blocking, API-token protection, bookmarks, history, error pages, clean shutdown) and saves screenshots.
It runs against a throw-away profile; the last run in the Linux build environment passed 67 of 67 checks. Tab tear-off / merge, persistence of
cookies across restarts and the Clear-data semantics were verified with separate scripted runs (synthetic mouse events in an offscreen display, so real-mouse feel on Windows is untested).
The search engine has its own 64 pytest tests (`Null Search Engine/tests`).

**Not tested:** Windows and macOS. The code uses only cross-platform Qt APIs plus guarded Windows calls (taskbar ID, dark title
bar), but nobody has run it there yet. If the first launch fails, the output of `python main.py --debug` and `logs/null-browser.log` will show why.

## Known limits

- No extensions, password manager / autofill, account sync, translation, or Chrome's Live Caption.
- DRM-protected video (Netflix, Spotify web) needs Widevine, which Qt WebEngine builds don't ship, so those sites may refuse to play.
- Spell-check needs Qt's dictionary files installed separately.
- *Default browser* opens your OS's default-apps settings; the OS decides, no registry changes are made.

## Layout

```
setup_and_run.bat / .sh      one-time setup + launch          run_browser.bat / .sh   daily launcher
Search_Engine/
  Null Browser/
    main.py                  launcher
    null_browser/
      main.py  app.py        start-up, profiles, policies, session, tray
      core/                  db, settings, permissions, adblock, downloads, search, engine_service, notify, crash
      ui/                    window, tab, tabbar, tabdrag, omnibox, popups, tips, theme, icons, native
      web/                   null:// scheme handler, JSON API, pages/ and static/ for the built-in pages
      selftest.py            headless end-to-end test
  Null Search Engine/        FastAPI meta-search + FTS5 index + crawler + UI (see its README)
```
