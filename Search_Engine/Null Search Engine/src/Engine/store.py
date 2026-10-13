"""SQLite + FTS5 page index.

* ``pages`` holds one row per URL (title, description, extracted body text).
* ``pages_fts`` is an external-content FTS5 table (porter stemming, unicode folding) kept in sync by triggers.
* Ranking is BM25 with column weights (title >> url >> body) plus a mild freshness/length prior.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from .text import ParsedQuery, fts_expression

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    host TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    url_text TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT '',
    words INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS pages_host ON pages(host);
CREATE INDEX IF NOT EXISTS pages_fetched ON pages(fetched_at);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    title, url_text, body,
    content='pages', content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, title, url_text, body) VALUES (new.id, new.title, new.url_text, new.body);
END;
CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, url_text, body) VALUES ('delete', old.id, old.title, old.url_text, old.body);
END;
CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, url_text, body) VALUES ('delete', old.id, old.title, old.url_text, old.body);
    INSERT INTO pages_fts(rowid, title, url_text, body) VALUES (new.id, new.title, new.url_text, new.body);
END;
"""

MAX_BODY_CHARS = 60_000


@dataclass
class Doc:
    url: str
    title: str = ""
    description: str = ""
    body: str = ""
    lang: str = ""
    fetched_at: float = field(default_factory=time.time)


@dataclass
class Hit:
    id: int
    url: str
    host: str
    title: str
    description: str
    body: str
    score: float
    fetched_at: float


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _url_text(url: str) -> str:
    parts = urlsplit(url)
    return " ".join(p for p in ((parts.hostname or ""), parts.path.replace("/", " ").replace("-", " ").replace("_", " ").replace(".", " ")) if p)


