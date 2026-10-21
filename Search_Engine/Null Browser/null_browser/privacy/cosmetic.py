"""Cosmetic filtering: hides ad containers that network blocking leaves behind, and runs uBlock-style scriptlets.

How it works (main thread only):

1. `prepare(page, url)` runs just before a main-frame navigation. It asks the engine for the page's cosmetic resources and
   installs ONE named user script on that page (`null-cosmetic`, main frame only, run at document creation) that
   * hides the site-specific selectors (`display:none !important`) in one persistent adopted stylesheet, before first paint;
   * runs the scriptlets the lists ask for (anti-adblock, YouTube ad skipping ...);
   * starts a `MutationObserver` that queues the class names and ids of every element the page adds, so that
     *generic* rules (`##.ad-banner`) can be applied to content that appears later (infinite scroll, SPA route changes).
2. While the tab is visible a short timer (`Watcher`) drains that queue, asks the engine which generic rules match, and hides
   them. It polls every 250 ms during the first seconds after navigation (when ad slots appear, so nothing sits on screen for
   long) and every 1.2 s afterwards. An idle page costs one tiny `runJavaScript` per tick and nothing else.

Previously generic rules were applied once, after the load event and again 2.5 s later: slots were visible for seconds and
then collapsed (layout shift = flicker), and anything inserted later was never hidden.

Nothing here talks to the network, and pages never see a Python object: the only thing that crosses is CSS / JS text.
"""
import json
import logging
import secrets

from PyQt6.QtCore import QObject, QTimer, QUrl
from PyQt6.QtWebEngineCore import QWebEngineScript

log = logging.getLogger("null.cosmetic")
SCRIPT_NAME = "null-cosmetic"
QUrlFull = QUrl.ComponentFormattingOption.FullyEncoded
MAX_SELECTORS = 20000
FAST_MS, SLOW_MS, FAST_TICKS = 250, 1200, 20            # 20 fast ticks = the first 5 seconds
TOKEN = "nullcq-" + secrets.token_hex(8)                # console message the page sends when its queue is non-empty (see Tab / BrowserPage)

_SHEET = r"""var s=window.__nullSheet;if(!s){s=window.__nullSheet=new CSSStyleSheet();
try{Object.defineProperty(window,'__nullSheet',{enumerable:false});}catch(e){}
document.adoptedStyleSheets=(document.adoptedStyleSheets||[]).concat([s]);}"""

# Queue of class names / ids added to the page. Runs at document creation, before the page's own scripts.
# When the queue becomes non-empty it pings the browser (one console message, throttled to ~30 ms) so the drain happens at once
# instead of waiting for the next timer tick: that is what keeps the time an ad slot is visible down to a frame or two.
_OBSERVER = r"""(function(){try{if(window.__nullCQ)return;var q={c:new Set(),i:new Set()},dbg=console.debug.bind(console),wait=false;
Object.defineProperty(window,'__nullCQ',{value:q,enumerable:false});
function ping(){if(wait)return;wait=true;setTimeout(function(){wait=false;if(q.c.size||q.i.size)dbg('__TOKEN__');},30);}
function take(n){if(n.nodeType!==1)return;if(n.id)q.i.add(n.id);var cl=n.classList;if(cl)for(var k=0;k<cl.length;k++)q.c.add(cl[k]);}
function scan(n){take(n);if(n.querySelectorAll){var a=n.querySelectorAll('[class],[id]');for(var k=0;k<a.length&&k<6000;k++)take(a[k]);}}
new MutationObserver(function(ms){for(var i=0;i<ms.length;i++){var m=ms[i];if(m.type==='childList'){for(var j=0;j<m.addedNodes.length;j++)scan(m.addedNodes[j]);}else take(m.target);}ping();})
 .observe(document,{subtree:true,childList:true,attributes:true,attributeFilter:['class','id']});
document.addEventListener('DOMContentLoaded',function(){scan(document.documentElement);ping();},{once:true});
}catch(e){}})();""".replace('__TOKEN__', TOKEN)

_DRAIN = r"""(function(){var q=window.__nullCQ;if(!q||(!q.c.size&&!q.i.size))return '';
var r=JSON.stringify([Array.from(q.c),Array.from(q.i)]);q.c.clear();q.i.clear();return r;})()"""


def _chunks(items, size=40):
    """Group selectors so most rules cost one insertRule, but a rejected selector only loses its own group's fallback."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def hide_js(selectors):
    """JS that hides `selectors`; falls back to one-by-one inside a rejected group."""
    groups = list(_chunks(selectors))
    return ("(function(groups){try{" + _SHEET +
            r"""function add(t){try{s.insertRule(t+'{display:none!important}',s.cssRules.length);return true;}catch(e){return false;}}
