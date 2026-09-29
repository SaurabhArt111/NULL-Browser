# Null Browser + Null Search Engine

A privacy-focused desktop browser (PyQt6 / QtWebEngine) with a companion
local search engine (FastAPI). This build focuses on making the *existing*
project actually work end-to-end, harden its error handling, and bring it
closer to Chrome/Brave/Edge in the areas you asked for.

## What's genuinely new/fixed in this pass

**Null Browser**
- Built-in ad & tracker blocker (`ui/adblock.py`) - blocks common ad/tracker
  domains and paths at the network-request level, with a shield button
  showing how many were blocked, a per-site allow-list, and a toggle in
  Settings → Privacy & Security.
- Popup blocker (blocks chrome-less `window.open()` popups, the kind ad
  scripts spawn), toggleable.
- Offline "New Tab" page (search box + bookmark tiles) so the browser is
  fully usable even if the search engine server isn't running - the old
  version hard-navigated to `localhost:8000` and broke if that wasn't up.
- Friendly error page on failed loads instead of a blank tab.
- Security/connection indicator (padlock/warning icon) next to the address
  bar based on the page's scheme.
- InPrivate/incognito windows now actually use an off-the-record
  QWebEngineProfile (in-memory cache, no persistent cookies, no history
  writes) instead of just changing the window title.
- "Clear browsing data" (Ctrl+Shift+Delete) that really clears cache,
  cookies, and history via QtWebEngine's profile APIs.
- Full keyboard shortcut set: Ctrl+T/W/N/Shift+N/Shift+T (reopen closed
  tab)/L/D/H/J/F/R/0/+/-, Alt+Left/Right, Ctrl+Tab, Alt+1-9, Ctrl+Shift+I
  (DevTools), etc. - de-duplicated so Qt doesn't treat any of them as
  "ambiguous".
- Bookmark bar under the address bar, movable/draggable tabs, a "+"
  corner button for new tabs, middle-click to close a tab, a subtle fade
  transition on tab switches and theme changes (Qt Widgets has no native
  CSS transitions, so this is done with QPropertyAnimation).
- 5 built-in themes (Light/Dark/Night/Brave/Ocean) plus a custom accent
  colour picker, applied via one shared stylesheet that also styles the
  bookmark bar.
- Downloads now go through the existing `DownloadManager` dialog
  (progress bars, open file/folder, clear) instead of a disconnected list
  that never actually showed progress.
- Removed a UI-freezing busy-loop that used to "simulate" load progress
  with a blocking `for` loop; replaced with a proper indeterminate
  progress bar.
- Defensive error handling throughout: a bad page load, a broken bookmark,
  a failed download, or a settings-file issue now shows a status-bar
  message instead of crashing the app.

**Null Search Engine**
- The FastAPI backend was a stub (hardcoded `["Result 1", "Result 2", ...]`)
  - it's now wired to a real TF-IDF inverted index and a polite,
    robots.txt-respecting crawler:
  - `GET /api/search?q=&limit=` - ranked results
  - `GET /api/suggest?q=` - autocomplete
  - `POST /api/crawl` - crawl a list of seed URLs into the index
  - `GET /api/stats`, `GET /api/crawl/status`
- The web UI's JavaScript (`app.js`/`search.js`/`storage.js`/`themes.js`/
  `voice.js`) declared clashing globals and, critically, **was never
  `<script>`-included by `index.html`** - the search box didn't do
  anything. Replaced with one consolidated `js/main.js` that actually
  wires up search, suggestions, theme switching, bookmarks, history, and
  settings, plus the missing CSS for results/suggestions/toasts.
- Fixed two duplicate `id="history-toggle"` / `id="bookmarks-toggle"`
  elements (a nav button and a settings checkbox shared the same id, so
  `getElementById` only ever found the button).
- Static file serving for `css/`/`js/`, safe (escaped) result rendering.

## Requirements & honesty about scope

This is **not** a from-scratch Chromium fork - "all the features of
Chrome/Brave/Edge" isn't achievable in one pass (those are multi-million
line codebases). What's delivered is a real, working PyQt6/QtWebEngine
browser shell (which already gives you Chromium's rendering engine, so
pages render exactly like they would in Chrome) with the browser-chrome
features listed above. Password/autofill storage, extensions, and sync are
not implemented.

The search engine indexes whatever you point its crawler at - it does not
ship with a pre-built index of "the internet". Point `/api/crawl` at a
handful of sites you care about, or use Google/Bing/DuckDuckGo from the
search-engine dropdown in the browser for general web search.

## Running it

### Search engine (optional but recommended)
```bash
cd "Search_Engine/Null Search Engine"
pip install -r requirements.txt
python src/main.py
# -> http://127.0.0.1:8000
```
Then, to build a starter index:
```bash
curl -X POST http://127.0.0.1:8000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"seeds": ["https://en.wikipedia.org/wiki/Web_browser"], "max_pages": 30}'
```

### Browser
```bash
cd "Search_Engine/Null Browser"
pip install -r requirements.txt
python src/main.py            # normal window
python src/main.py --private  # InPrivate window
```

The browser works fine with the search engine server stopped - it'll just
fall back to the offline New Tab page and tell you (in the status bar) if
you pick "Null Search" as your engine while the server's down.
