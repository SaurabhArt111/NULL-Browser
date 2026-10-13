"""Central configuration: every tunable lives here and is read from env vars.

Nothing outside this module reads ``os.environ`` (apart from tests), so the
full list of knobs is documented in one place (see README.md).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ENGINE_DIR, "src")
TEMPLATES_DIR = os.path.join(SRC_DIR, "templates")

LOOPBACK_HOST = "127.0.0.1"  # The server never binds anywhere else.

DEFAULT_PROVIDERS = ("duckduckgo", "wikipedia", "openverse", "wikimedia", "gnews")


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(str(env.get(name, "")).strip())
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _float(env: Mapping[str, str], name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(str(env.get(name, "")).strip())
    except ValueError:
        return default
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings. Build with :meth:`from_env`."""

    port: int = 8000
    data_dir: str = os.path.join(ENGINE_DIR, "data")
    db_filename: str = "index.sqlite3"

    # --- network behaviour -------------------------------------------------
    web_enabled: bool = True              # NULL_SEARCH_OFFLINE=1 disables every external provider
    providers: tuple = DEFAULT_PROVIDERS  # NULL_SEARCH_PROVIDERS=duckduckgo,wikipedia,brave,...
    brave_api_key: str = ""
    searxng_url: str = ""
    google_api_key: str = ""
    google_cse_id: str = ""
    provider_timeout: float = 4.5         # per provider request, seconds
    web_budget: float = 4.5               # hard wall for a whole federated search
    web_soft_budget: float = 2.5          # stop waiting for stragglers once someone answered
    suggest_budget_ms: int = 300          # hard budget for provider suggestions
    cache_ttl: int = 300                  # provider result cache TTL (s)
    cache_size: int = 256
    # --- ranking -------------------------------------------------------------
    per_page: int = 10
    image_per_page: int = 30
    news_per_page: int = 12
    max_per_host: int = 2
    local_boost: float = 1.6
    # --- crawler -------------------------------------------------------------
    allow_private: bool = False           # NULL_SEARCH_ALLOW_PRIVATE=1 (testing only!)
    crawl_delay: float = 0.6
    crawl_threads: int = 4
    crawl_max_pages: int = 500
    crawl_max_bytes: int = 2_000_000
    # --- privacy / misc ------------------------------------------------------
    log_queries: bool = False
    remember_recent: bool = False         # in-memory only, never written to disk
    favicons: bool = True                 # fetch site favicons through the local proxy
    proxy_images: bool = True
    log_level: str = "INFO"
    allowed_hosts: tuple = ("127.0.0.1", "localhost", "[::1]", "::1")

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, self.db_filename)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        providers = tuple(
            p.strip().lower() for p in env.get("NULL_SEARCH_PROVIDERS", "").split(",") if p.strip()
        ) or DEFAULT_PROVIDERS
        brave = env.get("BRAVE_API_KEY", "").strip()
        searx = env.get("NULL_SEARCH_SEARXNG_URL", "").strip()
        gkey = env.get("GOOGLE_API_KEY", "").strip()
        gcse = env.get("GOOGLE_CSE_ID", "").strip()
        # Keyed / self-hosted providers switch on automatically when configured.
        auto = list(providers)
        for name, active in (("brave", brave), ("searxng", searx), ("google", gkey and gcse)):
            if active and name not in auto and "NULL_SEARCH_PROVIDERS" not in env:
                auto.append(name)
        extra_hosts = tuple(h.strip().lower() for h in env.get("NULL_SEARCH_ALLOWED_HOSTS", "").split(",") if h.strip())
        return cls(
            port=_int(env, "NULL_SEARCH_PORT", 8000, 1, 65535),
            data_dir=env.get("NULL_SEARCH_DATA_DIR") or os.path.join(ENGINE_DIR, "data"),
            web_enabled=not _bool(env, "NULL_SEARCH_OFFLINE", False),
            providers=tuple(auto),
            brave_api_key=brave,
            searxng_url=searx.rstrip("/"),
            google_api_key=gkey,
            google_cse_id=gcse,
            provider_timeout=_float(env, "NULL_SEARCH_PROVIDER_TIMEOUT", 4.5, 0.5, 15),
            web_budget=_float(env, "NULL_SEARCH_WEB_BUDGET", 4.5, 0.5, 20),
            web_soft_budget=_float(env, "NULL_SEARCH_WEB_SOFT_BUDGET", 2.5, 0.2, 20),
            suggest_budget_ms=_int(env, "NULL_SEARCH_SUGGEST_BUDGET_MS", 300, 0, 350),
            cache_ttl=_int(env, "NULL_SEARCH_CACHE_TTL", 300, 0, 86400),
            allow_private=_bool(env, "NULL_SEARCH_ALLOW_PRIVATE", False),
            crawl_delay=_float(env, "NULL_SEARCH_CRAWL_DELAY", 0.6, 0.0, 30),
            log_queries=_bool(env, "NULL_SEARCH_LOG_QUERIES", False),
            remember_recent=_bool(env, "NULL_SEARCH_RECENT", False),
            favicons=_bool(env, "NULL_SEARCH_FAVICONS", True),
            proxy_images=_bool(env, "NULL_SEARCH_PROXY_IMAGES", True),
            log_level=env.get("NULL_SEARCH_LOG_LEVEL", "INFO").upper(),
            allowed_hosts=cls.allowed_hosts + extra_hosts,
        )
