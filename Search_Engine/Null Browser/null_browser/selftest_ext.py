"""Self-test section for the features added in 3.1 (auto-scroll, accounts, PWA, VPN, privacy). Called from selftest._run."""
from PyQt6.QtTest import QTest
from PyQt6.QtWebEngineCore import QWebEngineScript

APP_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld

LONG = ("<html><title>long</title><body style='margin:0'>" +
        "".join(f"<p style='height:120px;margin:0'>row {i}</p>" for i in range(80)) +
        "<a id=lnk href='/zoom.html' style='position:fixed;left:300px;top:10px'>a link</a></body></html>")
SHORT = "<html><title>short</title><body>nothing to scroll</body></html>"


def run_ext(S, app, w, base, outdir):
    """`S` is the selftest module (ok, js, load, wait_until, PAGES, ...)."""
    ok, js, load, wait_until = S.ok, S.js, S.load, S.wait_until
    S.PAGES["/long.html"] = LONG
    S.PAGES["/short.html"] = SHORT
    t = w.new_tab(None)
    QTest.qWait(500)

    def appjs(code):
        box = {}
        t.page.runJavaScript(code, APP_WORLD, lambda r: box.setdefault("r", r))
        wait_until(lambda: "r" in box, 4000)
        return box.get("r")

    # ---- auto-scroll ---------------------------------------------------------------------------------------------------
    app.settings.data["custom_autoscroll"] = True
    for p in (app.profile, app._private_profile):
        if p is not None:
            from .engine import pagescripts
            pagescripts.install(p, app.settings)
    ok("auto-scroll script is installed on the profile", bool(app.profile.scripts().find("null-autoscroll")))
    load(t, base + "/long.html")
    QTest.qWait(300)
    ok("auto-scroll is armed in the page (isolated world)", appjs("window.__nullAutoscroll === true") is True)
    ok("page JS cannot see the auto-scroll flag", js(t, "typeof window.__nullAutoscroll") == "undefined")
    appjs("""var tg=document.elementFromPoint(400,300);
             tg.dispatchEvent(new MouseEvent('mousedown',{button:1,clientX:400,clientY:300,bubbles:true,cancelable:true}));
             tg.dispatchEvent(new MouseEvent('mouseup',{button:1,clientX:400,clientY:300,bubbles:true,cancelable:true})); 0""")
    state = appjs("JSON.stringify(window.__nullAutoscrollState)")
    ok("middle-click starts auto-scroll (v axis) and a quick click keeps it on", state is not None and '"ax":"v"' in state and '"sticky":true' in state, str(state))
    ok("auto-scroll sets its own cursor (not a resize cursor)", appjs("!!document.querySelector('style[data-null-autoscroll]')") is True)
    appjs("window.dispatchEvent(new MouseEvent('mousemove',{clientX:400,clientY:520,bubbles:true})); 0")
    QTest.qWait(700)
    y1 = js(t, "window.scrollY")
    ok("moving the pointer down scrolls the page down", isinstance(y1, (int, float)) and y1 > 150, f"scrollY={y1}")
    appjs("window.dispatchEvent(new MouseEvent('mousemove',{clientX:400,clientY:80,bubbles:true})); 0")
    QTest.qWait(700)
    y2 = js(t, "window.scrollY")
    ok("moving the pointer up scrolls back up", isinstance(y2, (int, float)) and y2 < y1, f"{y1} -> {y2}")
    appjs("document.body.dispatchEvent(new MouseEvent('mousedown',{button:0,clientX:400,clientY:80,bubbles:true,cancelable:true})); 0")
    ok("any click ends auto-scroll", appjs("window.__nullAutoscrollState === null") is True)
    ok("cursor override is removed afterwards", appjs("!document.querySelector('style[data-null-autoscroll]')") is True)
    y3 = js(t, "window.scrollY")
    QTest.qWait(300)
    ok("page stays put once auto-scroll ended", js(t, "window.scrollY") == y3)
    # middle-click on a link must not start auto-scroll (it opens a new tab in Chrome)
    appjs("document.getElementById('lnk').dispatchEvent(new MouseEvent('mousedown',{button:1,bubbles:true,cancelable:true})); 0")
    ok("middle-click on a link does not start auto-scroll", appjs("window.__nullAutoscrollState === null") is True)
    # nothing to scroll -> nothing starts
    load(t, base + "/short.html")
    QTest.qWait(200)
    appjs("document.body.dispatchEvent(new MouseEvent('mousedown',{button:1,clientX:50,clientY:50,bubbles:true,cancelable:true})); 0")
    ok("no auto-scroll on a page that cannot scroll", appjs("window.__nullAutoscrollState === null") is True)

    # ---- tabs: drag to reorder, selected tab on top -------------------------------------------------------------------
    from PyQt6.QtCore import QPoint, Qt
    tw = app.new_window()
    QTest.qWait(500)
    for n in range(3):
        tw.new_tab(base + "/short.html", background=True)
    QTest.qWait(600)
    bar = tw.tabbar
    ok("tab strip has 4 tabs", bar.count() == 4 and len(tw.tabs) == 4)
    moved = []
    bar.tabMoved.connect(lambda a, b: moved.append((a, b)))
    first_url = tw.tabs[0]
    r0 = bar.tabRect(0)
    start = QPoint(r0.center().x(), r0.center().y() + 4)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    ok("pressing a tab selects it at once", bar.currentIndex() == 0)
    steps = 14
    target_x = bar.tabRect(2).center().x()
    mid_shot = False
    for k in range(1, steps + 1):
        x = start.x() + (target_x - start.x()) * k / steps
        QTest.mouseMove(bar, QPoint(int(x), start.y()))
        QTest.qWait(16)
        if k == steps // 2 and not mid_shot:
            tw.grab().save(f"{outdir}/tab_drag_mid.png")
            mid_shot = True
    ok("dragging a tab right reorders it past its neighbours", bar._dix == 2 and tw.tabs[2] is first_url, f"dix={bar._dix}")
    ok("window pages follow the tab strip while dragging", len(moved) == 2 and moved[-1] == (1, 2), str(moved))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(target_x), start.y()))
    wait_until(lambda: not bar._off, 3000)
    ok("after release the drag ends and tabs settle", bar._dix == -1 and not bar._off, f"off={bar._off}")
    ok("selected tab is the one that was dragged", bar.currentIndex() == 2 and tw.current() is first_url)
    # close button / middle click
    n_before = bar.count()
    rr = bar.tabRect(3)
    QTest.mouseClick(bar, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, QPoint(rr.center().x(), rr.center().y() + 4))
    QTest.qWait(300)
    ok("middle-click closes a tab", bar.count() == n_before - 1)
    cur = bar.currentIndex()
    body = bar._body(cur)
    close = bar._parts(cur, body, True, True)["close"]
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, close.center().toPoint())
    QTest.qWait(300)
    ok("clicking the close button closes the tab", bar.count() == n_before - 2)
    tw.grab().save(f"{outdir}/tabs_after.png")
    tw.close()
    QTest.qWait(300)
    run_ext2(S, app, w, base, outdir)
    run_ext3(S, app, w, base, outdir)
    run_ext4(S, app, w, base, outdir)


