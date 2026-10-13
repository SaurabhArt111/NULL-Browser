"""Provider registry."""
from __future__ import annotations

from typing import Dict, List

from .base import Provider, ProviderError, Query, Result
from .duckduckgo import DuckDuckGo
from .keyed import Brave, GoogleCSE, SearxNG
from .media import GoogleNewsRSS, Openverse, WikimediaCommons
from .wikipedia import Wikipedia

ALL = {c.name: c for c in (DuckDuckGo, Wikipedia, Brave, SearxNG, GoogleCSE, Openverse, WikimediaCommons, GoogleNewsRSS)}


def build(settings) -> Dict[str, Provider]:
    """Instantiate every enabled provider named in ``settings.providers``."""
    out: Dict[str, Provider] = {}
    if not settings.web_enabled:
        return out
    for name in settings.providers:
        cls = ALL.get(name)
        if cls:
            p = cls(settings)
            if p.enabled():
                out[name] = p
    return out


__all__ = ["Provider", "ProviderError", "Query", "Result", "ALL", "build"]
