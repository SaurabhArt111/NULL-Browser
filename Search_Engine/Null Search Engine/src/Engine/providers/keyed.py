"""Optional back-ends that need a key or your own server: Brave Search API, SearxNG, Google Programmable Search."""
from __future__ import annotations

from typing import List

import httpx

from .base import Provider, ProviderError, Query, Result, clean_text

BRAVE_SAFE = {"off": "off", "moderate": "moderate", "strict": "strict"}
BRAVE_FRESH = {"d": "pd", "w": "pw", "m": "pm", "y": "py"}


class Brave(Provider):
    name = "brave"
    kinds = ("web", "images", "news")
    weight = 1.25
    needs_key = True

    def enabled(self):
        return bool(self.settings.brave_api_key)

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        ep = {"web": "web", "images": "images", "news": "news"}[q.kind]
        params = {"q": q.q, "count": min(q.count, 20 if q.kind == "web" else 50), "offset": min(q.page - 1, 9), "safesearch": BRAVE_SAFE.get(q.safe, "moderate"),
                  "search_lang": q.lang.split("-")[0]}
        if q.time in BRAVE_FRESH:
            params["freshness"] = BRAVE_FRESH[q.time]
        r = await client.get(f"https://api.search.brave.com/res/v1/{ep}/search", params=params,
                             headers={"X-Subscription-Token": self.settings.brave_api_key, "Accept": "application/json"})
        d = self.json(r)
        out: List[Result] = []
        if q.kind == "web":
            for i, it in enumerate(d.get("web", {}).get("results", [])):
                out.append(Result(title=clean_text(it.get("title", "")), url=it.get("url", ""), snippet=clean_text(it.get("description", "")),
                                  source="brave", rank=i + 1))
        elif q.kind == "images":
            for i, it in enumerate(d.get("results", [])):
                props = it.get("properties") or {}
                out.append(Result(title=clean_text(it.get("title", "")), url=it.get("url", ""), source="brave", rank=i + 1,
                                  image=props.get("url", ""), thumb=(it.get("thumbnail") or {}).get("src", ""),
                                  width=int(props.get("width") or 0), height=int(props.get("height") or 0), publisher=it.get("source", "")))
        else:
            for i, it in enumerate(d.get("results", [])):
                out.append(Result(title=clean_text(it.get("title", "")), url=it.get("url", ""), snippet=clean_text(it.get("description", "")),
                                  source="brave", rank=i + 1, published=it.get("age", ""), thumb=(it.get("thumbnail") or {}).get("src", ""),
                                  publisher=(it.get("meta_url") or {}).get("hostname", "")))
        return [x for x in out if x.url.startswith("http")]

    async def suggest(self, client, prefix, lang="en"):
        return []


class SearxNG(Provider):
    name = "searxng"
    kinds = ("web", "images", "news")
    weight = 1.1
    needs_key = True

    def enabled(self):
        return bool(self.settings.searxng_url)

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        cat = {"web": "general", "images": "images", "news": "news"}[q.kind]
        params = {"q": q.q, "format": "json", "categories": cat, "pageno": q.page, "language": q.lang,
                  "safesearch": {"off": 0, "moderate": 1, "strict": 2}.get(q.safe, 1)}
        if q.time in ("d", "w", "m", "y"):
            params["time_range"] = {"d": "day", "w": "week", "m": "month", "y": "year"}[q.time]
        r = await client.get(self.settings.searxng_url + "/search", params=params)
        d = self.json(r)
        out = []
        for i, it in enumerate(d.get("results", [])):
            out.append(Result(title=clean_text(it.get("title", "")), url=it.get("url", ""), snippet=clean_text(it.get("content", "")), source="searxng",
                              rank=i + 1, image=it.get("img_src", "") if q.kind == "images" else "", thumb=it.get("thumbnail_src") or it.get("thumbnail") or "",
                              published=str(it.get("publishedDate") or ""), publisher=it.get("parsed_url", [None, ""])[1] if isinstance(it.get("parsed_url"), list) else ""))
        return [x for x in out if x.url.startswith("http")]


class GoogleCSE(Provider):
    name = "google"
    kinds = ("web", "images")
    weight = 1.25
    needs_key = True

    def enabled(self):
        return bool(self.settings.google_api_key and self.settings.google_cse_id)

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        params = {"key": self.settings.google_api_key, "cx": self.settings.google_cse_id, "q": q.q, "num": min(q.count, 10),
                  "start": min((q.page - 1) * 10 + 1, 91), "hl": q.lang.split("-")[0], "safe": "off" if q.safe == "off" else "active"}
        if q.kind == "images":
            params["searchType"] = "image"
        if q.time in ("d", "w", "m", "y"):
            params["dateRestrict"] = q.time + "1"
        r = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
        d = self.json(r)
        out = []
        for i, it in enumerate(d.get("items", [])):
            img = it.get("image") or {}
            out.append(Result(title=clean_text(it.get("title", "")), url=img.get("contextLink") or it.get("link", ""), snippet=clean_text(it.get("snippet", "")),
                              source="google", rank=i + 1, image=it.get("link", "") if q.kind == "images" else "", thumb=img.get("thumbnailLink", ""),
                              width=int(img.get("width") or 0), height=int(img.get("height") or 0)))
        return [x for x in out if x.url.startswith("http")]