# ======================================================================================================================
def run_ext2(S, app, w, base, outdir):
    """Accounts (cookie keeper), VPN, installed apps (PWA) and the new settings pages."""
    import json
    import os
    import socket
    import threading

    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtNetwork import QNetworkCookie
    from PyQt6.QtWidgets import QApplication

    from .core import vpn as vpn_mod
    from .web import api as api_mod
    ok, js, load, wait_until = S.ok, S.js, S.load, S.wait_until

    def cookie(name, domain, value="v"):
        c = QNetworkCookie(name.encode(), value.encode())
        c.setDomain(domain)
        c.setPath("/")
        c.setSecure(True)
        return c

    def jar_names(store_holder):
        names = set()
        got = []
        store = store_holder
        store.cookieAdded.connect(lambda c: got.append(bytes(c.name()).decode()))
        store.loadAllCookies()
        wait_until(lambda: False, 700)
        names.update(got)
        return names

    # ---- cookie keeper: clear cookies, keep the Google sign-in ----------------------------------------------------------
    store = app.profile.cookieStore()
    for c, host in ((cookie("SID", ".google.com"), "https://accounts.google.com"), (cookie("HSID", ".google.com"), "https://accounts.google.com"),
                    (cookie("session", ".example.org"), "https://example.org"), (cookie("track", ".ads.example.net"), "https://ads.example.net")):
        store.setCookie(c)
    wait_until(lambda: any(k[2] == "SID" for k in app.cookies.jar), 3000)
    ok("cookie keeper mirrors the cookie jar", {"SID", "HSID", "session", "track"} <= {k[2] for k in app.cookies.jar}, str(sorted(k[2] for k in app.cookies.jar)))
    app.account.set("tester@example.com", "Tester", "")
    app.settings.data["google_keep_signed_in"] = True
    ok("keep_google_login is on when signed in", app.keep_google_login() is True)
    app.clear_data({"cookies"}, "all")
    wait_until(lambda: not any(k[2] in ("session", "track") for k in app.cookies.jar), 3000)
    left = {k[2] for k in app.cookies.jar}
    ok("Clear browsing data deletes other sites' cookies", "session" not in left and "track" not in left, str(sorted(left)))
    ok("...but keeps the Google sign-in cookies", {"SID", "HSID"} <= left, str(sorted(left)))
    app.settings.data["google_keep_signed_in"] = False
    app.clear_data({"cookies"}, "all")
    wait_until(lambda: "SID" not in {k[2] for k in app.cookies.jar}, 3000)
    ok("with 'keep sign-in' off, the Google cookies are cleared too", "SID" not in {k[2] for k in app.cookies.jar})
    app.settings.data["google_keep_signed_in"] = True
    app.account.clear()
    info = app.account_info()
    ok("account info for a signed-out profile", info["signed_in"] is False)

    # ---- VPN ------------------------------------------------------------------------------------------------------------
    # a tiny HTTP CONNECT server stands in for the user's proxy
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    seen = []

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                data = conn.recv(2048)
                seen.append(data.split(b"\r\n")[0])
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            finally:
                conn.close()
    threading.Thread(target=serve, daemon=True).start()
    api_mod.dispatch(app, "vpn/save", {"name": "local", "scheme": "http", "host": "127.0.0.1", "port": port, "user": "u", "password": "secret"})
    state = api_mod.dispatch(app, "vpn/state", {})
    sid = state["servers"][-1]["id"]
    ok("VPN server saved and its password is never returned to pages", "secret" not in json.dumps(state) and state["servers"][-1]["has_password"] is True, json.dumps(state)[:160])
    tok = api_mod.dispatch(app, "vpn/test", {"id": sid})["token"]
    wait_until(lambda: api_mod.dispatch(app, "vpn/test_result", {"token": tok})["done"], 6000)
    res = api_mod.dispatch(app, "vpn/test_result", {"token": tok})
    ok("VPN connection test reaches the proxy and gets a tunnel", res.get("ok") is True and seen and seen[0].startswith(b"CONNECT example.com:443"), str(res) + str(seen[:1]))
    ok("VPN off: no proxy flags", vpn_mod.chromium_args(app.vpn.dir) == [])
    app.vpn.set_active(sid)
    app.vpn.set_enabled(True)
    args = vpn_mod.chromium_args(app.vpn.dir)
    ok("VPN on: Chromium gets the proxy and a WebRTC policy", any(a.startswith("--proxy-server=http://127.0.0.1:") for a in args) and any("webrtc" in a for a in args), str(args))
    ok("VPN credentials are answered only for the proxy itself", app.vpn.credentials_for("127.0.0.1", port) == ("u", "secret") and app.vpn.credentials_for("example.com") is None)
    from .core import vpn_qt
    vpn_qt.apply(app.vpn)
    from PyQt6.QtNetwork import QNetworkProxyFactory, QNetworkProxyQuery
    qp = QNetworkProxyFactory.proxyForQuery(QNetworkProxyQuery("example.com", 443))
    lp = QNetworkProxyFactory.proxyForQuery(QNetworkProxyQuery("127.0.0.1", 1234))
    ok("Qt's own sockets use the tunnel (loopback stays direct)", qp and qp[0].hostName() == "127.0.0.1" and qp[0].port() == port and lp[0].type().name == "NoProxy", f"{qp[0].type()} {lp[0].type()}")
    w.refresh_vpn_button()
    ok("VPN button appears in the toolbar when the VPN is on", not w.vpn_btn.isHidden())
    app.vpn.set_enabled(False)
    vpn_qt.apply(app.vpn)
    w.refresh_vpn_button()
    ok("VPN button hides when the VPN is off", w.vpn_btn.isHidden())
    api_mod.dispatch(app, "vpn/delete", {"id": sid})
    srv.close()
    try:
        api_mod.dispatch(app, "vpn/save", {"name": "bad", "scheme": "socks5", "host": "h", "port": 1080, "user": "x"})
        ok("SOCKS5 with a user name is refused with an explanation", False)
    except Exception as exc:
        ok("SOCKS5 with a user name is refused with an explanation", "SOCKS5" in str(exc), str(exc)[:80])

    # ---- installed apps (PWA) --------------------------------------------------------------------------------------------
    S.PAGES["/app.html"] = ("<html><head><title>Demo App</title><link rel='manifest' href='/manifest.json'><meta name='theme-color' content='#336699'></head>"
                            "<body>demo app</body></html>")
    S.PAGES["/manifest.json"] = json.dumps({"name": "Demo App", "short_name": "Demo", "start_url": "/app.html", "scope": "/", "display": "standalone",
                                            "theme_color": "#336699", "icons": []})
    t = w.new_tab(base + "/app.html")
    wait_until(lambda: getattr(t, "installable", False), 6000)
    ok("a page with a manifest shows the Install chip", getattr(t, "installable", False) is True)
    w.tabbar.setCurrentIndex(w.index_of(t))
    QTest.qWait(300)
    w.update_install_chip()
    ok("the Install chip is visible in the address bar", not w.omni.install_chip.isHidden())

    def accept_install():
        d = QApplication.activeModalWidget()
        if d is not None and d.__class__.__name__ == "InstallDialog":
            d.accept()
    timer = QTimer()
    timer.timeout.connect(accept_install)
    timer.start(200)
    QTest.mouseClick(w.omni.install_chip, Qt.MouseButton.LeftButton)          # a real click: Qt passes `checked` to the slot
    wait_until(lambda: bool(app.pwa.apps), 12000)
    timer.stop()
    ok("installing from the address bar creates an app", len(app.pwa.apps) == 1, str(list(app.pwa.apps)))
    aid = next(iter(app.pwa.apps), None)
    rec = app.pwa.get(aid) or {}
    ok("the app keeps its name, scope and theme colour", rec.get("name") == "Demo App" and rec.get("scope", "").endswith("/") and rec.get("theme_color", "").lower() == "#336699", str({k: rec.get(k) for k in ("name", "scope", "theme_color")}))
    ok("the app has an icon file", os.path.isfile(app.pwa.icon_path(aid)))
    pw = app.pwa_windows.get(aid)
    wait_until(lambda: pw is not None and pw.tab.page.url().path() == "/app.html", 8000)
    ok("the app opens in its own window", pw is not None and pw.isVisible() and pw.tab.page.url().path() == "/app.html")
    ok("the app uses its own profile, not the browser's", pw is not None and pw.tab.page.profile() is not app.profile and pw.tab.page.profile().storageName() == "NullApp-" + aid, pw.tab.page.profile().storageName() if pw else "")
    # a cookie set by the app's own page survives 'clear everything' in the browser; the same kind of cookie in the browser does not
    S.js(pw.tab, "document.cookie='appsession=1; max-age=86400; path=/'; 0")
    tc = w.new_tab(base + "/short.html")
    wait_until(lambda: tc.page.url().path() == "/short.html", 5000)
    QTest.qWait(300)
    S.js(tc, "document.cookie='ctrl=1; max-age=86400; path=/'; 0")
    ok("the app's page can set its own cookie", "appsession=1" in (S.js(pw.tab, "document.cookie") or ""))
    ok("the browser's page can set a cookie", "ctrl=1" in (S.js(tc, "document.cookie") or ""))
    app.clear_data({"history", "cookies", "cache", "downloads", "site_perms"}, "all")
    QTest.qWait(1200)
    ok("'Clear browsing data' (everything) does not touch an installed app's cookies", "appsession=1" in (S.js(pw.tab, "document.cookie") or ""), str(S.js(pw.tab, "document.cookie")))
    ok("...while the same kind of cookie in the browser profile is cleared", "ctrl=1" not in (S.js(tc, "document.cookie") or ""), str(S.js(tc, "document.cookie")))
    w.close_tab(tc)
    ok("the app is still installed afterwards", aid in app.pwa.apps)
    # update detection: the site changes its manifest
    S.PAGES["/manifest.json"] = json.dumps({"name": "Demo App 2", "short_name": "Demo", "start_url": "/app.html", "scope": "/", "display": "standalone",
                                            "theme_color": "#993366", "icons": []})
    box = {}
    app.pwa_check_update(aid, pw.tab.page, force=False, callback=lambda note: box.setdefault("n", note))
    wait_until(lambda: "n" in box, 10000)
    ok("a changed manifest is detected and applied as an update", "Updated" in box.get("n", "") and app.pwa.get(aid)["name"] == "Demo App 2" and app.pwa.get(aid)["theme_color"].lower() == "#993366", str(box))
    api_mod.dispatch(app, "pwa/set_auto", {"id": aid, "on": False})
    ok("auto-update can be switched off per app", app.pwa.get(aid)["auto_update"] is False)
    lst = api_mod.dispatch(app, "pwa/list", {})["apps"]
    ok("API lists apps without icon blobs", len(lst) == 1 and "icons" not in lst[0])
    pw.close()
    QTest.qWait(300)
    pdir = app.pwa.data_dir(aid)
    app.uninstall_pwa(aid)
    wait_until(lambda: not os.path.isdir(pdir), 6000)
    ok("uninstalling removes the app and its data folder", aid not in app.pwa.apps and not os.path.isdir(pdir))
    w.close_tab(t)

    # ---- new settings pages render -------------------------------------------------------------------------------------------
    t2 = w.new_tab(None)
    before = len(t2.page.console)
    for name, expect in (("settings/account", "Google account"), ("settings/apps", "Apps"), ("settings/vpn", "VPN"), ("settings", "You and Null Browser")):
        good = load(t2, f"null://{name}")
        QTest.qWait(600)
        text = js(t2, "document.body.innerText") or ""
        ok(f"null://{name} renders", good and expect.lower() in text.lower(), text[:100].replace("\n", " | "))
        if name in ("settings/vpn", "settings/apps", "settings/account"):
            S.shot(w, outdir, "page_" + name.replace("/", "_"))
    errs = [c for c in t2.page.console[before:] if c[1] >= 2]
    ok("no JS errors on the new settings pages", not errs, str(errs[:2]))
    w.close_tab(t2)


