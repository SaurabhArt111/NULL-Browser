"""
newtab.py - Builds the local "New Tab" page shown when Null Browser starts
or when a new tab is opened, without requiring the Null Search Engine
server to be running. Styled after Chrome/Brave's new-tab page: a
centered search box, quick-access tiles for top bookmarks, and a small
privacy/ad-block summary card.
"""
import html
from string import Template

PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>New Tab</title>
<style>
  :root {
    --bg: $bg; --fg: $fg; --card: $card; --accent: $accent; --muted: $muted;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; height: 100%;
    background: var(--bg); color: var(--fg);
    font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    transition: background 0.25s ease, color 0.25s ease;
  }
  body {
    display: flex; flex-direction: column; align-items: center;
    padding-top: 12vh;
  }
  .logo { font-size: 42px; font-weight: 600; letter-spacing: -1px; margin-bottom: 28px; }
  .logo span { color: var(--accent); }
  form.search { width: min(560px, 88vw); }
  .search-box {
    display: flex; align-items: center; gap: 10px;
    background: var(--card); border-radius: 24px; padding: 12px 20px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.15);
    transition: box-shadow 0.2s ease, transform 0.15s ease;
  }
  .search-box:focus-within { box-shadow: 0 2px 14px rgba(0,0,0,0.25); transform: translateY(-1px); }
  .search-box input {
    flex: 1; border: none; outline: none; background: transparent;
    font-size: 16px; color: var(--fg);
  }
  .search-box button {
    border: none; background: var(--accent); color: white; border-radius: 18px;
    padding: 8px 16px; font-size: 14px; cursor: pointer;
    transition: filter 0.15s ease;
  }
  .search-box button:hover { filter: brightness(1.1); }
  .tiles {
    display: flex; flex-wrap: wrap; gap: 16px; justify-content: center;
    margin-top: 42px; width: min(680px, 92vw);
  }
  .tile {
    width: 96px; text-decoration: none; color: var(--fg); text-align: center;
    transition: transform 0.15s ease;
  }
  .tile:hover { transform: translateY(-3px); }
  .tile .icon {
    width: 52px; height: 52px; border-radius: 50%; background: var(--card);
    display: flex; align-items: center; justify-content: center; margin: 0 auto 6px;
    font-size: 18px; font-weight: 600; color: var(--accent);
    box-shadow: 0 1px 4px rgba(0,0,0,0.12);
  }
  .tile .label {
    font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .stats {
    margin-top: 48px; background: var(--card); border-radius: 12px;
    padding: 14px 22px; font-size: 13px; color: var(--muted);
    display: flex; gap: 22px;
  }
  .stats b { color: var(--fg); }
  .empty-hint { color: var(--muted); font-size: 13px; margin-top: 42px; }
</style>
</head>
<body>
  <div class="logo">Null<span>Browser</span></div>
  <form class="search" action="null-search:" method="get" onsubmit="return doSearch(event)">
    <div class="search-box">
      <span>🔎</span>
      <input id="q" name="q" type="text" placeholder="Search the web or type a URL" autofocus>
      <button type="submit">Search</button>
    </div>
  </form>
  <div class="tiles">
    $tiles
  </div>
  $empty_hint
  <div class="stats">
    <div>🛡️ <b>$blocked</b> trackers &amp; ads blocked</div>
    <div>⭐ <b>$bookmark_count</b> bookmarks</div>
  </div>
  <script>
    function doSearch(ev) {
      ev.preventDefault();
      const q = document.getElementById('q').value.trim();
      if (q) {
        window.location.href = "nullbrowser://search?q=" + encodeURIComponent(q);
      }
      return false;
    }
  </script>
</body>
</html>""")


def _initials(title):
    words = [w for w in title.split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def build_new_tab_html(bookmarks=None, blocked_count=0, dark=False):
    """Return a self-contained HTML string for the new tab page.

    bookmarks: list of (id, title, url, ...) tuples, most-recent/most-used first.
    """
    bookmarks = bookmarks or []
    tiles = []
    for entry in bookmarks[:8]:
        try:
            title = entry[1] or entry[2]
            url = entry[2]
        except (IndexError, TypeError):
            continue
        safe_title = html.escape(title[:18])
        safe_url = html.escape(url, quote=True)
        tiles.append(
            f'<a class="tile" href="{safe_url}" title="{html.escape(title)}">'
            f'<div class="icon">{html.escape(_initials(title))}</div>'
            f'<div class="label">{safe_title}</div></a>'
        )

    empty_hint = ""
    if not tiles:
        empty_hint = '<div class="empty-hint">Bookmark pages (Ctrl+D) to see quick-access tiles here.</div>'

    if dark:
        colors = dict(bg="#202124", fg="#e8eaed", card="#303134", accent="#8ab4f8", muted="#9aa0a6")
    else:
        colors = dict(bg="#ffffff", fg="#202124", card="#f1f3f4", accent="#1a73e8", muted="#5f6368")

    return PAGE_TEMPLATE.substitute(
        tiles="\n".join(tiles),
        empty_hint=empty_hint,
        blocked=blocked_count,
        bookmark_count=len(bookmarks),
        **colors,
    )


ERROR_PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>$title</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
         background:#fff; color:#202124; display:flex; flex-direction:column;
         align-items:center; justify-content:center; height:100vh; margin:0; text-align:center; }
  .icon { font-size:56px; margin-bottom: 12px; }
  h1 { font-size: 20px; font-weight: 500; margin: 0 0 8px; }
  p { color:#5f6368; font-size:14px; max-width:480px; margin: 0 0 18px;}
  code { background:#f1f3f4; padding:2px 6px; border-radius:4px; }
  button { border:none; background:#1a73e8; color:#fff; padding:9px 18px;
           border-radius:18px; font-size:14px; cursor:pointer; }
  button:hover { filter:brightness(1.08); }
</style></head>
<body>
  <div class="icon">⚠️</div>
  <h1>$title</h1>
  <p>$message<br><code>$url</code></p>
  <button onclick="location.reload()">Try again</button>
</body></html>""")


def build_error_page(url, reason="This site can't be reached"):
    return ERROR_PAGE_TEMPLATE.substitute(
        title=reason,
        message="Null Browser could not load this page. Check the address, your "
                "internet connection, or try again in a moment.",
        url=html.escape(url),
    )
