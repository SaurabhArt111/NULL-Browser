"""FastAPI application factory: routes, security middleware, image/favicon proxies, admin API."""
from __future__ import annotations

import asyncio
import datetime as dt
import email.utils
import os
import re
import time
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import quote_plus, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .cache import TTLCache
from .config import SRC_DIR, TEMPLATES_DIR, Settings
from .crawler import Crawler
from .log import configure_logging, get_logger
from .net import FetchError, Resolver, UnsafeURL, safe_get
from .service import SearchService
from .store import Store

log = get_logger("app")
STATIC_DIR = os.path.join(SRC_DIR, "static")
VERSION = "2.0.0"
IMG_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp", "image/x-icon", "image/vnd.microsoft.icon"}
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251}[a-z0-9])?$")


class CrawlRequest(BaseModel):
    urls: List[str] = Field(default_factory=list, max_length=50)
    max_pages: int = Field(50, ge=1, le=5000)
    depth: int = Field(2, ge=0, le=5)
    same_site: bool = True


class DeleteRequest(BaseModel):
    url: Optional[str] = None
    host: Optional[str] = None


def _ago(value: str) -> str:
    """Relative age for news items (RFC 822 or ISO dates); falls back to the raw string."""
    if not value:
        return ""
    d = None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:24]
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    s = (dt.datetime.now(dt.timezone.utc) - d).total_seconds()
    if s < 0:
        return d.strftime("%d %b %Y")
    for limit, div, unit in ((3600, 60, "min"), (86400, 3600, "h"), (86400 * 14, 86400, "d")):
        if s < limit:
            return f"{max(1, int(s // div))} {unit} ago"
    return d.strftime("%d %b %Y")


