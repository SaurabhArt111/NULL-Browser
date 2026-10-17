"""Filter engines and filter lists for the ad / tracker blocker.

Three interchangeable engines, best first (all expose the same small API, see `pyabp.Engine`):

1. **rust**   - `null_adblock`: our PyO3 binding of Brave's adblock-rust (native/ folder). Fastest; full uBlock/ABP syntax,
                scriptlets, `$redirect`, `$removeparam`, `$csp`, cosmetic filters.
2. **pypi**   - the community `adblock` wheel (also adblock-rust, an older release). Prebuilt for Windows, so `pip install`
                is enough; used when the native module has not been built.
3. **python** - `pyabp`: pure-Python engine, no dependencies (slower, a subset of the syntax).

`FilterManager` owns the filter lists (bundled snapshot + optional updates), builds the engine on a worker thread, caches
the compiled engine on disk, and swaps it in atomically so browsing is never blocked and never unprotected.
"""
import hashlib
import json
import logging
import marshal
import os
import sys
import threading
import time

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import paths, pyabp
from .scriptlets import Scriptlets

log = logging.getLogger("null.adblock")

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(PKG, "data", "filters")
NATIVE_DIR = os.path.join(PKG, "_native")                  # build_native.bat / .sh copy the compiled module here
RESOURCES_FILE = "brave-resources.json"
CACHE_FORMAT = 2                                           # bump when the cached engine layout changes

UBO = "https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/"
# kind: ads | trackers | mixed | security.  `heavy` lists are off by default on the slow pure-Python engine.
CATALOG = [
    dict(id="easylist", title="EasyList", file="easylist.txt", url="https://easylist.to/easylist/easylist.txt", kind="ads",
         desc="The standard ad-blocking list for most websites"),
    dict(id="easyprivacy", title="EasyPrivacy", file="easyprivacy.txt", url="https://easylist.to/easylist/easyprivacy.txt", kind="trackers",
         desc="Analytics, tracking scripts, pixels and fingerprinting"),
    dict(id="brave", title="Brave default filters", file="brave-main-list.txt", url=None, kind="mixed", heavy=True,
         desc="Brave's own ad and tracker rules, scriptlets and fixes (bundled snapshot)"),
    dict(id="brave-unbreak", title="Brave unbreak", file="brave-unbreak.txt", url=None, kind="mixed",
         desc="Exceptions that keep popular sites working (bundled snapshot)"),
    dict(id="ubo", title="uBlock filters", file="ubo-filters.txt", url=UBO + "filters.txt", kind="mixed", heavy=True,
         desc="uBlock Origin's own filters: ads, pop-ups, anti-adblock, video ads"),
    dict(id="ubo-unbreak", title="uBlock unbreak", file="ubo-unbreak.txt", url=UBO + "unbreak.txt", kind="mixed",
         desc="Fixes for sites broken by the other lists"),
    dict(id="ubo-badware", title="Badware risks", file="ubo-badware.txt", url=UBO + "badware.txt", kind="security",
         desc="Known malicious, scam and phishing hosts"),
    dict(id="ubo-resource-abuse", title="Resource abuse", file="ubo-resource-abuse.txt", url=UBO + "resource-abuse.txt", kind="security",
         desc="Sites that abuse your CPU or hijack your browser"),
    dict(id="coin-miners", title="Crypto-miners", file="coin-miners.txt", url=None, kind="security",
         desc="Blocks in-browser cryptocurrency miners (bundled snapshot)"),
]
BY_ID = {c["id"]: c for c in CATALOG}
UPDATE_EVERY = 7 * 24 * 3600


