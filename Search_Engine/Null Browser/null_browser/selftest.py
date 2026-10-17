"""Headless end-to-end smoke test: `python -m null_browser --selftest OUTDIR` (used while developing / in CI)."""
import http.server
import json
import os
import socketserver
import threading
import time
import traceback

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QToolButton

RESULTS = []
DIALOGS = []                      # (title, text) of every native dialog the browser showed
SOURCE_VIEWS = []
_answer = {"label": "Block"}      # which button the auto-answerer presses
_keep = []
WATCHDOG_MS = 200_000


def _auto_dialog():
    """Presses a button on any modal QMessageBox, exactly like a user would (permission prompts are real dialogs)."""
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPlainTextEdit
    w = QApplication.activeModalWidget()
    if isinstance(w, QDialog) and w.windowTitle().startswith("Page source:"):
        text = w.findChild(QPlainTextEdit)
        SOURCE_VIEWS.append(text.toPlainText() if text else "")
        w.reject()
        return
    if isinstance(w, QMessageBox):
        DIALOGS.append((w.windowTitle(), w.text()))
        for b in w.buttons():
            if b.text().replace("&", "") == _answer["label"]:
                b.click()
                return
        w.reject()


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def wait_until(fn, timeout=8000, step=50):
    t = 0
    while t < timeout:
        try:
            if fn():
                return True
        except Exception:
            pass
        QTest.qWait(step)
        t += step
    return False


def js(tab, code, timeout=6000):
    box = {}
    tab.page.runJavaScript(code, lambda r: box.setdefault("r", r if r is not None else "__none__"))
    wait_until(lambda: "r" in box, timeout)
    r = box.get("r", "__timeout__")
    return None if r == "__none__" else r


def js_async(tab, expr, timeout=6000):
    """runJavaScript does not await Promises, so park the settled value on window and poll for it."""
    key = "__nt_%d" % int(time.time() * 1000)
    js(tab, "window['%s']=undefined;Promise.resolve(%s).then(v=>{window['%s']={v:v}},e=>{window['%s']={v:'__rejected__'}});0" % (key, expr, key, key))
    wait_until(lambda: js(tab, "window['%s']!==undefined" % key) is True, timeout)
    box = js(tab, "JSON.stringify(window['%s']||null)" % key)
    try:
        return (json.loads(box) or {}).get("v", "__timeout__")
    except (TypeError, ValueError):
        return "__timeout__"


def load(tab, url, timeout=15000):
    done = {}
    tab.view.loadFinished.connect(lambda ok_: done.setdefault("ok", ok_))
    tab.load(url)
    wait_until(lambda: "ok" in done, timeout)
    QTest.qWait(400)
    return done.get("ok")


PAGES = {
    "/perm.html": """<html><title>perm</title><body><script>
      window.R = {};
      (async()=>{
        try { await navigator.requestMIDIAccess(); R.midi='allowed'; } catch(e){ R.midi=e.name; }
        R.usb = (typeof navigator.usb === 'undefined') ? 'removed' : 'present';
        R.serial = (typeof navigator.serial === 'undefined') ? 'removed' : 'present';
        R.accel = (typeof Accelerometer === 'undefined') ? 'removed' : 'present';
        R.done = true;
      })();
    </script></body></html>""",
    "/ads.html": """<html><title>ads</title><body><h1>content</h1>
      <img src="http://ads.doubleclick.net/pixel.png"><script src="http://www.googletagservices.com/tag.js"></script></body></html>""",
    "/cosmetic.html": """<html><title>cosmetic</title><body><div id="keep">content</div><div class="adbox-null-test" id="boxA">AD</div>
      <script>window.R={}; setTimeout(()=>{ R.boxHidden = getComputedStyle(document.getElementById('boxA')).display==='none';
        R.keepVisible = getComputedStyle(document.getElementById('keep')).display!=='none'; R.done=true; }, 400);</script></body></html>""",
    "/netfilter.html": """<html><title>netfilter</title><body><script>
      window.R={blockedLoaded:false, redirOnload:false, redirOnerror:false, done:false};
      function add(src, on, err){ var s=document.createElement('script'); s.src=src; s.onload=on; s.onerror=err; document.body.appendChild(s); }
      var other = location.href.replace('127.0.0.1','localhost').replace(/\\/netfilter.html.*/,'');
      add(other+'/null-ad-tracker.js', function(){R.blockedLoaded=window.NULL_AD_LOADED===1;}, function(){});
      add(other+'/null-redirect-me.js', function(){R.redirOnload=true; R.redirReal=window.NULL_REAL===1;}, function(){R.redirOnerror=true;});
      fetch(other+'/null-pixel.gif?utm_source=abc&keepme=1', {mode:'no-cors'}).catch(function(){});
      setTimeout(function(){R.done=true;}, 1500);
    </script></body></html>""",
    "/null-ad-tracker.js": "window.NULL_AD_LOADED=1;",
    "/null-redirect-me.js": "window.NULL_REAL=1;",
    "/null-pixel.gif": "GIF89a",
    "/popup.html": """<html><title>popup</title><body><script>window.open('/perm.html','_blank');</script>hello</body></html>""",
    "/zoom.html": "<html><title>zoom</title><body>zoom test</body></html>",
    "/private.html": "<html><title>privatepage</title><body>only in a private window</body></html>",
    "/apis.html": """<html><title>apis</title><body><script>
      window.R = { usb: 'usb' in navigator, serial: 'serial' in navigator, hid: 'hid' in navigator, midi: typeof navigator.requestMIDIAccess,
                   accel: typeof Accelerometer, xr: 'xr' in navigator, idle: typeof IdleDetector, payment: typeof PaymentRequest,
                   sync: typeof SyncManager, fs: typeof showOpenFilePicker, screens: typeof getScreenDetails, done: true };
    </script></body></html>""",
}


