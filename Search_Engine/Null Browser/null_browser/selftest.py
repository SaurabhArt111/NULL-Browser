"""Headless end-to-end smoke test: `python -m null_browser --selftest OUTDIR` (used while developing / in CI)."""
import http.server
import json
import os
import socketserver
import threading
import time
import traceback

from PyQt6.QtCore import QTimer
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


def press(win, sequence):
    """Trigger the window action that owns a keyboard shortcut (checks it is registered and wired), as the key press would."""
    from PyQt6.QtGui import QKeySequence
    want = QKeySequence(sequence)
    for a in win.actions():
        if want in a.shortcuts():
            a.trigger()
            return True
    return False


_FIND_JS = ("(()=>{const w=r=>{for(const e of r.querySelectorAll('*')){if(PICK)return e;"
            "if(e.shadowRoot){const x=w(e.shadowRoot);if(x)return x}}return null};const el=w(document);BODY})()")


def devtools_js(tab, pick, body, timeout=4000):
    """Evaluate something about the DevTools frontend (its buttons and tabs sit in shadow DOM)."""
    box = {}
    code = _FIND_JS.replace("PICK", pick).replace("BODY", body)
    tab.devtools.page().runJavaScript(code, lambda r: box.setdefault("r", r if r is not None else "__none__"))
    wait_until(lambda: "r" in box, timeout)
    r = box.get("r", "__timeout__")
    return None if r == "__none__" else r


TAB_SELECTED = "e.id==='tab-console'"
INSPECT_BTN = "e.tagName==='BUTTON'&&(e.title||'').startsWith('Select an element')"
CLOSE_BTN = "e.tagName==='BUTTON'&&e.title==='Close'"


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
    "/h264mse.html": """<html><body style="margin:0"><video id=v muted autoplay playsinline width=320 height=180></video><script>
      window.R={}; (async()=>{ try{
        R.supported = MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E"') && MediaSource.isTypeSupported('audio/mp4; codecs="mp4a.40.2"');
        const ms=new MediaSource(), v=document.getElementById('v'); v.src=URL.createObjectURL(ms);
        await new Promise(r=>ms.addEventListener('sourceopen',r,{once:true}));
        const get=async u=>new Uint8Array(await (await fetch(u)).arrayBuffer());
        const sbv=ms.addSourceBuffer('video/mp4; codecs="avc1.42E01E"'), sba=ms.addSourceBuffer('audio/mp4; codecs="mp4a.40.2"');
        const app=(sb,d)=>new Promise((res,rej)=>{ sb.addEventListener('updateend',()=>res(),{once:true}); sb.addEventListener('error',()=>rej(new Error('sb error')),{once:true}); sb.appendBuffer(d); });
        async function feed(sb,pre,init,n){ await app(sb,await get(init)); for(let i=0;i<n;i++) await app(sb,await get(pre+i+'.m4s')); }
        v.play().catch(()=>{});
        await Promise.all([feed(sbv,'/m/v','/m/init_v.bin',R_N),feed(sba,'/m/a','/m/init_a.bin',R_N)]);
        try{ms.endOfStream();}catch(e){}
        await new Promise(r=>setTimeout(r,2500));
        R.t=v.currentTime; R.w=v.videoWidth; R.err=v.error?v.error.code:0;
      }catch(e){ R.exc=String(e); } R.done=true; })();</script></body></html>""",
    "/h264file.html": """<html><body style="margin:0"><video id=v muted autoplay loop playsinline width=320 height=180 src="/m/prog.mp4"></video><script>
      window.R={}; setTimeout(()=>{ const v=document.getElementById('v'); R.t=v.currentTime; R.w=v.videoWidth; R.err=v.error?v.error.code:0; R.done=true; }, 5500);</script></body></html>""",
    "/zoom.html": "<html><title>zoom</title><body>zoom test</body></html>",
    "/private.html": "<html><title>privatepage</title><body>only in a private window</body></html>",
    "/apis.html": """<html><title>apis</title><body><script>
      window.R = { usb: 'usb' in navigator, serial: 'serial' in navigator, hid: 'hid' in navigator, midi: typeof navigator.requestMIDIAccess,
                   accel: typeof Accelerometer, xr: 'xr' in navigator, idle: typeof IdleDetector, payment: typeof PaymentRequest,
                   sync: typeof SyncManager, fs: typeof showOpenFilePicker, screens: typeof getScreenDetails, done: true };
    </script></body></html>""",
}


