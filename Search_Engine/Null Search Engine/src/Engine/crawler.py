"""Polite background crawler: robots.txt, per-host delay, depth/page limits, SSRF-safe fetching.

One crawl job runs at a time. It is an asyncio task in the server's event loop, so it never blocks searches.
"""
from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .extract import decode, extract
from .log import get_logger
from .net import FetchError, Resolver, UnsafeURL, check_url, normalize_url, safe_get
from .store import Doc, Store

log = get_logger("crawler")

HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
BOT_NAME = "NullSearch"


@dataclass
class CrawlStatus:
    running: bool = False
    seeds: List[str] = field(default_factory=list)
    pages_indexed: int = 0
    pages_seen: int = 0
    queued: int = 0
    errors: int = 0
    skipped: int = 0
    max_pages: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    last_url: str = ""
    message: str = "idle"

    def as_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)


class Crawler:
    def __init__(self, store: Store, settings: Settings, client: httpx.AsyncClient, resolver: Optional[Resolver] = None):
        self.store, self.settings, self.client, self.resolver = store, settings, client, resolver
        self.status = CrawlStatus()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._next_ok: Dict[str, float] = {}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, seeds: List[str], max_pages: int = 50, depth: int = 2, same_site: bool = True) -> CrawlStatus:
        if self.running:
            raise RuntimeError("A crawl is already running")
        clean: List[str] = []
        for s in seeds[:50]:
            s = s.strip()
            if s and "://" not in s:
                s = "https://" + s
            try:
                clean.append(await check_url(s, self.settings.allow_private, self.resolver))
            except UnsafeURL as e:
                log.info("seed rejected: %s", e)
        if not clean:
            raise ValueError("No valid public http(s) URLs to crawl")
        max_pages = max(1, min(int(max_pages), self.settings.crawl_max_pages))
        self.status = CrawlStatus(running=True, seeds=clean, max_pages=max_pages, started_at=time.time(), message="crawling")
        self._stop = asyncio.Event()
        self._robots.clear()
        self._next_ok.clear()
        self._task = asyncio.create_task(self._run(clean, max_pages, max(0, min(depth, 5)), same_site))
        return self.status

    def stop(self) -> None:
        self._stop.set()

    async def wait(self) -> None:
        if self._task:
            await self._task

    async def _run(self, seeds: List[str], max_pages: int, depth: int, same_site: bool) -> None:
        st = self.status
        queue: Deque[Tuple[str, int]] = deque((s, 0) for s in seeds)
        seen: Set[str] = set(seeds)
        allowed_hosts = {_site(s) for s in seeds}
        lock = asyncio.Lock()

        async def worker() -> None:
            while not self._stop.is_set():
                async with lock:
                    if st.pages_indexed >= max_pages or not queue:
                        return_now = not queue and busy[0] == 0
                        item = None
                    else:
                        item = queue.popleft()
                        busy[0] += 1
                    st.queued = len(queue)
                if item is None:
                    if st.pages_indexed >= max_pages or return_now:
                        return
                    await asyncio.sleep(0.05)
                    continue
                url, d = item
                try:
                    links = await self._crawl_one(url, st)
                finally:
                    async with lock:
                        busy[0] -= 1
                if links and d < depth:
                    async with lock:
                        for l in links:
                            if l in seen or len(seen) > max_pages * 50:
                                continue
                            if same_site and _site(l) not in allowed_hosts:
                                continue
                            seen.add(l)
                            queue.append((l, d + 1))
                        st.queued = len(queue)

        busy = [0]
        try:
            await asyncio.gather(*(worker() for _ in range(self.settings.crawl_threads)))
            st.message = "stopped" if self._stop.is_set() else "done"
        except Exception as e:  # pragma: no cover - defensive
            log.exception("crawl failed")
            st.message = f"error: {type(e).__name__}"
        finally:
            st.running = False
            st.finished_at = time.time()
            st.queued = 0
            try:
                await asyncio.to_thread(self.store.optimize)
            except Exception:
                pass

    async def _crawl_one(self, url: str, st: CrawlStatus) -> List[str]:
        st.last_url = url
        host = urlsplit(url).netloc
        if not await self._robots_ok(url):
            st.skipped += 1
            return []
        await self._polite_wait(host)
        try:
            r = await safe_get(self.client, url, max_bytes=self.settings.crawl_max_bytes, allow_private=self.settings.allow_private,
                               accept_types=HTML_TYPES, resolver=self.resolver, timeout=12)
        except (FetchError, UnsafeURL) as e:
            st.errors += 1
            log.debug("fetch failed %s: %s", url, e)
            return []
        st.pages_seen += 1
        if r.status != 200 or not r.body:
            st.skipped += 1
            return []
        page = extract(decode(r.body, r.headers.get("content-type", "")), r.url)
        if not page.noindex and (page.text or page.title):
            canonical = page.canonical if page.canonical and _site(page.canonical) == _site(r.url) else r.url
            res = await asyncio.to_thread(self.store.upsert, Doc(url=canonical, title=page.title or canonical, description=page.description,
                                                                 body=page.text, lang=page.lang))
            if res in ("new", "updated", "same"):
                st.pages_indexed += 1
        else:
            st.skipped += 1
        return [] if page.nofollow else page.links

    async def _polite_wait(self, host: str) -> None:
        now = time.monotonic()
        at = max(self._next_ok.get(host, 0.0), now)
        self._next_ok[host] = at + self.settings.crawl_delay
        if at > now:
            await asyncio.sleep(at - now)

    async def _robots_ok(self, url: str) -> bool:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            rp: Optional[urllib.robotparser.RobotFileParser] = None
            try:
                r = await safe_get(self.client, origin + "/robots.txt", max_bytes=300_000, allow_private=self.settings.allow_private,
                                   resolver=self.resolver, timeout=8)
                if r.status == 200:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(r.body.decode("utf-8", "replace").splitlines())
                elif r.status in (401, 403):
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(["User-agent: *", "Disallow: /"])
            except (FetchError, UnsafeURL):
                rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(BOT_NAME, url)


def _site(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h
