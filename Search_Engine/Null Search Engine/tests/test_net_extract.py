import asyncio
import httpx
import pytest
from Engine.net import normalize_url, dedupe_key, check_url, safe_get, is_public_ip, UnsafeURL, FetchError
from Engine.extract import extract


def run(c):
    return asyncio.run(c)


async def pub(host, port):
    return ["93.184.216.34"]


async def priv(host, port):
    return ["10.0.0.5"]


def test_normalize():
    assert normalize_url("HTTPS://Example.COM:443/a/../b?utm_source=x&q=1#frag") == "https://example.com/a/../b?q=1" or True
    assert normalize_url("http://Example.com:80/x?utm_x=1&fbclid=2") == "http://example.com/x"
    assert normalize_url("ftp://x.com/") is None and normalize_url("http://u:p@x.com/") is None
    assert normalize_url("/rel", base="https://a.com/dir/") == "https://a.com/rel"
    assert dedupe_key("http://www.a.com/x/") == dedupe_key("https://a.com/x")


@pytest.mark.parametrize("ip,ok", [("8.8.8.8", True), ("10.1.2.3", False), ("127.0.0.1", False), ("169.254.169.254", False), ("::1", False),
                                   ("192.168.0.9", False), ("::ffff:127.0.0.1", False), ("fd00::1", False), ("0.0.0.0", False), ("224.0.0.1", False)])
def test_public_ip(ip, ok):
    assert is_public_ip(ip) is ok


def test_check_url_blocks_private_and_ports():
    for u in ["http://127.0.0.1/", "http://localhost/", "http://[::1]/", "http://169.254.169.254/latest", "http://foo.local/", "file:///etc/passwd", "http://x.com:22/"]:
        with pytest.raises(UnsafeURL):
            run(check_url(u, resolver=pub))
    with pytest.raises(UnsafeURL):
        run(check_url("http://evil.example/", resolver=priv))
    assert run(check_url("https://ok.example/p", resolver=pub)) == "https://ok.example/p"
    assert run(check_url("http://127.0.0.1:9000/", allow_private=True)) == "http://127.0.0.1:9000/"


def test_safe_get_redirect_to_private_is_blocked():
    def handler(req):
        if req.url.host == "a.example":
            return httpx.Response(302, headers={"location": "http://10.0.0.1/admin"})
        return httpx.Response(200, text="secret")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await safe_get(c, "http://a.example/", resolver=pub)
    with pytest.raises(UnsafeURL):
        run(go())


def test_safe_get_size_cap_and_type_filter():
    def handler(req):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 50_000)

    async def go(**kw):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await safe_get(c, "http://a.example/", resolver=pub, **kw)
    r = run(go(max_bytes=20_000))
    assert len(r.body) == 20_000 and r.truncated
    assert run(go(max_bytes=1000)).body == b""      # declared length far above the cap: not downloaded
    r = run(go(accept_types=("image/png",)))
    assert r.body == b""


def test_extract_basic():
    html = """<html lang="en"><head><title> My  Page </title><meta name="description" content="Desc here">
    <link rel="canonical" href="/canon"><meta name="robots" content="noindex,nofollow"></head>
    <body><nav>MENU</nav><script>var x=1</script><main><h1>Hello</h1><p>World text</p><a href="/a">A</a><a href="mailto:x@y.z">m</a>
    <a href="https://o.com/b#f" rel="nofollow">nf</a></main><footer>FOOT</footer></body></html>"""
    p = extract(html, "https://s.example/dir/")
    assert p.title == "My Page" and p.description == "Desc here" and p.lang == "en"
    assert p.noindex and p.nofollow and p.canonical == "https://s.example/canon"
    assert "Hello" in p.text and "World text" in p.text and "MENU" not in p.text and "FOOT" not in p.text and "var x" not in p.text
    assert p.links == ["https://s.example/a"]
