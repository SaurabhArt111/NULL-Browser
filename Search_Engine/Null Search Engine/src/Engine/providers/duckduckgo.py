"""DuckDuckGo HTML endpoint (keyless). Parsed defensively; bot-wall pages raise ProviderError."""
from __future__ import annotations

from typing import List
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

from .base import Provider, ProviderError, Query, Result, clean_text

SAFE = {"off": "-2", "moderate": "-1", "strict": "1"}


def unwrap(href: str) -> str:
    """DDG wraps links as //duckduckgo.com/l/?uddg=<real url>."""
    if href.startswith("//"):
        href = "https:" + href
    p = urlsplit(href)
    if p.hostname and p.hostname.endswith("duckduckgo.com") and p.path.startswith("/l/"):
        v = parse_qs(p.query).get("uddg")
        if v:
            return unquote(v[0])
    return href


class DuckDuckGo(Provider):
    name = "duckduckgo"
    kinds = ("web",)
    weight = 1.0

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:
        data = {"q": q.q, "kp": SAFE.get(q.safe, "-1"), "kl": "wt-wt"}
        if q.time in ("d", "w", "m", "y"):
            data["df"] = q.time
        if q.page > 1:
            data["s"] = str((q.page - 1) * 30 - 20 if q.page > 1 else 0)
            data["dc"] = str((q.page - 1) * 30 + 1)
        r = await client.post("https://html.duckduckgo.com/html/", data=data, headers={"Accept-Language": q.lang})
        if r.status_code in (202, 429) or "anomaly" in r.text[:4000].lower():
            raise ProviderError("bot check / rate limit")
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}")
        return parse(r.text, q.count)

    async def suggest(self, client, prefix, lang="en"):
        r = await client.get("https://duckduckgo.com/ac/", params={"q": prefix, "type": "list"})
        d = self.json(r)
        return [s for s in d[1] if isinstance(s, str)] if isinstance(d, list) and len(d) > 1 else []


def parse(html_text: str, limit: int = 10) -> List[Result]:
    soup = BeautifulSoup(html_text, "lxml")
    out: List[Result] = []
    for node in soup.select("div.result, div.web-result"):
        if "result--ad" in (node.get("class") or []):
            continue
        a = node.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        url = unwrap(a["href"])
        if not url.startswith(("http://", "https://")) or "duckduckgo.com/y.js" in url:
            continue
        sn = node.select_one(".result__snippet")
        out.append(Result(title=clean_text(a.get_text()), url=url, snippet=clean_text(sn.get_text()) if sn else "", source="duckduckgo",
                          rank=len(out) + 1))
        if len(out) >= limit:
            break
    return out