def create_app(settings: Optional[Settings] = None, client: Optional[httpx.AsyncClient] = None, providers=None,
               resolver: Optional[Resolver] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    templates.env.filters["ago"] = _ago
    media_cache = TTLCache(96, 3600)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = Store(settings.db_path)
        app.state.http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.provider_timeout, connect=3.0), limits=httpx.Limits(max_connections=40, max_keepalive_connections=10),
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0", "Accept-Language": "en"})
        app.state.service = SearchService(settings, app.state.store, app.state.http, providers)
        app.state.crawler = Crawler(app.state.store, settings, app.state.http, resolver)
        log.info("Null Search %s ready on http://127.0.0.1:%d  (%d pages indexed, providers: %s)", VERSION, settings.port, app.state.store.count(),
                 ", ".join(app.state.service.providers) or "none - local index only")
        try:
            yield
        finally:
            app.state.crawler.stop()
            if client is None:
                await app.state.http.aclose()
            app.state.store.close()

    app = FastAPI(title="Null Search", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    allowed = {h.lower() for h in settings.allowed_hosts}

    csp = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:" + ("" if settings.proxy_images else " https:") +
           "; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")

    # ---- security middleware ---------------------------------------------------------------
    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").lower()
        hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if hostname not in allowed:                                   # blocks DNS-rebinding attacks
            return JSONResponse({"error": "Host not allowed"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and (urlsplit(origin).hostname or "").lower() not in {h.strip("[]") for h in allowed}:
                return JSONResponse({"error": "Cross-origin request blocked"}, status_code=403)
            if request.headers.get("x-null-search") != "1":           # forces a CORS preflight for any foreign page
                return JSONResponse({"error": "Missing X-Null-Search header"}, status_code=403)
        if request.url.path.startswith(("/api/img", "/api/favicon")) and request.headers.get("sec-fetch-site", "same-origin") == "cross-site":
            return Response(status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault("Content-Security-Policy", csp)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if request.url.path.startswith("/api/") and not request.url.path.startswith(("/api/img", "/api/favicon")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    if os.path.isdir(STATIC_DIR):
        app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    def svc() -> SearchService:
        return app.state.service

    def lang_of(request: Request) -> str:
        al = request.headers.get("accept-language", "en").split(",")[0].strip().lower()
        return al if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,4})?", al) else "en"

    def ctx(request: Request, **kw):
        return {"request": request, "version": VERSION, "docs": app.state.store.count(), **kw}

    # ---- pages ----------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request, q: Optional[str] = None):
        if q and q.strip():
            return RedirectResponse("/search?q=" + quote_plus(q.strip()), status_code=302)
        return templates.TemplateResponse(request, "home.html", ctx(request, answer_examples=["2^10 / 3", "10 km to miles", "time in tokyo", "#6c5ce7"]))

    @app.get("/search", response_class=HTMLResponse)
    async def search_page(request: Request, q: str = "", kind: str = "web", page: int = 1, safe: str = "moderate", t: str = ""):
        if not q.strip():
            return RedirectResponse("/", status_code=302)
        r = await svc().search(q, kind, page, safe, t, lang_of(request))
        return templates.TemplateResponse(request, "results.html", ctx(request, r=r, q=r.query, kind=r.kind, page=r.page, safe=safe, t=t,
                                                                     has_providers=bool(svc().providers)))

    @app.get("/index", response_class=HTMLResponse)
    async def index_page(request: Request):
        return templates.TemplateResponse(request, "index_admin.html", ctx(request, stats=app.state.store.stats(), providers=svc().provider_info(),
                                                                         crawl=app.state.crawler.status.as_dict(), recent=app.state.store.recent(25)))

    @app.get("/opensearch.xml")
    async def opensearch(request: Request):
        base = f"http://127.0.0.1:{settings.port}"
        xml = (f'<?xml version="1.0" encoding="UTF-8"?><OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
               f"<ShortName>Null Search</ShortName><Description>Private local search</Description><InputEncoding>UTF-8</InputEncoding>"
               f'<Url type="text/html" template="{base}/search?q={{searchTerms}}"/>'
               f'<Url type="application/x-suggestions+json" template="{base}/api/suggest?q={{searchTerms}}"/></OpenSearchDescription>')
        return Response(xml, media_type="application/opensearchdescription+xml")

    # ---- JSON API -------------------------------------------------------------------------
    @app.get("/api/search")
    async def api_search(request: Request, q: str = "", kind: str = "web", page: int = 1, safe: str = "moderate", t: str = ""):
        return (await svc().search(q, kind, page, safe, t, lang_of(request))).as_dict()

    @app.get("/api/suggest")
    async def api_suggest(request: Request, q: str = ""):
        """OpenSearch suggestion format: ``[query, [suggestions]]`` (what the browser omnibox expects)."""
        return JSONResponse([q, await svc().suggest(q, lang_of(request))])

    @app.get("/api/stats")
    async def api_stats():
        s = app.state.store.stats()
        s.update({"version": VERSION, "providers": svc().provider_info(), "crawl": app.state.crawler.status.as_dict(), "searches": svc().searches,
                  "offline_mode": not settings.web_enabled})
        return s

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/api/crawl")
    async def api_crawl(req: CrawlRequest):
        try:
            st = await app.state.crawler.start(req.urls, req.max_pages, req.depth, req.same_site)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return st.as_dict()

    @app.get("/api/crawl/status")
    async def api_crawl_status():
        return app.state.crawler.status.as_dict()

    @app.post("/api/crawl/stop")
    async def api_crawl_stop():
        app.state.crawler.stop()
        return {"ok": True}

    @app.post("/api/index/delete")
    async def api_delete(req: DeleteRequest):
        if req.url:
            n = await asyncio.to_thread(app.state.store.delete_url, req.url)
        elif req.host:
            n = await asyncio.to_thread(app.state.store.delete_host, req.host)
        else:
            raise HTTPException(400, "Provide url or host")
        return {"deleted": n}

    @app.post("/api/index/clear")
    async def api_clear():
        return {"deleted": await asyncio.to_thread(app.state.store.clear)}

    # ---- proxies (so results never make your browser contact third parties directly) ---------
    async def fetch_media(url: str, max_bytes: int):
        return await safe_get(app.state.http, url, max_bytes=max_bytes, allow_private=settings.allow_private, accept_types=IMG_TYPES,
                              resolver=resolver, timeout=6, headers={"Accept": "image/*"})

    def media_response(ctype: str, body: bytes, max_age: int = 3600) -> Response:
        return Response(body, media_type=ctype, headers={"Cache-Control": f"private, max-age={max_age}", "Content-Security-Policy": "sandbox; default-src 'none'"})

    @app.get("/api/img")
    async def img_proxy(u: str):
        if not settings.proxy_images:
            raise HTTPException(404)
        cached = media_cache.get(("img", u))
        if cached:
            return media_response(*cached)
        try:
            r = await fetch_media(u, 6_000_000)
        except (UnsafeURL, FetchError):
            raise HTTPException(404)
        if r.status != 200 or r.truncated or not r.body or r.content_type not in IMG_TYPES:
            raise HTTPException(404)
        if len(r.body) < 600_000:
            media_cache.set(("img", u), (r.content_type, r.body))
        return media_response(r.content_type, r.body)

    @app.get("/api/favicon")
    async def favicon(host: str):
        host = host.lower().strip()
        if not settings.favicons or not HOST_RE.match(host) or "." not in host:
            raise HTTPException(404)
        cached = media_cache.get(("fav", host))
        if cached is not None:
            if cached == b"":
                raise HTTPException(404)
            return media_response(*cached, max_age=86400)
        try:
            r = await fetch_media(f"https://{host}/favicon.ico", 100_000)
            ok = r.status == 200 and r.body and r.content_type in IMG_TYPES and not r.truncated
        except (UnsafeURL, FetchError):
            ok = False
        if not ok:
            media_cache.set(("fav", host), b"")
            raise HTTPException(404)
        media_cache.set(("fav", host), (r.content_type, r.body))
        return media_response(r.content_type, r.body, 86400)

    return app