# ------------------------------------------------------------------------------------------------ engine back-ends
class PypiEngine:
    """Adapter that makes the PyPI `adblock` wheel look like `null_adblock.Engine`.

    The wheel is an older adblock-rust: it matches network and cosmetic rules well but cannot assemble the newer uBlock
    scriptlets (YouTube's ad blocking relies on them), so `core.scriptlets` does that part and the two are combined here.
    """

    def __init__(self, engine, mod, sc=None):
        self._e, self._m, self._sc = engine, mod, sc or Scriptlets()

    @staticmethod
    def make(mod):
        class _E(PypiEngine):
            @staticmethod
            def from_lists(lists, debug=False):
                fs = mod.FilterSet(debug)
                sc = Scriptlets()
                for text, fmt in lists:
                    fs.add_filter_list(text, fmt)
                    if fmt == "standard":
                        sc.add_lines(text)
                sc.finish()
                return _E(mod.Engine(fs), mod, sc)

            @staticmethod
            def from_serialized(data):
                d = marshal.loads(bytes(data))
                if d.get("v") != 2:
                    raise ValueError("unknown cache format")
                e = mod.Engine(mod.FilterSet())
                e.deserialize(d["engine"])
                sc = Scriptlets()
                sc.raw = [tuple(x) for x in d["sc"]]
                sc.finish()
                return _E(e, mod, sc)
        return _E

    def serialize(self):
        return marshal.dumps({"v": 2, "engine": bytes(self._e.serialize()), "sc": self._sc.raw})

    def add_resources_json(self, text):
        n = 0
        self._sc.set_resources(text)
        for r in json.loads(text):
            kind = r.get("kind")
            ctype = kind.get("mime") if isinstance(kind, dict) else kind
            if not ctype or not r.get("content"):
                continue
            try:
                self._e.add_resource(r["name"], ctype, r["content"], r.get("aliases") or [])
                n += 1
            except Exception:
                pass
        return n

    def check(self, url, source_url="", request_type="other"):
        r = self._e.check_network_urls(url, source_url or url, request_type)
        return (bool(r.matched), r.redirect or None, None)

    def csp(self, url, source_url, request_type):
        return None

    def cosmetic(self, url):
        r = self._e.url_cosmetic_resources(url)
        return {"hide_selectors": sorted(r.hide_selectors), "procedural_actions": [], "exceptions": sorted(r.exceptions),
                "injected_script": self._sc.script_for(url), "generichide": bool(r.generichide)}

    def hidden_class_id_selectors(self, classes, ids, exceptions):
        return list(self._e.hidden_class_id_selectors(list(classes), list(ids), set(exceptions)))   # the wheel insists on a set


class Backend:
    def __init__(self, name, label, engine_cls, version=""):
        self.name, self.label, self.cls, self.version = name, label, engine_cls, version

    def __repr__(self):
        return f"<Backend {self.name} {self.version}>"


def load_backend(prefer=None):
    """Pick the best engine that actually imports and passes a smoke test."""
    order = [prefer] if prefer else ["rust", "pypi", "python"]
    order += [x for x in ("rust", "pypi", "python") if x not in order]
    for name in order:
        try:
            if name == "rust":
                if os.path.isdir(NATIVE_DIR) and NATIVE_DIR not in sys.path:
                    sys.path.insert(0, NATIVE_DIR)
                import null_adblock
                b = Backend("rust", "Rust (Brave adblock-rust)", null_adblock.Engine, null_adblock.engine_version())
            elif name == "pypi":
                import adblock
                b = Backend("pypi", "Rust (adblock wheel)", PypiEngine.make(adblock), "adblock " + getattr(adblock, "__version__", "?"))
            else:
                b = Backend("python", "Python (built-in)", pyabp.Engine, "pyabp")
            e = b.cls.from_lists([("||null-selftest.invalid^\n##.null-selftest\n", "standard")])
            ok = e.check("https://x.null-selftest.invalid/a.js", "https://example.com/", "script")[0]
            if not ok:
                raise RuntimeError("smoke test failed")
            return b
        except Exception as exc:                              # noqa: BLE001 - any failure just means "try the next engine"
            if name == "python":
                raise
            log.info("ad-block engine %r unavailable: %s", name, exc)
    raise RuntimeError("no ad-block engine available")


# ------------------------------------------------------------------------------------------------ lists
def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def looks_like_filter_list(text):
    head = text[:4000]
    return len(text) > 2000 and ("[Adblock" in head or "! Title" in head or "! Version" in head or "||" in text[:200000])


