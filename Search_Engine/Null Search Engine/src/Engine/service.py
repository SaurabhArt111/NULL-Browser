"""SearchService: local index + federated providers + fusion + instant answers + knowledge panel + suggestions."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from . import providers as prov
from .answers import instant_answer
from .cache import CircuitBreaker, TTLCache
from .config import Settings
from .log import get_logger, q_for_log
from .net import dedupe_key
from .providers.base import Provider, ProviderError, Query, Result
from .providers.wikipedia import Wikipedia
from .ranking import fuse
from .store import Hit, Store
from .text import ParsedQuery, clean_query, highlight_plain, make_snippet, parse_query

log = get_logger("service")
KINDS = ("web", "images", "news")
TIME_SINCE = {"d": 86400, "w": 7 * 86400, "m": 30 * 86400, "y": 365 * 86400}


@dataclass
class Response:
    query: str
    kind: str = "web"
    page: int = 1
    results: List[Dict] = field(default_factory=list)
    answer: Optional[Dict] = None
    panel: Optional[Dict] = None
    local_total: int = 0
    providers: Dict[str, str] = field(default_factory=dict)
    took_ms: int = 0
    has_next: bool = False
    notice: str = ""
    cached: bool = False

    def as_dict(self) -> Dict:
        return dict(self.__dict__)


def _view(r: Result, terms: List[str], hit_body: str = "") -> Dict:
    p = urlsplit(r.url)
    host = (p.hostname or "")
    host = host[4:] if host.startswith("www.") else host
    path = p.path.rstrip("/")
    crumb = host + (" › " + " › ".join(x for x in path.split("/") if x)[:70] if path else "")
    snippet = make_snippet(hit_body, terms) if hit_body else highlight_plain(r.snippet, terms)
    return {"title": r.title or r.url, "url": r.url, "host": host, "crumb": crumb, "snippet": [[t, b] for t, b in snippet],
            "snippet_text": r.snippet, "sources": r.sources or ([r.source] if r.source else []), "local": r.local,
            "thumb": r.thumb, "image": r.image, "width": r.width, "height": r.height, "published": r.published, "publisher": r.publisher,
            "extra": r.extra}


class SearchService:
    def __init__(self, settings: Settings, store: Store, client: httpx.AsyncClient, providers: Optional[Dict[str, Provider]] = None):
        self.settings, self.store, self.client = settings, store, client
        self.providers = prov.build(settings) if providers is None else providers
        self.cache = TTLCache(settings.cache_size, settings.cache_ttl)
        self.panel_cache = TTLCache(128, 3600)
        self.breakers: Dict[str, CircuitBreaker] = {n: CircuitBreaker(3, 30.0) for n in self.providers}
        self.recent: Deque[str] = deque(maxlen=50)
        self.searches = 0

    # ---- federation ---------------------------------------------------------------------
    async def _call(self, p: Provider, q: Query) -> List[Result]:
        key = p.key(q)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        br = self.breakers[p.name]
        try:
            res = await asyncio.wait_for(p.search(self.client, q), timeout=self.settings.provider_timeout)
        except Exception:
            br.failure()
            raise
        br.success()
        self.cache.set(key, res)
        return res

    async def federate(self, q: Query):
        """Run all providers for ``q.kind`` in parallel. Returns ({name: results}, {name: status})."""
        status: Dict[str, str] = {}
        tasks: Dict[asyncio.Task, str] = {}
        for name, p in self.providers.items():
            if q.kind not in p.kinds:
                continue
            if self.breakers[name].is_open:
                status[name] = "paused"
                continue
            tasks[asyncio.create_task(self._call(p, q))] = name
        results: Dict[str, List[Result]] = {}
        loop = asyncio.get_running_loop()
        hard = loop.time() + self.settings.web_budget
        soft: Optional[float] = None
        pending = set(tasks)
        while pending:
            now = loop.time()
            limit = min(hard, soft) if soft else hard
            if limit - now <= 0:
                break
            done, pending = await asyncio.wait(pending, timeout=limit - now, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                name = tasks[t]
                try:
                    results[name] = t.result()
                    status[name] = "ok"
                    if soft is None and results[name]:
                        soft = loop.time() + self.settings.web_soft_budget
                except asyncio.TimeoutError:
                    status[name] = "timeout"
                except ProviderError as e:
                    status[name] = f"error: {e}"
                except Exception as e:
                    status[name] = f"error: {type(e).__name__}"
        for t in pending:
            t.cancel()
            status[tasks[t]] = "timeout"
        return results, status

    # ---- search -------------------------------------------------------------------------
    async def search(self, raw: str, kind: str = "web", page: int = 1, safe: str = "moderate", time_range: str = "", lang: str = "en") -> Response:
        t0 = time.perf_counter()
        raw = clean_query(raw)
        kind = kind if kind in KINDS else "web"
        page = max(1, min(int(page or 1), 20))
        safe = safe if safe in ("off", "moderate", "strict") else "moderate"
        time_range = time_range if time_range in TIME_SINCE else ""
        resp = Response(query=raw, kind=kind, page=page)
        if not raw:
            return resp
        self.searches += 1
        if self.settings.remember_recent and raw not in self.recent:
            self.recent.appendleft(raw)
        log.debug("search %s kind=%s page=%d", q_for_log(raw, self.settings.log_queries), kind, page)
        pq = parse_query(raw)
        terms = pq.highlight
        per_page = {"web": self.settings.per_page, "images": self.settings.image_per_page, "news": self.settings.news_per_page}[kind]

        if kind == "web" and page == 1:
            resp.answer = instant_answer(raw)

        local_task = None
        if kind == "web":
            since = time.time() - TIME_SINCE[time_range] if time_range else None
            local_task = asyncio.create_task(asyncio.to_thread(self.store.search, pq, per_page, (page - 1) * per_page, since))
        wq = Query(q=raw, kind=kind, page=page, lang=lang, safe=safe, time=time_range, count=per_page)
        web, status = await self.federate(wq) if self.providers else ({}, {})
        lists: Dict[str, List[Result]] = dict(web)
        hits: List[Hit] = []
        if local_task:
            hits, resp.local_total = await local_task
            lists["local"] = [Result(title=h.title or h.url, url=h.url, snippet=h.description, source="local", rank=i + 1, local=True)
                              for i, h in enumerate(hits)]
        bodies = {dedupe_key(h.url): (h.body or h.description) for h in hits}
        weights = {n: p.weight for n, p in self.providers.items()}
        fused = fuse(lists, weights, pq.terms, self.settings.max_per_host if kind == "web" else 0, self.settings.local_boost,
                     limit=per_page if kind == "web" else per_page + 10)
        views = []
        for r in fused:
            body = bodies.get(dedupe_key(r.url), "") if r.local else ""
            views.append(_view(r, terms, body))
        resp.results = views
        resp.providers = status
        counts = [len(v) for v in web.values()]
        resp.has_next = bool(resp.local_total > page * per_page or any(c >= max(5, per_page - 2) for c in counts)) and page < 20
        if kind == "web" and page == 1 and not resp.answer:
            resp.panel = await self._panel(pq, web.get("wikipedia", []), lang)
        if resp.answer and not resp.results:
            resp.notice = ""
        elif self.providers and status and not any(s == "ok" for s in status.values()):
            resp.notice = "offline" if not hits else "partial"
        elif not self.providers and self.settings.web_enabled is False:
            resp.notice = "offline-mode"
        resp.took_ms = int((time.perf_counter() - t0) * 1000)
        return resp

    async def _panel(self, pq: ParsedQuery, wiki: List[Result], lang: str) -> Optional[Dict]:
        w = self.providers.get("wikipedia")
        if not isinstance(w, Wikipedia) or not wiki or not pq.terms or pq.has_filters or len(pq.terms) > 5 or pq.phrases or pq.exclude:
            return None
        title = wiki[0].title.rsplit(" - Wikipedia", 1)[0]
        tw = {x for x in title.lower().replace("(", " ").replace(")", " ").split() if x.isalnum()}
        qs = set(pq.terms)
        if not (qs <= tw or tw <= qs):
            return None
        key = (title, lang)
        cached = self.panel_cache.get(key)
        if cached is not None:
            return cached or None
        try:
            s = await asyncio.wait_for(w.summary(self.client, title, lang), timeout=1.2)
        except Exception:
            return None
        self.panel_cache.set(key, s or {})
        return s

    # ---- suggestions --------------------------------------------------------------------
    async def suggest(self, prefix: str, lang: str = "en") -> List[str]:
        prefix = clean_query(prefix)
        if len(prefix) < 1:
            return []
        low = prefix.lower()
        out: List[str] = []
        out += [r for r in self.recent if r.lower().startswith(low) and r.lower() != low][:3]
        try:
            out += await asyncio.to_thread(self.store.titles_like, prefix, 3)
        except Exception:
            pass
        budget = self.settings.suggest_budget_ms / 1000
        if budget > 0 and len(prefix) >= 2:
            tasks = [asyncio.create_task(p.suggest(self.client, prefix, lang)) for n, p in self.providers.items()
                     if not self.breakers[n].is_open and type(p).suggest is not Provider.suggest and type(p).__name__ in ("DuckDuckGo", "Wikipedia")]
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=budget)
                for t in pending:
                    t.cancel()
                for t in tasks:
                    if t in done and not t.exception():
                        out += t.result()
        seen, uniq = set(), []
        for s in out:
            k = s.strip().lower()
            if k and k != low and k not in seen:
                seen.add(k)
                uniq.append(s.strip())
        return uniq[:8]

    def provider_info(self) -> List[Dict]:
        return [{"name": n, "kinds": list(p.kinds), "paused": self.breakers[n].is_open, "keyed": p.needs_key} for n, p in self.providers.items()]