class Store:
    """Thread-safe (one connection per thread) page index."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._local = threading.local()
        self._all: List[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._shared: Optional[sqlite3.Connection] = None
        if path == ":memory:":                                   # one shared connection for tests
            self._shared = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared.row_factory = sqlite3.Row
        self._conn().executescript(SCHEMA)

    # ---- connection handling ------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=15)
            c.row_factory = sqlite3.Row
            self._local.c = c
            with self._lock:
                self._all.append(c)
        return c

    def close(self) -> None:
        with self._lock:
            for c in self._all:
                try:
                    c.close()
                except sqlite3.Error:
                    pass
            self._all.clear()
        if self._shared is not None:
            self._shared.close()
        self._local = threading.local()

    # ---- writes -------------------------------------------------------------------------
    def upsert(self, doc: Doc) -> str:
        """Insert or refresh a page. Returns ``"new"``, ``"updated"`` or ``"same"``."""
        body = (doc.body or "")[:MAX_BODY_CHARS]
        h = hashlib.blake2b((doc.title + "\0" + doc.description + "\0" + body).encode("utf-8", "ignore"), digest_size=12).hexdigest()
        c = self._conn()
        row = c.execute("SELECT id, content_hash FROM pages WHERE url=?", (doc.url,)).fetchone()
        if row and row["content_hash"] == h:
            c.execute("UPDATE pages SET fetched_at=? WHERE id=?", (doc.fetched_at, row["id"]))
            c.commit()
            return "same"
        words = len(body.split())
        if row:
            c.execute("UPDATE pages SET title=?, description=?, body=?, url_text=?, lang=?, words=?, content_hash=?, fetched_at=? WHERE id=?",
                      (doc.title, doc.description, body, _url_text(doc.url), doc.lang, words, h, doc.fetched_at, row["id"]))
            c.commit()
            return "updated"
        c.execute("INSERT INTO pages(url, host, title, description, body, url_text, lang, words, content_hash, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (doc.url, _host(doc.url), doc.title, doc.description, body, _url_text(doc.url), doc.lang, words, h, doc.fetched_at))
        c.commit()
        return "new"

    def delete_url(self, url: str) -> int:
        c = self._conn()
        n = c.execute("DELETE FROM pages WHERE url=?", (url,)).rowcount
        c.commit()
        return n

    def delete_host(self, host: str) -> int:
        host = host.lower()
        host = host[4:] if host.startswith("www.") else host
        c = self._conn()
        n = c.execute("DELETE FROM pages WHERE host=? OR host LIKE ? ESCAPE '\\'", (host, "%." + _like(host))).rowcount
        c.commit()
        return n

    def clear(self) -> int:
        c = self._conn()
        n = c.execute("DELETE FROM pages").rowcount
        c.execute("INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')")
        c.commit()
        try:
            c.execute("VACUUM")
        except sqlite3.Error:
            pass
        return n

    def optimize(self) -> None:
        c = self._conn()
        c.execute("INSERT INTO pages_fts(pages_fts) VALUES ('optimize')")
        c.commit()

    # ---- reads --------------------------------------------------------------------------
    def count(self) -> int:
        return int(self._conn().execute("SELECT count(*) FROM pages").fetchone()[0])

    def has_url(self, url: str) -> bool:
        return self._conn().execute("SELECT 1 FROM pages WHERE url=?", (url,)).fetchone() is not None

    def search(self, pq: ParsedQuery, limit: int = 10, offset: int = 0, since: Optional[float] = None) -> Tuple[List[Hit], int]:
        """Ranked search. Falls back to OR-matching when AND finds almost nothing. Returns (hits, total)."""
        where, params = [], []
        if pq.site:
            where.append("(p.host = ? OR p.host LIKE ? ESCAPE '\\')")
            params += [pq.site, "%." + _like(pq.site)]
        if pq.filetype:
            where.append("(p.url LIKE ? ESCAPE '\\' OR p.url LIKE ? ESCAPE '\\')")
            params += ["%." + _like(pq.filetype), "%." + _like(pq.filetype) + "?%"]
        if since:
            where.append("p.fetched_at >= ?")
            params.append(since)
        extra = (" AND " + " AND ".join(where)) if where else ""
        c = self._conn()
        for loose in (False, True):
            expr = fts_expression(pq, loose=loose)
            if expr is None:
                return self._browse(pq, where, params, limit, offset)
            if loose and len(pq.terms) < 2:
                break
            try:
                total = c.execute(f"SELECT count(*) FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid WHERE pages_fts MATCH ?{extra}",
                                  [expr] + params).fetchone()[0]
                if total < 3 and not loose and len(pq.terms) > 1:
                    continue
                rows = c.execute(
                    "SELECT p.*, bm25(pages_fts, 10.0, 4.0, 1.0) AS rank FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid "
                    f"WHERE pages_fts MATCH ?{extra} ORDER BY rank LIMIT ? OFFSET ?", [expr] + params + [limit, offset]).fetchall()
            except sqlite3.OperationalError:                     # malformed expression: treat as no results
                return [], 0
            if total or loose:
                return [_hit(r) for r in rows], int(total)
        return [], 0

    def _browse(self, pq: ParsedQuery, where, params, limit, offset):
        """Operator-only queries (``site:example.com``): newest first."""
        if not where:
            return [], 0
        c = self._conn()
        clause = " WHERE " + " AND ".join(where)
        total = c.execute(f"SELECT count(*) FROM pages p{clause}", params).fetchone()[0]
        rows = c.execute(f"SELECT p.*, 0.0 AS rank FROM pages p{clause} ORDER BY fetched_at DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
        return [_hit(r) for r in rows], int(total)

    def titles_like(self, prefix: str, limit: int = 5) -> List[str]:
        prefix = prefix.strip()
        if len(prefix) < 2:
            return []
        rows = self._conn().execute(
            "SELECT DISTINCT title FROM pages WHERE title LIKE ? ESCAPE '\\' AND title != '' ORDER BY length(title) LIMIT ?",
            (_like(prefix) + "%", limit)).fetchall()
        return [r[0] for r in rows]

    def stats(self) -> Dict[str, object]:
        c = self._conn()
        row = c.execute("SELECT count(*), count(DISTINCT host), coalesce(sum(words),0), max(fetched_at) FROM pages").fetchone()
        top = c.execute("SELECT host, count(*) n FROM pages GROUP BY host ORDER BY n DESC LIMIT 12").fetchall()
        try:
            size = os.path.getsize(self.path) if self.path != ":memory:" else 0
        except OSError:
            size = 0
        return {"documents": int(row[0]), "hosts": int(row[1]), "words": int(row[2]), "last_indexed": row[3], "db_bytes": size,
                "top_hosts": [{"host": r["host"], "pages": r["n"]} for r in top]}

    def recent(self, limit: int = 20, offset: int = 0) -> List[Dict[str, object]]:
        rows = self._conn().execute("SELECT url, title, host, fetched_at, words FROM pages ORDER BY fetched_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [dict(r) for r in rows]


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _hit(r: sqlite3.Row) -> Hit:
    # bm25() is negative (lower = better); expose a positive "higher is better" score.
    return Hit(id=r["id"], url=r["url"], host=r["host"], title=r["title"], description=r["description"], body=r["body"],
               score=-float(r["rank"]), fetched_at=r["fetched_at"])
