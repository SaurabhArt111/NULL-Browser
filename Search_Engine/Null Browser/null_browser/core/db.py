"""SQLite storage for history, bookmarks, downloads, favicons and site permissions.

One connection guarded by a lock (QtWebEngine callbacks may arrive from other
threads). The database self-heals: a corrupt file is moved aside and recreated.
"""
import logging
import os
import sqlite3
import threading
import time

from . import paths

log = logging.getLogger("null.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS urls(
  url TEXT PRIMARY KEY, title TEXT DEFAULT '', visit_count INTEGER DEFAULT 0,
  typed_count INTEGER DEFAULT 0, last_visit REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS visits(
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS visits_ts ON visits(ts);
CREATE INDEX IF NOT EXISTS visits_url ON visits(url);
CREATE TABLE IF NOT EXISTS bookmarks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, url TEXT, folder TEXT DEFAULT 'Bookmarks bar',
  position INTEGER DEFAULT 0, created REAL);
CREATE TABLE IF NOT EXISTS downloads(
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, path TEXT, filename TEXT, mime TEXT,
  total INTEGER DEFAULT 0, received INTEGER DEFAULT 0, state TEXT, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS favicons(host TEXT PRIMARY KEY, png BLOB, updated REAL);
CREATE TABLE IF NOT EXISTS site_perms(
  origin TEXT, feature TEXT, value TEXT, updated REAL, PRIMARY KEY(origin, feature));
CREATE TABLE IF NOT EXISTS site_zoom(host TEXT PRIMARY KEY, zoom REAL);
"""


class Database:
    def __init__(self, path=None):
        self.path = path or os.path.join(paths.data_dir(), "browser.db")
        self.lock = threading.RLock()
        self.conn = None
        self._open()

    def _open(self):
        try:
            self._connect()
        except sqlite3.DatabaseError:
            bad = self.path + f".corrupt-{int(time.time())}"
            log.error("Database is corrupt, moving to %s and starting fresh", bad)
            try:
                if self.conn:
                    self.conn.close()
                os.replace(self.path, bad)
            except OSError:
                pass
            self._connect()

    def _connect(self):
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.execute("PRAGMA quick_check")
        self.conn.commit()

    # -- helpers ------------------------------------------------------------
    def run(self, sql, args=()):
        with self.lock:
            try:
                cur = self.conn.execute(sql, args)
                self.conn.commit()
                return cur
            except sqlite3.Error:
                log.exception("SQL failed: %s", sql)
                self.conn.rollback()
                raise

    def all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def close(self):
        with self.lock:
            try:
                self.conn.commit()
                self.conn.close()
            except sqlite3.Error:
                pass

    # -- history ------------------------------------------------------------
    def add_visit(self, url, title="", typed=False):
        now = time.time()
        with self.lock:
            self.conn.execute(
                "INSERT INTO urls(url,title,visit_count,typed_count,last_visit) VALUES(?,?,1,?,?) "
                "ON CONFLICT(url) DO UPDATE SET visit_count=visit_count+1, last_visit=?, "
                "typed_count=typed_count+?, title=CASE WHEN ?<>'' THEN ? ELSE title END",
                (url, title, int(typed), now, now, int(typed), title, title))
            self.conn.execute("INSERT INTO visits(url,ts) VALUES(?,?)", (url, now))
            self.conn.commit()

    def update_title(self, url, title):
        if title:
            self.run("UPDATE urls SET title=? WHERE url=?", (title, url))

    def history(self, query="", limit=200, before=None):
        q = "SELECT v.id, v.url, v.ts, COALESCE(u.title,'') AS title FROM visits v LEFT JOIN urls u ON u.url=v.url"
        cond, args = [], []
        if query:
            cond.append("(v.url LIKE ? OR u.title LIKE ?)")
            args += [f"%{query}%", f"%{query}%"]
        if before:
            cond.append("v.ts < ?")
            args.append(before)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY v.ts DESC LIMIT ?"
        args.append(limit)
        return self.all(q, args)

    def delete_visits(self, ids):
        with self.lock:
            for i in ids:
                self.conn.execute("DELETE FROM visits WHERE id=?", (i,))
            self._prune_urls()
            self.conn.commit()

    def delete_history_range(self, start=0, end=None):
        end = end or time.time() + 10
        with self.lock:
            self.conn.execute("DELETE FROM visits WHERE ts>=? AND ts<=?", (start, end))
            self._prune_urls()
            self.conn.commit()

    def delete_url(self, url):
        with self.lock:
            self.conn.execute("DELETE FROM visits WHERE url=?", (url,))
            self.conn.execute("DELETE FROM urls WHERE url=?", (url,))
            self.conn.commit()

    def _prune_urls(self):
        self.conn.execute("DELETE FROM urls WHERE url NOT IN (SELECT DISTINCT url FROM visits)")

    def top_sites(self, limit=8):
        return self.all("SELECT url, title, visit_count FROM urls WHERE url LIKE 'http%' "
                        "ORDER BY visit_count DESC, last_visit DESC LIMIT ?", (limit * 4,))

    def omnibox_history(self, text, limit=6):
        like = f"%{text}%"
        return self.all(
            "SELECT url, title, visit_count, typed_count, last_visit FROM urls "
            "WHERE url LIKE 'http%' AND (url LIKE ? OR title LIKE ?) "
            "ORDER BY typed_count DESC, visit_count DESC, last_visit DESC LIMIT ?", (like, like, limit))

    # -- bookmarks ----------------------------------------------------------
    def bookmarks(self, folder=None):
        if folder:
            return self.all("SELECT * FROM bookmarks WHERE folder=? ORDER BY position, id", (folder,))
        return self.all("SELECT * FROM bookmarks ORDER BY folder, position, id")

    def bookmark_for(self, url):
        return self.one("SELECT * FROM bookmarks WHERE url=?", (url,))

    def add_bookmark(self, title, url, folder="Bookmarks bar"):
        pos = (self.one("SELECT COALESCE(MAX(position),0)+1 AS p FROM bookmarks WHERE folder=?", (folder,)) or {"p": 0})["p"]
        cur = self.run("INSERT INTO bookmarks(title,url,folder,position,created) VALUES(?,?,?,?,?)",
                       (title or url, url, folder, pos, time.time()))
        return cur.lastrowid

    def update_bookmark(self, bid, title=None, url=None, folder=None):
        row = self.one("SELECT * FROM bookmarks WHERE id=?", (bid,))
        if not row:
            return False
        self.run("UPDATE bookmarks SET title=?, url=?, folder=? WHERE id=?",
                 (title if title is not None else row["title"], url if url is not None else row["url"],
                  folder if folder is not None else row["folder"], bid))
        return True

    def delete_bookmark(self, bid):
        self.run("DELETE FROM bookmarks WHERE id=?", (bid,))

    def bookmark_folders(self):
        names = [r["folder"] for r in self.all("SELECT DISTINCT folder FROM bookmarks")]
        for base in ("Bookmarks bar", "Other bookmarks"):
            if base not in names:
                names.append(base)
        return sorted(names, key=lambda n: (n not in ("Bookmarks bar", "Other bookmarks"), n))

    # -- favicons -----------------------------------------------------------
    def set_favicon(self, host, png):
        if host and png:
            self.run("INSERT OR REPLACE INTO favicons(host,png,updated) VALUES(?,?,?)", (host, png, time.time()))

    def favicon(self, host):
        r = self.one("SELECT png FROM favicons WHERE host=?", (host,))
        return r["png"] if r else None

    # -- site permissions & zoom -------------------------------------------
    def get_site_perm(self, origin, feature):
        r = self.one("SELECT value FROM site_perms WHERE origin=? AND feature=?", (origin, feature))
        return r["value"] if r else None

    def set_site_perm(self, origin, feature, value):
        if value in (None, "", "default"):
            self.run("DELETE FROM site_perms WHERE origin=? AND feature=?", (origin, feature))
        else:
            self.run("INSERT OR REPLACE INTO site_perms(origin,feature,value,updated) VALUES(?,?,?,?)",
                     (origin, feature, value, time.time()))

    def site_perms_for(self, origin):
        return {r["feature"]: r["value"] for r in self.all("SELECT feature,value FROM site_perms WHERE origin=?", (origin,))}

    def site_perms_list(self, feature=None):
        if feature:
            return self.all("SELECT origin,feature,value,updated FROM site_perms WHERE feature=? ORDER BY origin", (feature,))
        return self.all("SELECT origin,feature,value,updated FROM site_perms ORDER BY origin, feature")

    def clear_site_perms(self, origin=None):
        if origin:
            self.run("DELETE FROM site_perms WHERE origin=?", (origin,))
        else:
            self.run("DELETE FROM site_perms")

    def get_zoom(self, host):
        r = self.one("SELECT zoom FROM site_zoom WHERE host=?", (host,))
        return r["zoom"] if r else None

    def set_zoom(self, host, zoom):
        if abs(zoom - 1.0) < 0.001:
            self.run("DELETE FROM site_zoom WHERE host=?", (host,))
        else:
            self.run("INSERT OR REPLACE INTO site_zoom(host,zoom) VALUES(?,?)", (host, zoom))