class FilterManager(QObject):
    """Owns the lists and the current engine."""
    ready = pyqtSignal(str)                  # backend label, after every (re)build
    changed = pyqtSignal()                   # list state changed (for the settings page)
    _built = pyqtSignal(object, str, str, int)    # engine, backend name, message, rule count  (worker thread -> main thread)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.engine = None
        self.backend = None
        self.generation = 0
        self.building = False
        self.message = ""
        self.rules = 0
        self._custom_text = ""
        self._pending = False
        self._lock = threading.Lock()
        self.nam = QNetworkAccessManager(self)
        self._built.connect(self._on_built)
        self.updating = False
        self.update_error = ""

    # ---- paths / catalogue --------------------------------------------------------------------
    @staticmethod
    def user_dir():
        return paths.sub("filters")

    def list_path(self, item):
        user = os.path.join(self.user_dir(), item["file"])
        if os.path.isfile(user):
            return user, "updated"
        bundled = os.path.join(BUNDLED, item["file"])
        return (bundled, "bundled") if os.path.isfile(bundled) else (None, "missing")

    def enabled(self, item):
        chosen = self.settings.get("adblock_lists") or {}
        if item["id"] in chosen:
            return bool(chosen[item["id"]])
        if item["kind"] == "trackers" and not self.settings.get("block_trackers"):
            return False
        if item.get("heavy") and self.backend is not None and self.backend.name == "python":
            return False
        return True

    def lists_info(self):
        out = []
        for c in CATALOG:
            p, src = self.list_path(c)
            ts = os.path.getmtime(p) if p else 0
            out.append({"id": c["id"], "title": c["title"], "desc": c["desc"], "kind": c["kind"], "enabled": self.enabled(c) and p is not None,
                        "source": src, "updated": ts, "updatable": bool(c["url"]), "heavy": bool(c.get("heavy"))})
        return out

    def set_enabled(self, list_id, on):
        if list_id not in BY_ID:
            return False
        chosen = dict(self.settings.get("adblock_lists") or {})
        chosen[list_id] = bool(on)
        self.settings.set("adblock_lists", chosen, silent=True)
        self.rebuild()
        return True

    # ---- engine building ----------------------------------------------------------------------
    def set_custom(self, text):
        """User rules (one filter per line); included in the next build."""
        self._custom_text = text or ""

    def rebuild(self):
        """(Re)build the engine in the background. Calls made while a build runs are coalesced into one follow-up build."""
        with self._lock:
            if self.building:
                self._pending = True
                return
            self.building = True
        prefer = os.environ.get("NULL_ADBLOCK_BACKEND") or None
        if self.backend is None:
            try:
                self.backend = load_backend(prefer)                   # cheap (smoke test only); needed to pick the right default lists
            except Exception:                                         # noqa: BLE001
                log.exception("no ad-block engine could be loaded")
        sources = []
        chosen = self.settings.get("adblock_lists") or {}
        for c in CATALOG:
            mode = "standard"
            if not self.enabled(c):
                # the big lists are too heavy for the pure-Python matcher, but their scriptlets (YouTube ad blocking ...) are cheap
                if c.get("heavy") and self.backend is not None and self.backend.name == "python" and c["id"] not in chosen:
                    mode = "scriptlets"
                else:
                    continue
            p, _src = self.list_path(c)
            if p:
                st = os.stat(p)
                sources.append((c["id"], p, st.st_size, st.st_mtime_ns, mode))
        custom = self._custom_text
        threading.Thread(target=self._build, args=(sources, custom, prefer, self.backend), daemon=True, name="adblock-build").start()
        self.changed.emit()

    def _build(self, sources, custom, prefer, backend):
        t0 = time.time()
        try:
            backend = backend or load_backend(prefer)
            res_path = os.path.join(BUNDLED, RESOURCES_FILE)
            res_stat = os.stat(res_path) if os.path.isfile(res_path) else None
            sig = hashlib.sha256(json.dumps([CACHE_FORMAT, backend.name, backend.version, sources, hashlib.sha1(custom.encode()).hexdigest(),
                                             res_stat and [res_stat.st_size, res_stat.st_mtime_ns]]).encode()).hexdigest()
            cache_dir = os.path.join(self.user_dir(), "cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache = os.path.join(cache_dir, f"engine-{backend.name}.bin")
            meta = cache + ".json"
            engine, how, rules = None, "built", 0
            try:
                with open(meta, encoding="utf-8") as f:
                    m = json.load(f)
                good = m.get("sig") == sig
                if good:
                    rules = int(m.get("rules", 0))
                    with open(cache, "rb") as f:
                        engine = backend.cls.from_serialized(f.read())
                    how = "loaded from cache"
            except (OSError, ValueError, RuntimeError, Exception):          # noqa: BLE001 - a bad cache just means rebuild
                engine = None
            if engine is None:
                lists = [(_read(p), mode) for _id, p, _s, _m, mode in sources]
                if custom.strip():
                    lists.append((custom, "standard"))
                rules = sum(1 for text, _f in lists if _f == "standard" for ln in text.splitlines() if ln and ln[0] not in "![#")
                engine = backend.cls.from_lists(lists)
                try:
                    blob = engine.serialize()
                    for old in (cache, meta):
                        if os.path.exists(old):
                            os.remove(old)
                    with open(cache, "wb") as f:
                        f.write(blob)
                    with open(meta, "w", encoding="utf-8") as f:
                        json.dump({"sig": sig, "rules": rules}, f)
                except Exception:                                           # noqa: BLE001
                    log.debug("could not cache the compiled filter engine", exc_info=True)
            if res_stat:
                try:
                    engine.add_resources_json(_read(res_path))
                except Exception:                                           # noqa: BLE001
                    log.warning("filter resources not loaded", exc_info=True)
            msg = f"{backend.label}: {len(sources)} lists {how} in {time.time() - t0:.2f}s"
            self._built.emit(engine, backend.name, msg, rules)
        except Exception as exc:                                            # noqa: BLE001
            log.exception("building the filter engine failed")
            self._built.emit(None, getattr(backend, "name", ""), f"failed: {exc}", 0)

    def _on_built(self, engine, backend_name, msg, rules):
        if engine is not None:
            if self.backend is None or self.backend.name != backend_name:
                try:
                    self.backend = load_backend(backend_name)
                except Exception:                                           # noqa: BLE001
                    pass
            self.rules = rules
            self.engine = engine                                            # atomic swap: the interceptor reads this attribute
            self.generation += 1
        self.message = msg
        log.info("Ad blocker: %s", msg)
        again = False
        with self._lock:
            self.building = False
            again, self._pending = self._pending, False
        if engine is not None:
            self.ready.emit(self.backend.label if self.backend else "")
        self.changed.emit()
        if again:
            self.rebuild()

    # ---- updating -----------------------------------------------------------------------------
    def last_update(self):
        return float(self.settings.get("adblock_last_update") or 0)

    def maybe_auto_update(self):
        if self.settings.get("adblock_auto_update") and time.time() - self.last_update() > UPDATE_EVERY:
            self.update_all()

    def update_all(self):
        if self.updating:
            return
        self.updating, self.update_error = True, ""
        self._queue = [c for c in CATALOG if c["url"] and self.enabled(c)]
        self._updated = 0
        self.changed.emit()
        self._next()

    def _next(self):
        if not self._queue:
            self.updating = False
            if self._updated:
                self.settings.set("adblock_last_update", time.time(), silent=True)
                self.rebuild()
            elif not self.update_error:
                self.settings.set("adblock_last_update", time.time(), silent=True)
            self.changed.emit()
            return
        item = self._queue.pop(0)
        req = QNetworkRequest(QUrl(item["url"]))
        req.setTransferTimeout(30000)
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"NullBrowser-FilterUpdater")
        rep = self.nam.get(req)
        rep.finished.connect(lambda r=rep, it=item: self._fetched(r, it))

    def _fetched(self, rep, item):
        try:
            if rep.error() != QNetworkReply.NetworkError.NoError:
                self.update_error = f"{item['title']}: {rep.errorString()}"
                log.warning("filter list update failed: %s", self.update_error)
            else:
                text = bytes(rep.readAll()).decode("utf-8", "replace")
                if looks_like_filter_list(text):
                    dest = os.path.join(self.user_dir(), item["file"])
                    with open(dest + ".tmp", "w", encoding="utf-8", newline="\n") as f:
                        f.write(text)
                    os.replace(dest + ".tmp", dest)
                    self._updated += 1
                else:
                    self.update_error = f"{item['title']}: the download did not look like a filter list (ignored)"
        except Exception as exc:                                            # noqa: BLE001
            self.update_error = f"{item['title']}: {exc}"
            log.exception("filter list update")
        finally:
            rep.deleteLater()
            self._next()

    def reset_updates(self):
        """Go back to the bundled snapshot."""
        for c in CATALOG:
            try:
                os.remove(os.path.join(self.user_dir(), c["file"]))
            except OSError:
                pass
        self.settings.set("adblock_last_update", 0, silent=True)
        self.rebuild()
