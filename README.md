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
| macOS / Linux | `./setup_and_run.sh` the first time, then `./run_browser.sh` |

Needs Python 3.10 or newer (3.12 / 3.13 recommended) and an internet connection for the first install. Setup installs prebuilt
packages only (nothing is compiled, so locked-down PCs work), and Null Search is optional: if its packages can't install,
setup counts a warning and the browser still starts. If something misbehaves, run
`run_browser_debug.bat` for a console with verbose logging.

Command line: `main.py [URL ...] [--private] [--safe-mode] [--data-dir DIR] [--debug] [--new-instance]`.
`--data-dir` gives a portable profile.

## What you get

**Built-in pages** (real web pages served from inside the browser on `null://`, so they have proper layout, search and
dark mode): `null://history`, `bookmarks`, `downloads`, `settings`, `about`, `version`, `logs`, `newtab`. Chrome-style
names also work: `chrome://settings`, `edge://history`, `about:settings`, and the address-bar shortcuts `@history foo`,
`@bookmarks foo`, `@settings`.

- **History** – grouped by day, search, per-item delete, multi-select, *Clear browsing data* with time range.
- **Bookmarks** – folders, bookmarks bar, edit dialog, import / export (Netscape HTML, compatible with Chrome/Edge/Brave/Firefox).
- **Downloads** – live progress, pause / resume / cancel, open file, show in folder, missing-file detection, dangerous-file warning, native completion notification.
- **Settings** – the sidebar structure of Chrome's settings, with search across all pages: You, Privacy and security, Site settings, Performance, Appearance, Search engine, Default browser, On startup, Languages, Downloads, Accessibility, System, Reset.
- **Developer tools** – the real Chromium DevTools (Elements, Console, Network, Sources, Performance) docked right / bottom or in its own window (`F12`, `Ctrl+Shift+I`, *Inspect* in the context menu), plus view-source, remote-debugging port, and `null://logs`.

**Browser behaviour:** pinned / draggable tabs, audio indicators and mute, tab search, reopen closed tab, session restore,
Memory Saver (discards inactive tabs), per-site zoom, find in page, print / save as PDF, full-screen video, InPrivate
windows (separate off-the-record profile, dark purple theme, nothing written to disk), single-instance forwarding,
system-tray mode, a live Chrome-style omnibox (history, bookmarks, search suggestions, `@engine` shortcuts, `?` to force search).

**Ad & tracker blocking:** built-in, no extension needed. Shield button shows blocked count, with a per-site off switch and custom rules.
Sends *Do Not Track* and *Global Privacy Control*.

**Native feel:** Windows taskbar identity and dark title bar, system toast / Notification Center for downloads and for website
notifications you allowed, native print dialog, theme follows the OS dark-mode setting live.

## Search: Google, linked with Null Search

Google is the default address-bar engine. Null Search (`Null Search Engine/`, the FastAPI project you already had)
is linked in:

- The browser starts it in the background on launch and stops it on exit (Settings → Search engine → start / stop / port).
- Type **`@null query`** to use it for one search, **`@google`**, **`@ddg`**, **`@bing`**, **`@brave`** likewise, or pick any of them as the default. Add your own engine with `%s`.
- *Index my bookmarks in Null Search* crawls your bookmarked pages into its index.
- If the server is down or its Python packages are missing, nothing breaks: the browser keeps working and the New Tab page and Settings say why.

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
It runs against a throw-away profile; the last run in the Linux build environment passed 63 of 63 checks (2 more were skipped because they
need a real display or network).

**Not tested:** Windows and macOS. The code uses only cross-platform Qt APIs plus guarded Windows calls (taskbar ID, dark title
bar), but nobody has run it there yet. If the first launch fails, `run_browser_debug.bat` output and `logs/null-browser.log` will show why.

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
      ui/                    window, tab, tabbar, omnibox, popups, theme, icons, native
      web/                   null:// scheme handler, JSON API, pages/ and static/ for the built-in pages
      selftest.py            headless end-to-end test
  Null Search Engine/        FastAPI + TF-IDF index + crawler (unchanged apart from a configurable port)
```
