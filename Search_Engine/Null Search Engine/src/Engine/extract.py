"""HTML -> searchable text. Pulls title, description, language, links and the main body text."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup, UnicodeDammit

from .net import normalize_url

_DROP = ("script", "style", "noscript", "template", "svg", "canvas", "iframe", "form", "select", "button", "input", "head")
_BOILER = re.compile(r"(^|[-_ ])(nav|navbar|menu|footer|sidebar|cookie|consent|banner|breadcrumb|popup|modal|advert|ads?)([-_ ]|$)", re.I)
_WS = re.compile(r"\s+")


@dataclass
class Page:
    title: str = ""
    description: str = ""
    text: str = ""
    lang: str = ""
    canonical: Optional[str] = None
    noindex: bool = False
    nofollow: bool = False
    links: List[str] = field(default_factory=list)


def decode(body: bytes, content_type_header: str = "") -> str:
    charset = None
    m = re.search(r"charset=([\w\-]+)", content_type_header or "", re.I)
    if m:
        charset = m.group(1)
    d = UnicodeDammit(body, known_definite_encodings=[charset] if charset else None, is_html=True)
    return d.unicode_markup or body.decode("utf-8", "replace")


def extract(html: str, base_url: str, max_links: int = 200) -> Page:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    page = Page()
    page.title = _WS.sub(" ", (soup.title.get_text(" ") if soup.title else "")).strip()[:300]
    root = soup.find("html")
    page.lang = ((root.get("lang") if root else "") or "")[:12].lower() if root else ""

    def meta(name: str) -> str:
        t = soup.find("meta", attrs={"name": re.compile(f"^{name}$", re.I)}) or soup.find("meta", attrs={"property": re.compile(f"^{name}$", re.I)})
        return (t.get("content") or "").strip() if t else ""

    page.description = _WS.sub(" ", meta("description") or meta("og:description")).strip()[:500]
    if not page.title:
        page.title = _WS.sub(" ", meta("og:title")).strip()[:300]
    robots = meta("robots").lower() + " " + meta("googlebot").lower()
    page.noindex = "noindex" in robots
    page.nofollow = "nofollow" in robots
    can = soup.find("link", rel="canonical")
    if can and can.get("href"):
        page.canonical = normalize_url(can["href"], base=base_url)

    seen = set()
    for a in soup.find_all("a", href=True):
        if len(page.links) >= max_links:
            break
        if "nofollow" in (a.get("rel") or []):
            continue
        n = normalize_url(a["href"], base=base_url)
        if n and n not in seen:
            seen.add(n)
            page.links.append(n)

    for t in soup.find_all(_DROP):
        t.decompose()
    for t in soup.find_all(["nav", "footer", "aside"]):
        t.decompose()
    for t in soup.find_all(attrs={"class": _BOILER}):
        if t.name not in ("body", "html", "main", "article"):
            t.decompose()
    for t in soup.find_all(attrs={"id": _BOILER}):
        if t.name not in ("body", "html", "main", "article"):
            t.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = _WS.sub(" ", main.get_text(" ")).strip()
    page.text = text
    return page
