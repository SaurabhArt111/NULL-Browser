import asyncio
import json
import httpx
import pytest
from Engine.config import Settings
from Engine.store import Store, Doc
from Engine.service import SearchService
from Engine import providers as prov
from Engine.providers.duckduckgo import DuckDuckGo, parse as ddg_parse, unwrap
from Engine.providers.media import parse_rss
from Engine.providers.base import ProviderError, Query

DDG_HTML = """<html><body>
<div class="result results_links web-result"><h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpage%3Fa%3D1&rut=x">Example <b>Page</b></a></h2>
<a class="result__snippet">A <b>snippet</b> about things.</a></div>
<div class="result result--ad"><a class="result__a" href="https://ads.example/">AD</a></div>
<div class="result"><a class="result__a" href="https://second.example/">Second</a><a class="result__snippet">Another</a></div></body></html>"""

WIKI = {"query": {"search": [{"title": "Python (programming language)", "snippet": 'The <span class="searchmatch">Python</span> language'}]}}
SUMMARY = {"type": "standard", "title": "Python (programming language)", "description": "General-purpose language", "extract": "Python is a high-level language.",
           "thumbnail": {"source": "https://upload.wikimedia.org/p.jpg"}, "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python"}}}
RSS = b"""<?xml version="1.0"?><rss><channel><item><title>Big news - Daily Planet</title><link>https://news.example/a</link><pubDate>Tue, 13 Oct 2026 08:00:00 GMT</pubDate><source url="x">Daily Planet</source></item></channel></rss>"""


def handler(req: httpx.Request):
    h, p = req.url.host, req.url.path
    if h == "html.duckduckgo.com":
        return httpx.Response(200, text=DDG_HTML)
    if h == "en.wikipedia.org" and p == "/w/api.php":
        return httpx.Response(200, json=WIKI)
    if h == "en.wikipedia.org" and p.startswith("/api/rest_v1/page/summary"):
        return httpx.Response(200, json=SUMMARY)
    if h == "news.google.com":
        return httpx.Response(200, content=RSS)
    if h == "api.openverse.org":
        return httpx.Response(200, json={"results": [{"title": "Cat", "foreign_landing_url": "https://img.example/cat", "url": "https://img.example/cat.jpg",
                                                      "thumbnail": "https://img.example/t.jpg", "width": 800, "height": 600, "license": "by"}]})
    return httpx.Response(404)


def make(handler_fn=handler, **kw):
    s = Settings(data_dir=":memory:", providers=("duckduckgo", "wikipedia", "openverse", "gnews"), **kw)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler_fn))
    store = Store(":memory:")
    return SearchService(s, store, client), store, client


def test_ddg_parsing():
    out = ddg_parse(DDG_HTML)
    assert [r.url for r in out] == ["https://example.org/page?a=1", "https://second.example/"]
    assert out[0].title == "Example Page" and out[0].snippet == "A snippet about things."
    assert unwrap("https://plain.example/") == "https://plain.example/"


def test_rss():
    r = parse_rss(RSS)
    assert r[0].title == "Big news" and r[0].publisher == "Daily Planet"
    with pytest.raises(ProviderError):
        parse_rss(b"not xml at all <<<")
    assert parse_rss(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]><rss><channel><item><title>&a;</title><link>https://x.example/</link></item></channel></rss>')[0].title != "boom"


def test_search_fuses_local_and_web_with_panel():
    async def go():
        svc, store, client = make()
        store.upsert(Doc(url="https://example.org/page?a=1", title="Local copy", body="python things in my notes about python"))
        r = await svc.search("python", "web")
        await client.aclose()
        return r
    r = asyncio.run(go())
    urls = [x["url"] for x in r.results]
    assert "https://example.org/page?a=1" in urls and r.results[0]["url"] == "https://example.org/page?a=1"      # local + ddg agree -> top
    assert set(r.results[0]["sources"]) >= {"local", "duckduckgo"}
    assert r.panel and r.panel["title"].startswith("Python")
    assert r.providers["duckduckgo"] == "ok" and r.notice == ""
    assert any(b for seg in r.results[0]["snippet"] for _, b in [seg])                                   # highlighted terms


def test_images_news_and_page_clamp():
    async def go():
        svc, _, client = make()
        a = await svc.search("cat", "images")
        b = await svc.search("election", "news", page=999)
        await client.aclose()
        return a, b
    a, b = asyncio.run(go())
    assert a.results[0]["image"].endswith("cat.jpg") and b.results[0]["publisher"] == "Daily Planet" and b.page == 20


def test_offline_notice_and_breaker():
    calls = {"n": 0}

    def boom(req):
        calls["n"] += 1
        raise httpx.ConnectError("offline")

    async def go():
        svc, store, client = make(boom)
        store.upsert(Doc(url="https://a.example/", title="alpha", body="alpha beta"))
        rs = [await svc.search(f"alpha {i}") for i in range(5)]
        loc = await svc.search("alpha")
        await client.aclose()
        return rs, loc, svc
    rs, loc, svc = asyncio.run(go())
    assert rs[0].notice in ("offline", "partial") and loc.results and loc.results[0]["local"]
    assert all(b.is_open for b in svc.breakers.values() if b is not None) or calls["n"] < 5 * 2   # breaker stops hammering


def test_slow_provider_does_not_block():
    async def slow(req):
        if req.url.host == "html.duckduckgo.com":
            await asyncio.sleep(5)
        return handler(req)

    async def go():
        svc, _, client = make(slow, web_budget=3.0, web_soft_budget=0.3, provider_timeout=4.0)
        import time
        t = time.perf_counter()
        r = await svc.search("python")
        await client.aclose()
        return r, time.perf_counter() - t
    r, dt = asyncio.run(go())
    assert dt < 2.0 and r.providers["duckduckgo"] == "timeout" and r.providers["wikipedia"] == "ok"


def test_suggest_merges_sources():
    def h(req):
        if req.url.host == "duckduckgo.com":
            return httpx.Response(200, json=["py", ["python", "pytorch"]])
        if req.url.path == "/w/api.php":
            return httpx.Response(200, json=["py", ["Python (language)"]])
        return httpx.Response(404)

    async def go():
        svc, store, client = make(h)
        store.upsert(Doc(url="https://a.example/", title="Python tips", body="x"))
        r = await svc.suggest("py")
        await client.aclose()
        return r
    r = asyncio.run(go())
    assert "Python tips" in r and "python" in r and "pytorch" in r and len(r) == len(set(x.lower() for x in r))


def test_settings_env():
    s = Settings.from_env({"NULL_SEARCH_PORT": "9123", "BRAVE_API_KEY": "k", "NULL_SEARCH_OFFLINE": "1"})
    assert s.port == 9123 and "brave" in s.providers and not s.web_enabled
    assert prov.build(s) == {}
    assert Settings.from_env({"NULL_SEARCH_PORT": "bad"}).port == 8000