for(var i=0;i<groups.length;i++){var g=groups[i];if(!add(g.join(',')))for(var j=0;j<g.length;j++)add(g[j]);}
}catch(e){}})(%s);""" % json.dumps(groups))


class Watcher(QObject):
    """Drains one page's class / id queue on a timer while the page is on screen."""

    def __init__(self, cosmetic, page):
        super().__init__(page)
        self.cosmetic, self.page = cosmetic, page
        self.ticks = 0
        self.busy = False
        self.again = False
        self.timer = QTimer(self, interval=FAST_MS)
        self.timer.timeout.connect(self.tick)

    def restart(self):
        self.ticks = 0
        self.timer.setInterval(FAST_MS)
        self.timer.start()

    def kick(self):
        """The page says new class / id names are waiting: drain now."""
        if self.busy:
            self.again = True
        else:
            self.drain()

    def tick(self):
        self.ticks += 1
        if self.ticks == FAST_TICKS:
            self.timer.setInterval(SLOW_MS)
        self.drain()

    def drain(self):
        try:
            if self.busy or not self.page.isVisible():
                return
            self.busy = True
            self.page.runJavaScript(_DRAIN, QWebEngineScript.ScriptWorldId.MainWorld, self._got)
        except RuntimeError:
            self.timer.stop()                      # the page is gone

    def _got(self, raw):
        self.busy = False
        if raw:
            self.cosmetic._collected(self.page, raw)
        if self.again:
            self.again = False
            self.drain()


class CosmeticFilter:
    def __init__(self, adblocker, settings):
        self.ab, self.settings = adblocker, settings
        self._state = {}                       # page -> {"exceptions": [...], "generichide": bool, "seen": set(), "url": str}
        self._watchers = {}                    # page -> Watcher

    # ---- policy -----------------------------------------------------------------------------
    def active_for(self, url):
        ab = self.ab
        if not ab.enabled or not self.settings.get("adblock_cosmetic") or ab.filters.engine is None:
            return False
        if url.scheme() not in ("http", "https") or not url.host():
            return False
        return not ab.is_allowed(url.host().lower())

    # ---- before navigation ---------------------------------------------------------------------
    def prepare(self, page, url):
        try:
            coll = page.scripts()
            old = coll.find(SCRIPT_NAME)
            for sc in old:
                coll.remove(sc)
            self._state.pop(page, None)
            w = self._watchers.get(page)
            if w is not None:
                w.timer.stop()
            if not self.active_for(url):
                return
            res = self.ab.filters.engine.cosmetic(url.toString(QUrlFull))
            hide = res.get("hide_selectors") or []
            script = res.get("injected_script") or ""
            generichide = bool(res.get("generichide"))
            self._state[page] = {"exceptions": res.get("exceptions") or [], "generichide": generichide, "seen": set(), "url": url.toString()}
            parts = []
            if hide:
                parts.append(hide_js(sorted(hide)[:MAX_SELECTORS]))
            if not generichide:
                parts.append(_OBSERVER)
            if script:
                parts.append("try{" + script + "\n}catch(e){}")
            if not parts:
                return
            sc = QWebEngineScript()
            sc.setName(SCRIPT_NAME)
            sc.setSourceCode("\n".join(parts))
            sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            sc.setRunsOnSubFrames(False)
            coll.insert(sc)
            if not generichide:
                if w is None:
                    w = self._watchers[page] = Watcher(self, page)
                w.restart()
        except Exception:
            log.debug("cosmetic prepare failed", exc_info=True)

    # ---- after load ------------------------------------------------------------------------------
    def after_load(self, page, again=True):
        """Kept for the caller in Tab: make sure the watcher is running (it normally started in prepare())."""
        w = self._watchers.get(page)
        if w is not None and self._state.get(page) and not self._state[page]["generichide"] and not w.timer.isActive():
            w.restart()

    def _collected(self, page, raw):
        st = self._state.get(page)
        eng = self.ab.filters.engine
        if not st or eng is None or not raw:
            return
        try:
            classes, ids = json.loads(raw)
            classes = [c for c in classes if ("." + c) not in st["seen"]]
            ids = [i for i in ids if ("#" + i) not in st["seen"]]
            if not classes and not ids:
                return
            st["seen"].update("." + c for c in classes)
            st["seen"].update("#" + i for i in ids)
            sels = eng.hidden_class_id_selectors(classes, ids, st["exceptions"])
            if sels:
                page.runJavaScript(hide_js(sorted(set(sels))[:MAX_SELECTORS]), QWebEngineScript.ScriptWorldId.MainWorld)
        except RuntimeError:
            self._state.pop(page, None)          # the page object is gone
        except Exception:
            log.debug("cosmetic collect failed", exc_info=True)

    def kick(self, page):
        w = self._watchers.get(page)
        if w is not None:
            w.kick()

    def forget(self, page):
        self._state.pop(page, None)
        w = self._watchers.pop(page, None)
        if w is not None:
            try:
                w.timer.stop()
            except RuntimeError:
                pass
