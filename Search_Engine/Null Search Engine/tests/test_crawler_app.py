import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient
from Engine.app import create_app
from Engine.config import Settings
from Engine.crawler import Crawler
from Engine.store import Store
from Engine.text import parse_query

PAGES = {
    "/": '<html><head><title>Home</title></head><body><main><h1>Welcome to the garden</h1><a href="/a">A</a><a href="/secret">S</a><a href="https://other.example/x">ext</a></main></body></html>',
    "/a": '<html><head><title>Roses</title><meta name="description" content="About roses"></head><body><p>Roses are red and fragrant</p><a href="/b">B</a></body></html>',
    "/b": '<html><head><title>Tulips</title></head><body><p>Tulips bloom in spring</p></body></html>',
    "/noidx": '<html><head><title>X</title><meta name="robots" content="noindex"></head><body>hidden</body></html>',
    "/secret": '<html><head><title>Secret</title></head><body>should be skipped by robots</body></html>',
}
SEEN = []


def site(req: httpx.Request):
    SEEN.append(str(req.url))
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /secret\n")
    if req.url.host != "site.example":
        return httpx.Response(404)
    body = PAGES.get(req.url.path)
    return httpx.Response(200 if body else 404, headers={"content-type": "text/html; charset=utf-8"}, content=(body or "").encode())


async def pub(host, port):
    return ["93.184.216.34"]


def mk(tmp=None, handler=site, **kw):
    s = Settings(data_dir=":memory:", crawl_delay=0.0, crawl_threads=3, **kw)
    store = Store(":memory:")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return s, store, client, Crawler(store, s, client, pub)


def test_crawl_respects_robots_scope_depth():
    async def go():
        s, store, client, c = mk()
        await c.start(["https://site.example/"], max_pages=10, depth=2)
        await c.wait()
        await client.aclose()
        return c.status, store
    st, store = asyncio.run(go())
    urls = {r["url"] for r in store.recent(50)}
    assert urls == {"https://site.example/", "https://site.example/a", "https://site.example/b"}
    assert st.message == "done" and not st.running and st.pages_indexed == 3
    assert not any("/secret" in u and "robots" not in u for u in SEEN) and not any("other.example" in u for u in SEEN)
    assert store.search(parse_query("roses fragrant"))[0][0].title == "Roses"


def test_depth_zero_and_max_pages_and_noindex():
    async def go():
        s, store, client, c = mk()
        await c.start(["https://site.example/"], max_pages=10, depth=0)
        await c.wait()
        n0 = store.count()
        s2, store2, client2, c2 = mk()
        await c2.start(["https://site.example/"], max_pages=2, depth=3)
        await c2.wait()
        s3, store3, client3, c3 = mk()
        await c3.start(["https://site.example/noidx"], max_pages=5, depth=0)
        await c3.wait()
        return n0, store2.count(), store3.count()
    n0, n2, n3 = asyncio.run(go())
    assert (n0, n2, n3) == (1, 2, 0)


def test_private_seeds_rejected_and_single_job():
    async def go():
        s, store, client, c = mk()
        with pytest.raises(ValueError):
            await c.start(["http://127.0.0.1/", "http://192.168.1.1/", "http://localhost:8000/"])
        await c.start(["https://site.example/"], 5, 1)
        with pytest.raises(RuntimeError):
            await c.start(["https://site.example/"], 5, 1)
        await c.wait()
    asyncio.run(go())


def test_stop():
    async def slow(req):
        await asyncio.sleep(0.2)
        return site(req)

    async def go():
        s, store, client, c = mk(handler=slow)
        await c.start(["https://site.example/"], 50, 3)
        await asyncio.sleep(0.1)
        c.stop()
        await asyncio.wait_for(c.wait(), 5)
        return c.status
    assert asyncio.run(go()).message == "stopped"


# ------------------------------------------------------------------------------------------ app
@pytest.fixture
def client(tmp_path):
    s = Settings(data_dir=str(tmp_path), providers=(), web_enabled=False)
    app = create_app(s, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))), resolver=pub)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


H = {"X-Null-Search": "1"}


def test_pages_and_api_contract(client):
    assert client.get("/").status_code == 200
    st = client.get("/api/stats").json()
    assert st["documents"] == 0 and "providers" in st                     # the browser reads .documents
    sug = client.get("/api/suggest?q=ab").json()
    assert sug[0] == "ab" and isinstance(sug[1], list)                    # OpenSearch format for the omnibox
    assert client.get("/search?q=2%2B2").text.count("4") > 0
    assert client.get("/search").status_code in (200, 302)
    assert client.get("/opensearch.xml").status_code == 200
    r = client.get("/api/search?q=hello")
    assert r.status_code == 200 and r.json()["query"] == "hello"


def test_security_headers_and_host_check(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/", headers={"Host": "127.0.0.1.evil.example"}).status_code == 403


def test_post_requires_custom_header_and_same_origin(client):
    assert client.post("/api/index/clear").status_code == 403
    assert client.post("/api/index/clear", headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/index/clear", headers={**H, "Origin": "http://127.0.0.1:8000"}).status_code == 200


def test_xss_escaped_in_results(client):
    r = client.get("/search", params={"q": '"><script>alert(1)</script>'})
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_proxies_refuse_private_and_cross_site(client):
    assert client.get("/api/img", params={"u": "http://127.0.0.1:8000/healthz"}).status_code == 404
    assert client.get("/api/img", params={"u": "http://169.254.169.254/"}).status_code == 404
    assert client.get("/api/img", params={"u": "file:///etc/passwd"}).status_code == 404
    assert client.get("/api/favicon", params={"host": "127.0.0.1"}).status_code == 404
    assert client.get("/api/favicon", params={"host": "../etc"}).status_code == 404
    assert client.get("/api/img", params={"u": "https://x.example/a.png"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_crawl_api_validation(client):
    assert client.post("/api/crawl", json={"urls": ["http://10.0.0.1/"]}, headers=H).status_code == 400
    assert client.post("/api/crawl", json={"urls": [], "max_pages": 0}, headers=H).status_code == 422
    assert client.get("/api/crawl/status").json()["running"] is False
    assert client.get("/index").status_code == 200
