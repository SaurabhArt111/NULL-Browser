# Null Search Engine

A private, local search engine that runs on `127.0.0.1` and is linked into Null Browser. It is a complete rewrite of the earlier
TF-IDF prototype.

## What it is, honestly

Google, Bing and Brave own crawlers that index hundreds of billions of pages on data centres. No program on one PC can match that
index, and this one does not pretend to. Instead it does what privacy-focused meta-search engines do, and adds a personal index:

| Layer | What it does |
|---|---|
| **Federated web search** | Queries several providers in parallel (DuckDuckGo, Wikipedia by default; Brave, Google Programmable Search or your own SearxNG when you add a key / URL), then merges the lists with **Reciprocal Rank Fusion**. A page that several engines agree on beats one that a single engine put first. Duplicates (http/https, `www.`, tracking parameters) collapse into one result. Per-host diversity keeps one site from filling the page. |
| **Local index** | SQLite **FTS5** with BM25 ranking (title ≫ URL ≫ body weights, Porter stemming, accent folding), phrase and operator queries, highlighted snippets. Add sites from the **Local index** page (`/index`); your own pages rank above the web ones when they match. |
| **Instant answers** | Calculator, unit conversion, time in a city, colour converter, hashes, base64, UUID / password / dice / random number. All computed locally with a safe expression parser (no `eval`). |
| **Knowledge panel** | Wikipedia summary beside results when the query is clearly about one topic. |
| **Images and News** | Openverse + Wikimedia Commons (images) and Google News RSS (news) with no key; Brave / Google / SearxNG add more when configured. Images are fetched through a local proxy, so your browser never contacts those hosts directly. |
| **Suggestions** | Your index titles + provider suggestions within a 300 ms budget, in OpenSearch format (what the browser's address bar reads). |

Search quality for general web queries is therefore as good as the providers you enable. For the best quality add a
[Brave Search API](https://brave.com/search/api/) key (generous free tier) or point it at a SearxNG instance.

## Run

The browser starts this server automatically. To run it by hand:

```
pip install -r requirements.txt
python src/main.py            # http://127.0.0.1:8000   (NULL_SEARCH_PORT to change)
```

Tests: `pip install pytest` then `python -m pytest tests -q`.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `NULL_SEARCH_PORT` | `8000` | Listening port (always bound to 127.0.0.1) |
| `NULL_SEARCH_DATA_DIR` | `./data` | Where `index.sqlite3` lives |
| `NULL_SEARCH_OFFLINE` | off | `1` = never contact external providers (local index only) |
| `NULL_SEARCH_PROVIDERS` | `duckduckgo,wikipedia,openverse,wikimedia,gnews` | Comma list. Also available: `brave`, `searxng`, `google` |
| `BRAVE_API_KEY` | – | Enables Brave web / image / news search |
| `NULL_SEARCH_SEARXNG_URL` | – | e.g. `http://localhost:8888`; enables SearxNG |
| `GOOGLE_API_KEY`, `GOOGLE_CSE_ID` | – | Enable Google Programmable Search (web + images) |
| `NULL_SEARCH_WEB_BUDGET` / `_WEB_SOFT_BUDGET` | `4.5` / `2.5` s | Hard wall for a federated search / how long to wait for stragglers once one provider answered |
| `NULL_SEARCH_CACHE_TTL` | `300` | Provider result cache (seconds, `0` disables) |
| `NULL_SEARCH_CRAWL_DELAY` | `0.6` | Seconds between requests to the same host |
| `NULL_SEARCH_ALLOW_PRIVATE` | off | **Testing only:** allow crawling `localhost` / LAN addresses |
| `NULL_SEARCH_PROXY_IMAGES`, `NULL_SEARCH_FAVICONS` | on | Proxy result images / fetch site icons through the local server |
| `NULL_SEARCH_LOG_QUERIES` | off | Include query text in logs (off: only its length is logged) |
| `NULL_SEARCH_RECENT` | off | Remember recent queries **in memory only** for suggestions |

## Search syntax

`"exact phrase"` · `-word` · `-"phrase"` · `site:example.com` · `intitle:word` · `inurl:word` · `filetype:pdf`.
Operators apply to the local index and are passed through to the web providers.

## API

| Endpoint | |
|---|---|
| `GET /api/search?q=&kind=web\|images\|news&page=&safe=off\|moderate\|strict&t=d\|w\|m\|y` | JSON results, instant answer, panel, per-provider status |
| `GET /api/suggest?q=` | `[query, [suggestions…]]` |
| `GET /api/stats` | `documents`, `hosts`, `words`, providers, crawl status (the browser reads this) |
| `POST /api/crawl` `{urls, max_pages, depth, same_site}` · `GET /api/crawl/status` · `POST /api/crawl/stop` | Background crawl |
| `POST /api/index/delete` `{url}` or `{host}` · `POST /api/index/clear` | Edit the index |
| `GET /api/img?u=` · `GET /api/favicon?host=` | Local image / icon proxies |

All `POST` endpoints require the header `X-Null-Search: 1` (see Security).

## Privacy and security

- Queries are never written to disk or logged (unless you opt in). No cookies, no accounts, no analytics. Providers see the query (that is what searching is) but only from your IP, with a generic user agent; nothing identifies you.
- Listens on loopback only. A **Host-header allow-list** blocks DNS-rebinding; state-changing requests need a custom header (forces a CORS pre-flight, so other websites cannot trigger a crawl) and a same-origin `Origin`.
- Strict **CSP** (`script-src 'self'`, no inline script or style), `nosniff`, `no-referrer`, `frame-ancestors 'none'`. Templates auto-escape; snippet highlighting is built from escaped segments.
- The crawler and proxies only fetch public `http(s)` URLs: loopback, private, link-local and reserved addresses are refused for every redirect hop, only ports 80/443/8080/8443, responses are size-capped, and URLs with embedded credentials are rejected. One known gap: the address is checked right before connecting, not pinned for the connection, so a malicious DNS server could in theory race it (DNS rebinding against the crawler). Crawls only run on explicit user action.
- Crawling honours `robots.txt`, `noindex`, `nofollow`, and waits between requests to the same host.
- FTS queries are built from quoted tokens only; user text can't inject FTS operators.

## Layout

```
src/main.py            entry point
src/Engine/
  app.py               FastAPI app, security middleware, proxies, admin API
  service.py           federation (budgets, cache, circuit breakers), fusion, panel, suggestions
  providers/           duckduckgo, wikipedia, brave, searxng, google CSE, openverse, wikimedia, google-news RSS
  store.py             SQLite FTS5 index          text.py     query parser + snippets
  ranking.py           RRF fusion + diversity      answers.py  instant answers
  crawler.py           polite crawler              extract.py  HTML -> text
  net.py               SSRF-safe fetch + URL normalisation
  config.py cache.py log.py
src/templates, src/static   UI (no inline scripts)
tests/                 64 tests (providers use recorded fixtures through a mock transport)
```

## Limits

- Live providers were not reachable from the build sandbox, so provider parsing is tested against fixtures, not the live sites. DuckDuckGo's HTML endpoint sometimes shows a bot check; the engine then pauses that provider for 30 s and keeps serving the others plus your index.
- Pages that need JavaScript to render are indexed as the server sends them (no headless rendering).
- Single-language stemming (English); other languages are matched without stemming.
- Result pages beyond ~20 are not offered.
