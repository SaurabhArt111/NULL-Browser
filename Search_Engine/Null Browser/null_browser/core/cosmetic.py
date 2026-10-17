"""Cosmetic filtering: hides ad containers that network blocking leaves behind, and runs uBlock-style scriptlets.

How it works (main thread only):

1. `prepare(page, url)` runs just before a main-frame navigation. It asks the engine for the page's cosmetic resources and
   installs ONE named user script on that page (`null-cosmetic`, main frame only, run at document creation) that
   * adds the hide rules (`display:none !important`) through an adopted stylesheet, one rule at a time so a single
     selector the browser rejects cannot cancel the others, and
   * runs the scriptlets the lists ask for (anti-adblock, YouTube ad skipping ...).
2. `after_load(page)` runs once the page has loaded (and again a moment later for late content): it collects the classes
   and ids on the page, asks the engine which *generic* rules need them, and hides those too.

Nothing here talks to the network, and pages never see a Python object: the only thing that crosses is CSS / JS text.
"""
import json
import logging

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWebEngineCore import QWebEngineScript

log = logging.getLogger("null.cosmetic")
SCRIPT_NAME = "null-cosmetic"
QUrlFull = QUrl.ComponentFormattingOption.FullyEncoded
MAX_SELECTORS = 20000
_COLLECT = r"""(function(){try{var c=new Set(),i=new Set(),n=document.querySelectorAll('[class],[id]'),k,j,e;
for(k=0;k<n.length&&k<12000;k++){e=n[k];if(e.id)i.add(e.id);for(j=0;j<e.classList.length;j++)c.add(e.classList[j]);}
return JSON.stringify([Array.from(c),Array.from(i)]);}catch(x){return '[[],[]]';}})()"""

def _chunks(items, size=40):
    """Group selectors so most rules cost one insertRule, but a rejected selector only loses its own group's fallback."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def hide_js(selectors):
    """JS that hides `selectors`; falls back to one-by-one inside a rejected group."""
    groups = list(_chunks(selectors))
    return r"""(function(groups){try{
var sheet=new CSSStyleSheet(),rules=0;
function add(s){try{sheet.insertRule(s+'{display:none!important}',sheet.cssRules.length);rules++;return true;}catch(e){return false;}}
for(var i=0;i<groups.length;i++){var g=groups[i];if(!add(g.join(',')))for(var j=0;j<g.length;j++)add(g[j]);}
document.adoptedStyleSheets=(document.adoptedStyleSheets||[]).concat([sheet]);
}catch(e){}})(%s);""" % json.dumps(groups)


class CosmeticFilter:
    def __init__(self, adblocker, settings):
        self.ab, self.settings = adblocker, settings
        self._state = {}                       # page -> {"exceptions": [...], "generichide": bool, "seen": set(), "url": str}

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
            for sc in coll.find(SCRIPT_NAME):
                coll.remove(sc)
            self._state.pop(page, None)
            if not self.active_for(url):
                return
            res = self.ab.filters.engine.cosmetic(url.toString(QUrlFull))
            hide = res.get("hide_selectors") or []
            script = res.get("injected_script") or ""
            self._state[page] = {"exceptions": res.get("exceptions") or [], "generichide": bool(res.get("generichide")),
                                 "seen": set(), "url": url.toString()}
            if not hide and not script:
                return
            parts = []
            if hide:
                parts.append(hide_js(sorted(hide)[:MAX_SELECTORS]))
            if script:
                parts.append("try{" + script + "\n}catch(e){}")
            sc = QWebEngineScript()
            sc.setName(SCRIPT_NAME)
            sc.setSourceCode("\n".join(parts))
            sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            sc.setRunsOnSubFrames(False)
            coll.insert(sc)
        except Exception:
            log.debug("cosmetic prepare failed", exc_info=True)

    # ---- after load ------------------------------------------------------------------------------
    def after_load(self, page, again=True):
        st = self._state.get(page)
        if not st or st["generichide"]:
            return
        try:
            if page.url().toString() != st["url"] and page.requestedUrl().toString() != st["url"]:
                return                           # navigated on (redirect / SPA route): the next prepare() will refresh the state
            page.runJavaScript(_COLLECT, QWebEngineScript.ScriptWorldId.MainWorld, lambda r, p=page: self._collected(p, r))
            if again:
                QTimer.singleShot(2500, lambda p=page: self.after_load(p, again=False))
        except RuntimeError:
            self._state.pop(page, None)          # the page object is gone
        except Exception:
            log.debug("cosmetic after_load failed", exc_info=True)

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
            self._state.pop(page, None)
        except Exception:
            log.debug("cosmetic collect failed", exc_info=True)

    def forget(self, page):
        self._state.pop(page, None)


