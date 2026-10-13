"""Keyless image and news sources: Openverse + Wikimedia Commons (images), Google News RSS (news)."""
from __future__ import annotations

from typing import List
from urllib.parse import quote

import httpx
from lxml import etree

from .base import Provider, ProviderError, Query, Result, clean_text


class Openverse(Provider):
    name = "openverse"
    kinds = ("images",)
    weight = 1.0

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        r = await client.get("https://api.openverse.org/v1/images/", params={
            "q": q.q, "page": q.page, "page_size": min(q.count, 30), "mature": "true" if q.safe == "off" else "false"})
        d = self.json(r)
        out = []
        for i, it in enumerate(d.get("results", [])):
            out.append(Result(title=clean_text(it.get("title") or ""), url=it.get("foreign_landing_url") or "", source="openverse", rank=i + 1,
                              image=it.get("url", ""), thumb=it.get("thumbnail", ""), width=int(it.get("width") or 0), height=int(it.get("height") or 0),
                              publisher=it.get("provider", "") or it.get("source", ""), extra={"license": (it.get("license") or "").upper()}))
        return [x for x in out if x.url.startswith("http") and (x.image or x.thumb)]


class WikimediaCommons(Provider):
    name = "wikimedia"
    kinds = ("images",)
    weight = 0.9

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        r = await client.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "generator": "search", "gsrnamespace": 6, "gsrsearch": q.q, "gsrlimit": min(q.count, 30),
            "gsroffset": (q.page - 1) * q.count, "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 360, "format": "json", "formatversion": 2})
        d = self.json(r)
        pages = sorted(d.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
        out = []
        for i, p in enumerate(pages):
            info = (p.get("imageinfo") or [{}])[0]
            if not str(info.get("mime", "")).startswith("image/") or "svg" in str(info.get("mime", "")):
                continue
            out.append(Result(title=clean_text(p.get("title", "").replace("File:", "").rsplit(".", 1)[0]), url=info.get("descriptionurl", ""),
                              source="wikimedia", rank=i + 1, image=info.get("url", ""), thumb=info.get("thumburl", ""),
                              width=int(info.get("width") or 0), height=int(info.get("height") or 0), publisher="Wikimedia Commons"))
        return [x for x in out if x.url.startswith("http")]


class GoogleNewsRSS(Provider):
    name = "gnews"
    kinds = ("news",)
    weight = 1.0

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        lang = q.lang.split("-")[0].lower()
        query = q.q + ({"d": " when:1d", "w": " when:7d", "m": " when:30d", "y": " when:365d"}.get(q.time, ""))
        r = await client.get("https://news.google.com/rss/search", params={"q": query, "hl": lang, "gl": "US", "ceid": f"US:{lang}"})
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}")
        return parse_rss(r.content, q.count)


def parse_rss(content: bytes, limit: int = 12) -> List[Result]:
    try:
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True))
    except etree.XMLSyntaxError as e:
        raise ProviderError("bad RSS") from e
    if root is None:
        raise ProviderError("bad RSS")
    out: List[Result] = []
    for i, it in enumerate(root.iter("item")):
        def g(tag):
            el = it.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        src = it.find("source")
        title = clean_text(g("title"))
        publisher = (src.text or "").strip() if src is not None and src.text else ""
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(publisher) - 3]
        out.append(Result(title=title, url=g("link"), snippet="", source="gnews", rank=i + 1, published=g("pubDate"), publisher=publisher))
        if len(out) >= limit:
            break
    return [x for x in out if x.url.startswith("http")]
