"""Query parsing (operators, phrases, exclusions) and snippet building.

Supported operators::

    "exact phrase"   -word   -"excluded phrase"
    site:example.com   intitle:word   inurl:word   filetype:pdf
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAX_QUERY_CHARS = 300
_WORD = re.compile(r"\w+", re.UNICODE)
_TOKEN = re.compile(r'(-?)(?:([A-Za-z]+):)?(?:"([^"]*)"|(\S+))')
_OPS = {"site", "intitle", "inurl", "filetype", "ext"}
_WS = re.compile(r"\s+")


def clean_query(q: Optional[str]) -> str:
    """Collapse whitespace, strip control characters and cap the length."""
    if not q:
        return ""
    q = "".join(ch for ch in q if ch == " " or ch.isprintable())
    return _WS.sub(" ", q).strip()[:MAX_QUERY_CHARS]


def words(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


@dataclass
class ParsedQuery:
    raw: str = ""
    terms: List[str] = field(default_factory=list)
    phrases: List[List[str]] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)          # single words
    exclude_phrases: List[List[str]] = field(default_factory=list)
    intitle: List[str] = field(default_factory=list)
    inurl: List[str] = field(default_factory=list)
    site: Optional[str] = None
    filetype: Optional[str] = None

    @property
    def positive(self) -> bool:
        return bool(self.terms or self.phrases or self.intitle or self.inurl)

    @property
    def has_filters(self) -> bool:
        return bool(self.site or self.filetype)

    @property
    def highlight(self) -> List[str]:
        out = list(self.terms) + list(self.intitle)
        for p in self.phrases:
            out.extend(p)
        seen, uniq = set(), []
        for w in out:
            if w not in seen:
                seen.add(w)
                uniq.append(w)
        return uniq

    @property
    def plain(self) -> str:
        """Free-text portion, used for instant-answer triggers and suggestions."""
        return " ".join(self.terms)


def _q(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def parse_query(raw: str) -> ParsedQuery:
    pq = ParsedQuery(raw=clean_query(raw))
    for m in _TOKEN.finditer(pq.raw):
        neg, op, phrase, word = m.group(1) == "-", (m.group(2) or "").lower(), m.group(3), m.group(4)
        text = phrase if phrase is not None else word
        if op in _OPS and text:
            if op == "site":
                host = text.lower().strip().strip("/")
                host = re.sub(r"^https?://", "", host).split("/")[0]
                if host and re.fullmatch(r"[a-z0-9.\-]+", host):
                    pq.site = host[4:] if host.startswith("www.") else host
            elif op in ("filetype", "ext"):
                ft = re.sub(r"[^a-z0-9]", "", text.lower())
                if ft:
                    pq.filetype = ft[:8]
            elif op == "intitle":
                pq.intitle.extend(words(text))
            elif op == "inurl":
                pq.inurl.extend(words(text))
            continue
        if op and word is not None:                          # "foo:bar" with an unknown operator is plain text
            text = f"{op} {word}"
        ws = words(text or "")
        if not ws:
            continue
        if phrase is not None and len(ws) > 1:
            (pq.exclude_phrases if neg else pq.phrases).append(ws)
        elif neg:
            pq.exclude.extend(ws)
        else:
            pq.terms.extend(ws)
    return pq


def fts_expression(pq: ParsedQuery, loose: bool = False) -> Optional[str]:
    """Build an FTS5 MATCH string. ``loose`` ORs the free terms (used when AND finds too little)."""
    must: List[str] = []
    if pq.terms:
        if loose and len(pq.terms) > 1:
            must.append("(" + " OR ".join(_q(t) for t in pq.terms) + ")")
        else:
            must.extend(_q(t) for t in pq.terms)
    must.extend(_q(" ".join(p)) for p in pq.phrases)
    must.extend("title : " + _q(t) for t in pq.intitle)
    must.extend("url_text : " + _q(t) for t in pq.inurl)
    if not must:
        return None
    expr = "(" + " AND ".join(must) + ")"
    neg = [_q(t) for t in pq.exclude] + [_q(" ".join(p)) for p in pq.exclude_phrases]
    if neg:
        expr += " NOT (" + " OR ".join(neg) + ")"
    return expr


# ---------------------------------------------------------------------------------- snippets

Segment = Tuple[str, bool]


def _matches(token: str, terms: List[str]) -> bool:
    t = token.lower()
    for w in terms:
        if t == w or (len(w) >= 4 and (t.startswith(w[:-1]) or w.startswith(t)) and len(t) >= 4):
            return True
    return False


def make_snippet(text: str, terms: List[str], width: int = 260) -> List[Segment]:
    """Return ``[(text, is_match), ...]`` for the densest window of ``text``. Callers must escape."""
    text = _WS.sub(" ", text or "").strip()
    if not text:
        return []
    if not terms:
        return [(_trim(text, width), False)]
    low = text.lower()
    positions = sorted({i for w in terms for i in _find_all(low, w, 40)})
    if not positions:
        return [(_trim(text, width), False)]
    best_start, best_score = positions[0], -1
    for p in positions:
        start = max(0, p - width // 5)
        window = low[start:start + width]
        score = sum(1 for w in terms if w in window)
        if score > best_score:
            best_start, best_score = start, score
            if score == len(terms):
                break
    start = best_start
    if start > 0:
        sp = text.find(" ", start)
        start = sp + 1 if 0 <= sp < start + 30 else start
    end = min(len(text), start + width)
    if end < len(text):
        sp = text.rfind(" ", start, end)
        end = sp if sp > start + width // 2 else end
    chunk = text[start:end].strip()
    out: List[Segment] = []
    if start > 0:
        out.append(("… ", False))
    pos = 0
    for m in _WORD.finditer(chunk):
        if _matches(m.group(), terms):
            if m.start() > pos:
                out.append((chunk[pos:m.start()], False))
            out.append((m.group(), True))
            pos = m.end()
    if pos < len(chunk):
        out.append((chunk[pos:], False))
    if end < len(text):
        out.append((" …", False))
    return out


def highlight_plain(text: str, terms: List[str]) -> List[Segment]:
    """Mark matching words inside a short string (titles, provider snippets)."""
    text = _WS.sub(" ", text or "").strip()
    if not terms or not text:
        return [(text, False)] if text else []
    out: List[Segment] = []
    pos = 0
    for m in _WORD.finditer(text):
        if _matches(m.group(), terms):
            if m.start() > pos:
                out.append((text[pos:m.start()], False))
            out.append((m.group(), True))
            pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def _find_all(hay: str, needle: str, limit: int) -> List[int]:
    out, i = [], hay.find(needle)
    while i != -1 and len(out) < limit:
        out.append(i)
        i = hay.find(needle, i + len(needle))
    return out


def _trim(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    cut = text.rfind(" ", 0, width)
    return text[: cut if cut > width // 2 else width].rstrip() + " …"
