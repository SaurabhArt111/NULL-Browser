"""Result fusion: Reciprocal Rank Fusion across providers + the local index, de-duplication, host diversity."""
from __future__ import annotations

from typing import Dict, List
from urllib.parse import urlsplit

from .net import dedupe_key
from .providers.base import Result
from .text import words

RRF_K = 60.0


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def fuse(lists: Dict[str, List[Result]], weights: Dict[str, float], query_terms: List[str], max_per_host: int = 2, local_boost: float = 1.6,
         limit: int = 10) -> List[Result]:
    """Merge ranked lists. Each result earns ``weight / (k + rank)`` from every list that contains it.

    Agreement between independent sources is therefore rewarded; a result found by three engines beats one found
    at rank 1 by a single engine. A small title-match prior breaks ties, and at most ``max_per_host`` results per
    site are kept on the first screen (extra ones are demoted, not dropped).
    """
    merged: Dict[str, Result] = {}
    for name, results in lists.items():
        w = weights.get(name, 1.0) * (local_boost if name == "local" else 1.0)
        for i, r in enumerate(results):
            if not r.url:
                continue
            key = dedupe_key(r.url)
            gain = w / (RRF_K + (r.rank or i + 1))
            cur = merged.get(key)
            if cur is None:
                cur = Result(title=r.title, url=r.url, snippet=r.snippet, source=name, sources=[name], local=name == "local",
                             thumb=r.thumb, image=r.image, width=r.width, height=r.height, published=r.published, publisher=r.publisher,
                             extra=dict(r.extra))
                merged[key] = cur
            else:
                if name not in cur.sources:
                    cur.sources.append(name)
                if len(r.snippet) > len(cur.snippet) and len(r.snippet) <= 400:
                    cur.snippet = r.snippet
                if len(r.title) > len(cur.title) and len(r.title) <= 140 and not cur.title:
                    cur.title = r.title
                if r.url.startswith("https://") and cur.url.startswith("http://"):
                    cur.url = r.url
                cur.local = cur.local or name == "local"
                cur.thumb = cur.thumb or r.thumb
                cur.image = cur.image or r.image
                cur.published = cur.published or r.published
                cur.publisher = cur.publisher or r.publisher
            cur.score += gain
    terms = [t for t in query_terms if len(t) > 1]
    for r in merged.values():
        if terms:
            tw = set(words(r.title))
            r.score += 0.004 * sum(1 for t in terms if t in tw) / len(terms)
        if r.url.startswith("https://"):
            r.score += 0.0005
    ordered = sorted(merged.values(), key=lambda r: r.score, reverse=True)
    return diversify(ordered, max_per_host)[:limit] if limit else diversify(ordered, max_per_host)


def diversify(results: List[Result], max_per_host: int) -> List[Result]:
    if max_per_host <= 0:
        return results
    kept, demoted, count = [], [], {}
    for r in results:
        h = _host(r.url)
        count[h] = count.get(h, 0) + 1
        (kept if count[h] <= max_per_host else demoted).append(r)
    return kept + demoted
