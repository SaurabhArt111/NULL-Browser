"""Provider interface shared by all search back-ends."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class ProviderError(Exception):
    """Raised for rate limits, bot walls, bad payloads - anything that should open the circuit breaker."""


@dataclass
class Result:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    sources: List[str] = field(default_factory=list)
    rank: int = 0
    score: float = 0.0
    local: bool = False
    # media / news extras
    thumb: str = ""
    image: str = ""
    width: int = 0
    height: int = 0
    published: str = ""
    publisher: str = ""
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class Query:
    q: str
    kind: str = "web"          # web | images | news
    page: int = 1
    lang: str = "en"
    safe: str = "moderate"     # off | moderate | strict
    time: str = ""             # "" | d | w | m | y
    count: int = 10


def clean_text(s: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub("", s or ""))).strip()


class Provider:
    name = "base"
    kinds = ("web",)
    weight = 1.0
    needs_key = False

    def __init__(self, settings):
        self.settings = settings

    def enabled(self) -> bool:
        return True

    async def search(self, client: httpx.AsyncClient, q: Query) -> List[Result]:  # pragma: no cover - interface
        raise NotImplementedError

    async def suggest(self, client: httpx.AsyncClient, prefix: str, lang: str = "en") -> List[str]:
        return []

    def key(self, q: Query) -> tuple:
        return (self.name, q.kind, q.q.lower(), q.page, q.lang, q.safe, q.time)

    @staticmethod
    def json(r: httpx.Response):
        if r.status_code == 429:
            raise ProviderError("rate limited")
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError("bad JSON") from e