# ======================================================================================================================
def run_ext3(S, app, w, base, outdir):
    """Toolbar mouse behaviour (middle / right / hold) and the bookmarks bar."""
    from PyQt6.QtCore import Qt
    from .ui.window_bookmarks import BookmarkButton
    ok, js, load, wait_until = S.ok, S.js, S.load, S.wait_until

    t = w.new_tab(None)
    QTest.qWait(300)
    for page in ("/short.html", "/long.html", "/short.html"):
        load(t, base + page)
    w.tabbar.setCurrentIndex(w.index_of(t))
    QTest.qWait(300)
    h = t.page.history()
    ok("test tab has a back history", h.canGoBack() and h.currentItemIndex() >= 2, str(h.currentItemIndex()))
    cur = h.currentItemIndex()
    n0 = len(w.tabs)
    QTest.mouseClick(w.back_btn, Qt.MouseButton.MiddleButton)
    QTest.qWait(300)
    ok("middle-click on Back opens the previous page in a new background tab", len(w.tabs) == n0 + 1 and w.tabs[-1].page.url().path() == "/long.html",
       str([x.page.url().path() for x in w.tabs[-2:]]))
    ok("...and does not navigate the current tab", t.page.history().currentItemIndex() == cur and w.current() is t)
    w.close_tab(w.tabs[-1])
    # right-click and hold show the history list (the real menu is modal, so it is replaced by a flag here)
    shown = []
    w.back_btn.menuRequested.disconnect()
    w.back_btn.menuRequested.connect(lambda: shown.append(1))
    QTest.mouseClick(w.back_btn, Qt.MouseButton.RightButton)
    ok("right-click on Back asks for the history list", len(shown) == 1)
    QTest.mousePress(w.back_btn, Qt.MouseButton.LeftButton)
    QTest.qWait(700)
    QTest.mouseRelease(w.back_btn, Qt.MouseButton.LeftButton)
    QTest.qWait(300)
    ok("holding Back shows the list and does not also go back", len(shown) == 2 and t.page.history().currentItemIndex() == cur, f"{shown} idx={t.page.history().currentItemIndex()}")
    QTest.mouseClick(w.back_btn, Qt.MouseButton.LeftButton)
    QTest.qWait(500)
    ok("a normal click on Back still goes back", t.page.history().currentItemIndex() == cur - 1)
    w.history_open(-1)                                              # menu entry two pages back -> goToItem
    QTest.qWait(500)
    ok("choosing an older entry in the list jumps there", t.page.history().currentItemIndex() == max(0, cur - 2))
    w.close_tab(t)

    # ---- bookmarks bar ---------------------------------------------------------------------------------------------------
    db = app.db
    ids = [db.add_bookmark(f"BM{i}", f"{base}/short.html?bm={i}", "Bookmarks bar") for i in range(3)]
    gid = db.add_bookmark("InFolder", f"{base}/long.html?f=1", "Test folder")
    db.add_bookmark("InFolder2", f"{base}/long.html?f=2", "Test folder")
    app.bookmarks_changed()
    QTest.qWait(300)
    btns = [x for x in w.bmbar.findChildren(BookmarkButton) if x.bid in ids]
    ok("bookmark buttons appear on the bar", len(btns) == 3, str(len(btns)))
    n_tabs = len(w.tabs)
    cur_tab = w.current()
    QTest.mouseClick(btns[0], Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(400)
    ok("Ctrl+click on a bookmark opens a background tab", len(w.tabs) == n_tabs + 1 and w.current() is cur_tab)
    w.close_tab(w.tabs[-1])
    QTest.mouseClick(btns[1], Qt.MouseButton.MiddleButton)
    QTest.qWait(400)
    ok("middle-click on a bookmark opens a background tab", len(w.tabs) == n_tabs + 1 and w.current() is cur_tab)
    w.close_tab(w.tabs[-1])
    # drag to reorder: the drop slot under the pointer, then the database order
    last = btns[-1]
    n, edge = w._bm_drops._slot(last.geometry().right() + 20)
    n0_, edge0 = w._bm_drops._slot(btns[0].geometry().left() + 1)
    allb = sorted([x for x in w.bmbar.findChildren(BookmarkButton) if x.bid is not None], key=lambda b: b.x())
    ok("the drop slot is computed from the pointer position", n == len(allb) and n0_ == allb.index(btns[0]) and edge > edge0, f"{n} {n0_} {edge} {edge0} of {len(allb)}")
    db.move_bookmark(ids[2], "Bookmarks bar", 0)
    order = [b["id"] for b in db.bookmarks("Bookmarks bar") if b["id"] in ids]
    ok("moving a bookmark changes its place on the bar", order == [ids[2], ids[0], ids[1]], str(order))
    app.bookmarks_changed()
    QTest.qWait(200)
    shown_order = [x.bid for x in sorted(w.bmbar.findChildren(BookmarkButton), key=lambda b: b.x()) if x.bid in ids]
    ok("the bar shows the new order", shown_order == [ids[2], ids[0], ids[1]], str(shown_order))
    ok("folders keep their bookmarks and rename moves them", db.rename_folder("Test folder", "Renamed") is None and len(db.bookmarks("Renamed")) == 2)
    S.shot(w, outdir, "bookmark_bar2")
    for b in db.bookmarks():
        if b["id"] in ids or b["folder"] == "Renamed":
            db.delete_bookmark(b["id"])
    app.bookmarks_changed()
    QTest.qWait(200)


# ======================================================================================================================
def run_ext4(S, app, w, base, outdir):
    """One tab per built-in page, toast safety, Google sign-in compatibility script."""
    from .engine import google_compat
    ok, js, load, wait_until = S.ok, S.js, S.load, S.wait_until

    # ---- a toast whose label was already destroyed must not raise -----------------------------------------------------
    w.show_toast("first")
    w._toast.deleteLater()
    QTest.qWait(80)
    try:
        w.show_toast("second")
        good = True
    except RuntimeError:
        good = False
    ok("a new toast works after the previous label was destroyed", good)

    # ---- singleton built-in pages -------------------------------------------------------------------------------------
    def tabs_showing(host):
        return [t for t in w.tabs if t.real_url().scheme() == "null" and t.real_url().host() == host]
    for t in tabs_showing("downloads") + tabs_showing("history") + tabs_showing("settings"):
        w.close_tab(t)
    QTest.qWait(200)
    first = w.open_url("null://downloads")
    wait_until(lambda: first.page.url().host() == "downloads", 5000)
    n = len(w.tabs)
    other = w.new_tab(base + "/short.html")
    QTest.qWait(300)
    again = w.open_url("null://downloads")
    QTest.qWait(300)
    ok("opening Downloads again does not open a second Downloads tab", again is first and len(tabs_showing("downloads")) == 1 and len(w.tabs) == n + 1, f"{len(w.tabs)} tabs")
    ok("...it switches to the tab that already has it", w.current() is first)
    # a link on one built-in page to another built-in page that is already open
    hist = w.open_url("null://history")
    wait_until(lambda: hist.page.url().host() == "history" and hist.page.title() != "", 5000)
    QTest.qWait(500)
    w.tabbar.setCurrentIndex(w.index_of(first))
    QTest.qWait(300)
    count = len(w.tabs)
    js(first, "document.querySelector('.sidebar a[href=\"null://history\"]').click(); 0")
    QTest.qWait(600)
    ok("History link in the Downloads sidebar goes to the open History tab", w.current() is hist and len(w.tabs) == count, f"{len(w.tabs)} vs {count}")
    ok("...and the Downloads tab stays on Downloads", first.page.url().host() == "downloads")
    # settings sub-pages reuse the Settings tab and navigate it
    st = w.open_url("null://settings")
    wait_until(lambda: st.page.url().host() == "settings", 5000)
    count = len(w.tabs)
    st2 = w.open_url("null://settings/vpn")
    QTest.qWait(800)
    ok("Settings > VPN reuses the Settings tab and shows that section", st2 is st and len(w.tabs) == count and st.page.url().path().endswith("/vpn"), st.page.url().toString())
    # typing it in an empty New Tab switches to the open one and drops the empty tab
    blank = w.new_tab(None)
    QTest.qWait(500)
    nb = len(w.tabs)
    w.omni.edit.setText("null://history")
    w.navigate_text("null://history")
    QTest.qWait(500)
    ok("typing null://history in an empty New Tab goes to the open History tab", w.current() is hist, str(w.current().real_url().toString()))
    ok("...and the empty New Tab is closed", len(w.tabs) == nb - 1 and blank not in w.tabs)
    for t in (first, hist, st, other):
        if t in w.tabs:
            w.close_tab(t)
    QTest.qWait(200)

    # ---- Google sign-in compatibility ----------------------------------------------------------------------------------
    t = w.new_tab(base + "/short.html")
    wait_until(lambda: t.page.url().path() == "/short.html", 5000)
    QTest.qWait(300)
    before = js(t, "JSON.stringify((navigator.userAgentData||{}).brands||[])") or ""
    ok("without the compatibility script the page sees no Google Chrome brand", "Google Chrome" not in before, before)
    js(t, google_compat.script_source("134", hosts_regex=".*"))
    after = js(t, "JSON.stringify(navigator.userAgentData.brands)") or ""
    ok("the compatibility script adds the Google Chrome brand", '"Google Chrome"' in after and '"134"' in after, after)
    ok("window.chrome exists afterwards", js(t, "typeof window.chrome") == "object")
    ok("the script is only installed for Google hosts by default", "google" in google_compat.HOSTS_REGEX and not google_compat.is_google_host("127.0.0.1"))
    ok("the interceptor sends the Chrome brand only when the setting is on", (app.adblock.client_hints is not None) == bool(app.settings.get("google_compat")))
    w.close_tab(t)