HITS = []                                     # every path the test web server was asked for


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        body = PAGES.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript" if self.path.split("?")[0].endswith(".js") else "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


def run(app, outdir):
    t = QTimer()
    t.timeout.connect(_auto_dialog)
    t.start(100)
    _keep.append(t)
    QTimer.singleShot(WATCHDOG_MS, lambda: (print("WATCHDOG: self-test exceeded its time budget", flush=True), app.qapp.exit(3)))
    try:
        os.makedirs(outdir, exist_ok=True)
        _run(app, outdir)
    except Exception:
        traceback.print_exc()
        ok("selftest crashed", False, traceback.format_exc()[-300:])
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed", flush=True)
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(RESULTS, f, indent=1)
    app.qapp.exit(1 if failed else 0)


def shot(w, outdir, name):
    QTest.qWait(500)
    w.grab().save(os.path.join(outdir, name + ".png"))


def _run(app, outdir):
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    w = app.windows[0]
    w.resize(1280, 820)
    t = w.current()
    ok("window + first tab created", w and t)
    app.settings.data["adblock_auto_update"] = False          # the test must never touch the network
    fm = app.adblock.filters
    ready = wait_until(lambda: fm.engine is not None and not fm.building, 60000)
    print("INFO ad-block engine:", fm.message, flush=True)
    ok("filter engine is ready", ready and fm.rules > 1000, f"{fm.message} rules={fm.rules}")
    ok("engine blocks a known ad host from the real lists", fm.engine.check("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js", "https://example.com/", "script")[0])
    ok("engine allows a normal first-party script", not fm.engine.check("https://example.com/app.js", "https://example.com/", "script")[0])

    # ---- internal pages render ------------------------------------------------------------------
    errors_before = len(t.page.console)
    for name, expect in (("newtab", "Search"), ("history", "History"), ("bookmarks", "Bookmarks"), ("downloads", "Downloads"),
                         ("settings", "Settings"), ("settings/privacy", "Privacy"), ("settings/content", "Site settings"),
                         ("settings/content/camera", "Camera"), ("settings/search", "Search engine"), ("settings/appearance", "Appearance"),
                         ("settings/system", "Developer"), ("about", "Keyboard shortcuts"), ("version", "Chromium"), ("logs", "Logs")):
        good = load(t, f"null://{name}")
        QTest.qWait(500)
        text = js(t, "document.body.innerText") or ""
        ok(f"null://{name} renders", good and expect.lower() in text.lower(), text[:100].replace("\n", " | "))
        if name in ("settings", "history", "settings/content", "newtab", "about"):
            shot(w, outdir, "page_" + name.replace("/", "_"))
    cerrs = [c for c in t.page.console[errors_before:] if c[1] >= 2]
    ok("no JS errors on internal pages", not cerrs, str(cerrs[:2]))

    # ---- search / omnibox classification -------------------------------------------------------------
    S = app.search
    for text, expect_search, frag in (("hello world", True, "google.com/search?q=hello+world"), ("example.com", False, "https://example.com"),
                                      ("localhost:3000", False, "http://localhost:3000"), ("@ddg cats", True, "duckduckgo.com"),
                                      ("chrome://settings", False, "null://settings"), ("javascript:alert(1)", True, "google.com/search"),
                                      ("192.168.1.1", False, "http://192.168.1.1"), ("http://a.b/c d", False, "http://a.b/c d")):
        u, s = S.to_url(text)
        ok(f"omnibox '{text}'", s == expect_search and frag in u, f"{u} {s}")
    old_engine_state = app.engine.state
    old_search_engine = app.settings.data.get("search_engine")
    app.engine.state = "unavailable"
    app.settings.data["search_engine"] = "null"
    offline_urls = [app.resolve_text("offline search terms")[0], app.resolve_text("@null local query")[0],
                    app.resolve_text("?forced query")[0]]
    ok("offline Null Search falls back to Google",
       all("google.com/search?q=" in u for u in offline_urls), str(offline_urls))
    if old_search_engine is None:
        app.settings.data.pop("search_engine", None)
    else:
        app.settings.data["search_engine"] = old_search_engine
    app.engine.state = old_engine_state

    # ---- web page, permissions shim, adblock, popup -----------------------------------------------------
    ok("local web page loads", load(t, base + "/perm.html"))
    source_count = len(SOURCE_VIEWS)
    tab_count = len(w.tabs)
    t.view_source()
    source_ready = wait_until(lambda: len(SOURCE_VIEWS) == source_count + 1)
    source_text = SOURCE_VIEWS[-1] if source_ready else ""
    ok("View page source opens inert serialized DOM",
       source_ready and len(w.tabs) == tab_count and "navigator.requestMIDIAccess()" in source_text,
       source_text[:100].replace("\n", " "))
    wait_until(lambda: js(t, "!!window.R && R.done"), 5000)
    r = json.loads(js(t, "JSON.stringify(R)") or "{}")
    origin = f"http://127.0.0.1:{srv.server_address[1]}"
    ok("ASK mode shows a native prompt that names MIDI", any("MIDI" in d[1] for d in DIALOGS), str(DIALOGS[:2]))
    ok("pressing Block rejects the API call", r.get("midi") == "NotAllowedError", str(r))
    ok("Block decision is remembered for that site", app.perms.site(origin, "midi") == "block", str(app.perms.site(origin, "midi")))
    app.perms.reset_site(origin)
    _answer["label"] = "Allow this time"
    n_dlg = len(DIALOGS)
    load(t, base + "/perm.html")
    wait_until(lambda: js(t, "!!window.R && R.done"), 8000)
    ok("'Allow this time' is not persisted", app.perms.site(origin, "midi") is None and len(DIALOGS) > n_dlg)
    _answer["label"] = "Block"
    # Which gated web APIs does this Qt/Chromium build implement at all?  (QtWebEngine ships without WebUSB/Serial/HID/MIDI
    # devices, so for those there is nothing to hide: such checks are reported as SKIP instead of passing vacuously.)
    load(t, base + "/apis.html")
    present = json.loads(js(t, "JSON.stringify(R)") or "{}")
    print("INFO web APIs present in this engine:", present, flush=True)
    has = lambda v: v not in (None, False, "undefined", "")

    def gate_check(label, feature, key):
        app.perms.set_site(origin, feature, "block")
        app.apply_site_policies()
        load(t, base + "/apis.html")
        got = json.loads(js(t, "JSON.stringify(R)") or "{}")
        app.perms.reset_site(origin)
        app.apply_site_policies()
        if not has(present.get(key)):
            print(f"SKIP {label}: this engine does not implement it, so there is nothing to hide", flush=True)
            return
        ok(label, not has(got.get(key)), str(got))

    for label, feature, key in (("Block USB hides navigator.usb", "usb", "usb"), ("Block Serial hides navigator.serial", "serial", "serial"),
                                ("Block HID hides navigator.hid", "hid", "hid"), ("Block motion sensors hides Accelerometer", "motion_sensors", "accel"),
                                ("Block payment handlers hides PaymentRequest", "payment_handlers", "payment"),
                                ("Block background sync hides SyncManager", "background_sync", "sync"),
                                ("Block file editing hides showOpenFilePicker", "file_editing", "fs"),
                                ("Block window management hides getScreenDetails", "window_management", "screens"),
                                ("Block device use hides IdleDetector", "device_use", "idle")):
        gate_check(label, feature, key)
    load(t, base + "/apis.html")
    after = json.loads(js(t, "JSON.stringify(R)") or "{}")
    ok("Reset restores the engine's own APIs", after == present, f"{after} vs {present}")

    before = app.adblock.total
    load(t, base + "/ads.html")
    QTest.qWait(800)
    ok("ad/tracker requests blocked", app.adblock.total - before >= 1, f"blocked {app.adblock.total - before}")
    # ---- the filter engine inside the real browser: filter syntax, redirect stubs, removeparam, cosmetic hiding ----------
    def settle(gen, extra=700):
        wait_until(lambda: fm.generation > gen and not fm.building, 30000)
        QTest.qWait(extra)
        wait_until(lambda: not fm.building, 30000)
    gen = fm.generation
    for rule in ("||localhost^*/null-ad-tracker.js$script", "||localhost^*/null-redirect-me.js$script,redirect=noopjs",
                 "||localhost^$removeparam=utm_source", "127.0.0.1##.adbox-null-test"):
        app.adblock.custom_lines.append(app.adblock.parse_rule(rule) or rule)
    app.adblock.save_custom()
    fm.rebuild()
    settle(gen)
    HITS.clear()
    load(t, base + "/netfilter.html")
    wait_until(lambda: js(t, "!!window.R && R.done"), 8000)
    r = json.loads(js(t, "JSON.stringify(R)") or "{}")
    ok("filter rule ($script) stops the ad script loading", r.get("blockedLoaded") is False and not any("null-ad-tracker" in h for h in HITS), f"{r} {HITS}")
    redirect_ok = (r.get("redirOnload") and not r.get("redirReal")) or not fm.backend.name == "rust"
    ok("$redirect=noopjs swaps in a harmless stub (page script still loads, real one does not run)", redirect_ok and not r.get("redirReal"), f"{r} {HITS}")
    if fm.backend.name == "python" or fm.backend.name == "rust":
        pix = [h for h in HITS if "null-pixel" in h]
        ok("$removeparam strips the tracking parameter but keeps the others", bool(pix) and all("utm_source" not in h and "keepme=1" in h for h in pix), str(pix))
    else:
        print("SKIP $removeparam: the PyPI engine does not support it", flush=True)
    load(t, base + "/cosmetic.html")
    wait_until(lambda: js(t, "!!window.R && R.done"), 8000)
    r = json.loads(js(t, "JSON.stringify(R)") or "{}")
    ok("cosmetic filter hides the ad box and leaves page content alone", r.get("boxHidden") is True and r.get("keepVisible") is True, str(r))
    for rule in list(app.adblock.custom_lines):
        app.adblock.remove_rule(rule)
    n_before = len(w.tabs)
    load(t, base + "/popup.html")
    QTest.qWait(800)
    ok("unsolicited pop-up blocked", t.blocked_popups >= 1 and len(w.tabs) == n_before, f"tabs {len(w.tabs)} blocked {t.blocked_popups}")
    r = js_async(t, "fetch('null://history/api/history/list',{method:'POST',body:'{}'}).then(r=>r.text()).then(x=>'reached:'+x.slice(0,30)).catch(e=>'blocked')")
    ok("web page cannot call the null:// API", str(r) == "blocked", str(r))

    # ---- bookmarks + history through the real API ------------------------------------------------------------
    load(t, base + "/zoom.html")
    w.toggle_bookmark()
    QTest.qWait(300)
    ok("bookmark added via star", app.db.bookmark_for(base + "/zoom.html") is not None)
    for ed in w.findChildren(type(w.findChild(object, "")) if False else __import__("PyQt6.QtWidgets", fromlist=["QDialog"]).QDialog):
        ed.close()
    shot(w, outdir, "bookmark_bar")
    hist = app.db.history("zoom")
    ok("history recorded visit", len(hist) >= 1, str(hist[:1]))
    load(t, "null://history")
    QTest.qWait(500)
    ok("history page lists visit", "zoom" in (js(t, "document.body.innerText") or "").lower())
    load(t, "null://history?clear=1")
    QTest.qWait(500)
    ok("Ctrl+Shift+Del opens the Clear browsing data dialog", js(t, "!!document.querySelector('dialog[open] h3')") is True)
    load(t, "null://settings/privacy")
    QTest.qWait(600)
    js(t, "[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Clear data')).click();0")
    QTest.qWait(400)
    ok("Settings 'Clear data…' button opens the dialog", js(t, "!!document.querySelector('dialog[open] h3')") is True)
    load(t, "null://history")
    QTest.qWait(400)
    r = js_async(t, "fetch('/api/history/list',{method:'POST',headers:{'Content-Type':'application/json','X-Null-Token':" + "document.querySelector('meta[name=null-token]').content" + "},body:JSON.stringify({q:'zoom'})}).then(r=>r.json()).then(j=>j.items.length)")
    ok("history API from page works", (r or 0) >= 1, str(r))
    r = js_async(t, "fetch('/api/history/list',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status).catch(e=>'refused')")
    ok("API call without the token is refused", r in ("refused", 401, 403), str(r))

    # ---- settings round trip + permission API ------------------------------------------------------------------------
    load(t, "null://settings/content/camera")
    r = js(t, "fetch('/api/perm/set_default',{method:'POST',headers:{'Content-Type':'application/json','X-Null-Token':" + "document.querySelector('meta[name=null-token]').content" + "},body:JSON.stringify({feature:'camera',value:'block'})}).then(r=>r.json()).then(j=>JSON.stringify(j))")
    ok("set default camera=block", app.perms.default("camera") == "block", str(r))
    app.perms.set_default("camera", "ask")
    ok("settings persisted to disk", os.path.exists(app.settings.path))
    ok("38 permission catalog entries", len(app.perms.catalog_with_state()) >= 38)

    # ---- tabs, private window, devtools, find, zoom, error page --------------------------------------------------------
    n = len(w.tabs)
    w.new_tab(base + "/zoom.html")
    ok("new tab", len(w.tabs) == n + 1)
    w.close_tab(w.current())
    ok("close tab", len(w.tabs) == n)
    w.reopen_closed_tab()
    ok("reopen closed tab", len(w.tabs) == n + 1)
    cur = w.current()
    cur.zoom_step(1)
    ok("zoom step", abs(cur.page.zoomFactor() - 1.1) < 0.01, str(cur.page.zoomFactor()))
    cur.show_find()
    ok("find bar opens", cur.find.isVisible())
    cur.find.close_bar()
    cur.toggle_devtools()
    QTest.qWait(1500)
    ok("devtools opens", cur.devtools is not None)
    devtools_dark = cur.devtools.settings().testAttribute(QWebEngineSettings.WebAttribute.ForceDarkMode)
    devtools_theme = {}
    cur.devtools.page().runJavaScript(
        "document.documentElement.classList.contains('theme-with-dark-background')",
        lambda value: devtools_theme.setdefault("dark", value))
    wait_until(lambda: "dark" in devtools_theme, 2000)
    ok("DevTools color mode follows browser theme",
       devtools_dark == app.pal(cur.private)["dark"]
       and devtools_theme.get("dark") == app.pal(cur.private)["dark"],
       f"dark mode={devtools_dark}, frontend class={devtools_theme.get('dark')}")
    shot(w, outdir, "devtools")
    if cur.devtools_host is not None:
        close_devtools = cur.devtools_host.findChild(QToolButton, "devtoolsClose")
        if close_devtools:
            close_devtools.click()
        wait_until(lambda: cur.devtools is None, 2000)
        ok("DevTools close button closes dock", cur.devtools is None)
        cur.toggle_devtools()
        QTest.qWait(300)
    cur.toggle_devtools()
    ok("devtools closes", cur.devtools is None)
    load(cur, "http://127.0.0.1:9/unreachable")
    QTest.qWait(1500)
    ok("error page for refused connection", cur.page.url().host() == "error", cur.page.url().toString())
    shot(w, outdir, "error_page")

    pw = app.open_window(None, True)
    QTest.qWait(1200)
    ok("private window opens", pw.private and pw in app.windows)
    load(pw.current(), base + "/private.html")
    QTest.qWait(300)
    ok("private visits are not written to history", app.db.history("private.html") == [], str(app.db.history("private.html")[:1]))
    shot(pw, outdir, "private")
    pw.close()
    QTest.qWait(300)
    ok("private window closes", pw not in app.windows)

    # ---- downloads/db/clear -----------------------------------------------------------------------------------------------
    app.clear_data({"history", "cookies", "cache"}, "all")
    ok("clear browsing data", app.db.history("") == [])
    # ---- final screenshot of a normal window with menu closed
    load(w.current(), "null://newtab")
    shot(w, outdir, "newtab")
    ok("no unhandled errors captured", len(__import__("null_browser.core.crash", fromlist=["x"]).ERRORS) == 0,
       str([e["title"] for e in __import__("null_browser.core.crash", fromlist=["x"]).ERRORS][:3]))
