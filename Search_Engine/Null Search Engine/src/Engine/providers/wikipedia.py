"""Wikipedia: full-text search (keyless) + REST summary used for the knowledge panel."""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import quote

import httpx

from .base import Provider, ProviderError, Query, Result, clean_text

_LANG = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?$")


def _host(lang: str) -> str:
    lang = lang.split("-")[0].lower() if _LANG.match(lang.lower()) else "en"
    return f"https://{lang}.wikipedia.org"


class Wikipedia(Provider):
    name = "wikipedia"
    kinds = ("web",)
    weight = 0.7

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        base = _host(q.lang)
        r = await client.get(base + "/w/api.php", params={
            "action": "query", "list": "search", "srsearch": q.q, "srlimit": min(q.count, 10), "sroffset": (q.page - 1) * q.count,
            "format": "json", "utf8": 1, "srprop": "snippet"})
        d = self.json(r)
        out = []
        for i, it in enumerate(d.get("query", {}).get("search", [])):
            title = it.get("title", "")
            out.append(Result(title=f"{title} - Wikipedia", url=f"{base}/wiki/{quote(title.replace(' ', '_'), safe='_()')}",
                              snippet=clean_text(it.get("snippet", "")), source="wikipedia", rank=i + 1))
        return out

    async def suggest(self, client, prefix, lang="en"):
        r = await client.get(_host(lang) + "/w/api.php", params={"action": "opensearch", "search": prefix, "limit": 5, "format": "json"})
        d = self.json(r)
        return [s for s in d[1] if isinstance(s, str)] if isinstance(d, list) and len(d) > 1 else []

    async def summary(self, client: httpx.AsyncClient, title: str, lang: str = "en") -> Optional[dict]:
        r = await client.get(f"{_host(lang)}/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='_()')}")
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("type") != "standard" or not d.get("extract"):
            return None
        return {"title": d.get("title", title), "description": d.get("description", ""), "extract": d["extract"],
                "thumb": (d.get("thumbnail") or {}).get("source", ""), "url": (d.get("content_urls", {}).get("desktop", {}) or {}).get("page", "")}