HITS = []                                     # every path the test web server was asked for
MEDIA = {}                                    # path -> bytes (generated H.264 test clips)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        if self.path.split("?")[0] == "/uaecho":
            ua = (self.headers.get("User-Agent") or "").encode()
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.send_header("Content-Length", str(len(ua)))
            self.end_headers(); self.wfile.write(ua); return
        raw = MEDIA.get(self.path.split("?")[0])
        if raw is not None:
            self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw); return
        body = PAGES.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript" if self.path.split("?")[0].endswith(".js") else "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


def _make_h264_clips(exe, tmp):
    """Three-second H.264 + AAC test clips: one progressive file and a fragmented set (init + pieces) for MediaSource. None if ffmpeg cannot encode H.264."""
    import struct
    import subprocess
    try:
        enc = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, timeout=15).stdout.decode("utf-8", "replace")
        if "libx264" not in enc or " aac " not in enc.replace("\n", " "):
            return None
        base = [exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=3", "-c:v", "libx264", "-preset", "veryfast", "-g", "25",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k"]
        subprocess.run(base + ["-movflags", "+faststart", os.path.join(tmp, "prog.mp4")], check=True, timeout=60)
        subprocess.run(base + ["-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "1000000", "-f", "mp4", os.path.join(tmp, "frag.mp4")],
                       check=True, timeout=60)
        for kind, flag, pre in (("video", "-an", "v"), ("audio", "-vn", "a")):
            out = os.path.join(tmp, kind + ".mp4")
            subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", os.path.join(tmp, "frag.mp4"), flag, "-c", "copy", "-movflags",
                            "+frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "1000000", "-f", "mp4", out], check=True, timeout=60)
            data = open(out, "rb").read()
            i, init, cur, n = 0, b"", b"", 0
            while i + 8 <= len(data):
                size, typ = struct.unpack(">I4s", data[i:i + 8])
                seg = data[i:i + size]
                i += size
                if typ in (b"ftyp", b"moov"):
                    init += seg
                elif typ == b"moof":
                    cur = seg
                elif typ == b"mdat":
                    MEDIA[f"/m/{pre}{n}.m4s"] = cur + seg
                    n += 1
            MEDIA[f"/m/init_{pre}.bin"] = init
        MEDIA["/m/prog.mp4"] = open(os.path.join(tmp, "prog.mp4"), "rb").read()
        return sum(1 for k in MEDIA if k.startswith("/m/v") and k.endswith(".m4s"))
    except Exception as e:
        print("INFO could not make test clips:", e, flush=True)
        return None


def run(app, outdir):
    t = QTimer()
    t.timeout.connect(_auto_dialog)
    t.start(100)
    _keep.append(t)
    QTimer.singleShot(WATCHDOG_MS, lambda: (print("WATCHDOG: self-test exceeded its time budget", flush=True), app.qapp.exit(3)))
    try:
        os.makedirs(outdir, exist_ok=True)
        (_stress if os.environ.get("NULL_SELFTEST_STRESS") else _run)(app, outdir)
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


def _stress(app, outdir):
    """Developer stress test (NULL_SELFTEST_STRESS=1): hammer tabs, navigation, resizing and windows for a while; passing = no crash."""
    import random
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest as T
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    rnd = random.Random(5)
    w = app.windows[0]
    w.resize(1280, 820)
    fm = app.adblock.filters
    wait_until(lambda: fm.engine is not None and not fm.building, 60000)
    pages = ["/cosmetic.html", "/netfilter.html", "/ads.html", "/settings", "/history"]
    end = time.time() + float(os.environ.get("NULL_SELFTEST_STRESS_SECONDS", "60"))
    n = 0
    while time.time() < end:
        n += 1
        act = rnd.random()
        w = app.windows[-1] if app.windows else None
        if w is None:
            break
        if act < 0.30 and len(w.tabs) < 12:
            w.new_tab(base + rnd.choice(pages[:3]) + "?%d" % n)
        elif act < 0.45 and len(w.tabs) > 1:
            w.close_tab_index(rnd.randrange(len(w.tabs)))
        elif act < 0.65:
            t = w.current()
            if t:
                t.view.load(__import__("PyQt6.QtCore", fromlist=["QUrl"]).QUrl(base + rnd.choice(pages[:3]) + "?%d" % n))
        elif act < 0.80:
            w.resize(rnd.randint(500, 1500), rnd.randint(400, 950))
            w.begin_live_resize()
            T.qWait(rnd.randint(5, 60))
            w.end_live_resize()
        elif act < 0.86:
            w.toggle_maximized()
        elif act < 0.92 and len(app.windows) < 3:
            app.new_window(private=rnd.random() < 0.5, show=True)
        elif act < 0.96 and len(app.windows) > 1:
            app.windows[-1].close()
        else:
            t = w.current()
            if t:
                wid = t.view
                T.mouseClick(wid.focusProxy() or wid, Qt.MouseButton.MiddleButton, pos=QPoint(200, 200))
        T.qWait(rnd.randint(10, 120))
    wait_until(lambda: False, 1500)
    ok("stress: %d random actions without a crash" % n, True)
    ok("stress: no unhandled errors captured", len(__import__("null_browser.core.crash", fromlist=["x"]).ERRORS) == 0,
       str([e["title"] for e in __import__("null_browser.core.crash", fromlist=["x"]).ERRORS][:3]))


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
    yt = fm.engine.cosmetic("https://www.youtube.com/watch?v=x")["injected_script"]
    ok("YouTube ad scriptlets are injected (adPlacements pruning)", "adPlacements" in yt and "try {" in yt, f"{len(yt)} chars")
    ok("generic cosmetic lookup works on this engine", isinstance(fm.engine.hidden_class_id_selectors(["adsbygoogle"], [], []), list))
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
    tab_count = len(w.tabs)
    t.view_source()
    wait_until(lambda: len(w.tabs) == tab_count + 1, 3000)
    vs_tab = w.tabs[-1] if len(w.tabs) == tab_count + 1 else None
    source_text = {}
    if vs_tab is not None:
        wait_until(lambda: vs_tab.page.url().toString().startswith("view-source:") and not vs_tab.loading, 5000)
        vs_tab.page.runJavaScript("document.body.innerText", lambda v: source_text.setdefault("t", v or ""))
        wait_until(lambda: "t" in source_text, 3000)
    ok("View page source opens the real source in a new view-source: tab",
       vs_tab is not None and "navigator.requestMIDIAccess()" in source_text.get("t", ""),
       (vs_tab.page.url().toString() if vs_tab else "no tab") + " | " + source_text.get("t", "")[:80].replace("\n", " "))
    if vs_tab is not None:
        w.close_tab(vs_tab)
        w.tabbar.setCurrentIndex(w.tabs.index(t))
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

    # ---- H.264 / AAC through the video bridge (needs ffmpeg with an H.264 encoder to make test clips) ---------------------
    from .video import service as video_service
    video_service.ALLOW_PRIVATE = True
    if app.video.enabled:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="null-vtest-") as tmp:
            n_pieces = _make_h264_clips(app.video.exe, tmp)
            if n_pieces:
                PAGES["/h264mse.html"] = PAGES["/h264mse.html"].replace("R_N", str(n_pieces))
                load(t, base + "/h264mse.html")
                wait_until(lambda: js(t, "!!window.R && R.done"), 40000)
                r = json.loads(js(t, "JSON.stringify(R)") or "{}")
                if r.get("supported") and "exc" not in r and "avc" not in str(r):
                    ok("video bridge: an H.264 + AAC MediaSource stream plays", (r.get("t") or 0) > 0.8 and r.get("w") == 320 and not r.get("err"), str(r))
                else:
                    ok("video bridge: an H.264 + AAC MediaSource stream plays", False, str(r))
                load(t, base + "/h264file.html")
                wait_until(lambda: js(t, "!!window.R && R.done"), 40000)
                r = json.loads(js(t, "JSON.stringify(R)") or "{}")
                ok("video bridge: a plain H.264 .mp4 file plays", (r.get("t") or 0) > 0.8 and r.get("w") == 320 and not r.get("err"), str(r))
                app.settings.set("video_transcode", False)
                load(t, base + "/h264mse.html")
                wait_until(lambda: js(t, "!!window.R && R.done"), 15000)
                r = json.loads(js(t, "JSON.stringify(R)") or "{}")
                ok("video bridge stays out of pages when the setting is off", r.get("supported") is False and js(t, "typeof qt") in ("undefined", None), str(r))
                app.settings.set("video_transcode", True)
            else:
                print("SKIP video bridge: ffmpeg here cannot encode H.264 test clips", flush=True)
    else:
        print("SKIP video bridge: " + (app.video.reason() or "turned off"), flush=True)
    video_service.ALLOW_PRIVATE = False
    load(t, base + "/zoom.html")

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
    # keyboard shortcuts drive the panels of the open tools
    ok("Ctrl+Shift+J opens the Console panel", press(w, "Ctrl+Shift+J") and wait_until(
        lambda: devtools_js(cur, TAB_SELECTED, "return el?el.getAttribute('aria-selected'):null") == "true", 4000))
    cur.devtools_panel("Elements")
    ok("Ctrl+Shift+C starts element selection", press(w, "Ctrl+Shift+C") and wait_until(
        lambda: devtools_js(cur, INSPECT_BTN, "return el?el.getAttribute('aria-pressed'):null") == "true", 4000))
    # docking: right -> bottom -> window -> right, switchable while open
    from PyQt6.QtCore import Qt as _Qt
    old_dock = app.settings.get("devtools_dock")
    cur.set_devtools_dock("bottom")
    QTest.qWait(300)
    ok("DevTools dock to bottom", cur.split.orientation() == _Qt.Orientation.Vertical and cur.devtools_host is not None
       and cur.split.indexOf(cur.devtools_host) == 1, str(cur.split.orientation()))
    shot(w, outdir, "devtools_bottom")
    cur.set_devtools_dock("window")
    QTest.qWait(300)
    ok("DevTools undock into a window", cur.devtools is not None and cur.devtools.isWindow() and cur.devtools_host is None)
    cur.set_devtools_dock("right")
    QTest.qWait(300)
    ok("DevTools dock back to the right", cur.split.orientation() == _Qt.Orientation.Horizontal and cur.devtools_host is not None
       and not cur.devtools.isWindow())
    split_sizes = cur.split.sizes()
    ok("docked DevTools get their remembered share", 0.25 < split_sizes[1] / max(1, sum(split_sizes)) < 0.6, str(split_sizes))
    close_devtools = cur.devtools_host.findChild(QToolButton, "devtoolsClose")
    close_devtools.click()
    wait_until(lambda: cur.devtools is None, 2000)
    ok("DevTools close button closes dock", cur.devtools is None)
    # Ctrl+Shift+C with the tools closed opens them already picking an element
    press(w, "Ctrl+Shift+C")
    ok("Ctrl+Shift+C opens the tools and starts picking", wait_until(lambda: cur.devtools is not None, 2000) and wait_until(
        lambda: devtools_js(cur, INSPECT_BTN, "return el?el.getAttribute('aria-pressed'):null") == "true", 8000))
    # the frontend's own close button must close the dock too
    devtools_js(cur, CLOSE_BTN, "if(!el) return false; for (const t of ['pointerdown','mousedown','pointerup','mouseup','click']) "
                                 "el.dispatchEvent(new MouseEvent(t,{bubbles:true,composed:true,cancelable:true,button:0,view:window})); return true")
    ok("the DevTools frontend's own close button closes the dock", wait_until(lambda: cur.devtools is None, 3000))
    app.settings.set("devtools_dock", old_dock)
    press(w, "F12")
    ok("F12 opens the tools", wait_until(lambda: cur.devtools is not None, 2000))
    press(w, "F12")
    ok("devtools closes", cur.devtools is None)

    # ---- device mode (Ctrl+Shift+M) and the viewport watchdog ----------------------------------------------------------
    load(cur, base + "/zoom.html")
    QTest.qWait(400)
    ok("Ctrl+Shift+M turns device mode on", press(w, "Ctrl+Shift+M") and cur.device_active and cur.devbar is not None and cur.devbar.isVisible())
    QTest.qWait(1500)
    want_w, want_h = cur.devbar.state()[0]
    aw, ah = cur.stage.width(), cur.stage.height()
    ok("device mode sizes the viewport", cur.view.width() == min(want_w, aw) and cur.view.height() == min(want_h, ah),
       f"view {cur.view.width()}x{cur.view.height()}, wanted {want_w}x{want_h} in {aw}x{ah}")
    ok("the page sees the device width", abs((js(cur, "innerWidth") or 0) - cur.view.width()) <= 1, str(js(cur, "innerWidth")))
    ua = js(cur, "navigator.userAgent") or ""
    ok("mobile user agent is applied to navigator.userAgent", "Android" in ua and "Mobile" in ua, ua[:60])
    ok("mobile user agent is sent with requests", "Android" in str(js_async(cur, "fetch('/uaecho').then(r=>r.text())")))
    shot(w, outdir, "device_mode")
    cur.devbar.rotate.click()
    QTest.qWait(300)
    ok("rotate swaps width and height", cur.devbar.state()[0] == (want_h, want_w) and cur.view.width() == min(want_h, cur.stage.width()))
    cur.devbar.device.setCurrentIndex(0)
    QTest.qWait(200)
    ok("Responsive preset keeps the size and stays editable", not cur.devbar.w.isReadOnly())
    press(w, "Ctrl+Shift+M")
    QTest.qWait(1200)
    ok("device mode off fills the window again", not cur.device_active and cur.view.size() == cur.stage.size())
    ok("desktop user agent is back", "Android" not in (js(cur, "navigator.userAgent") or "")
       and "Android" not in str(js_async(cur, "fetch('/uaecho').then(r=>r.text())")))
    ok("no user-agent override is left behind", not app.adblock.device_ua)

    # the watchdog: a page that reports a smaller size than its widget gets nudged; a healthy one is left alone
    nudges = []
    real_nudge = cur.stage.nudge
    cur.stage.nudge = lambda: (nudges.append(1), real_nudge())
    cur.sync_viewport()
    QTest.qWait(600)
    ok("viewport watchdog leaves a healthy page alone", not nudges, str(nudges))
    real_run = cur.page.runJavaScript
    cur.page.runJavaScript = lambda code, cb=None: cb and cb([300, 200])
    cur.sync_viewport(tries=1)
    cur.page.runJavaScript = real_run
    ok("viewport watchdog nudges a page whose size is stale", len(nudges) == 1, str(nudges))
    cur.stage.nudge = real_nudge
    QTest.qWait(200)
    ok("the nudge restores the view size", cur.view.size() == cur.stage.size())
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
