"""
main.py - Null Search Engine backend (FastAPI).

Serves the search UI (templates/index.html + css/js) and a small JSON API:

  GET  /api/search?q=&limit=          -> ranked results from the local index
  GET  /search?q=...                  -> same as /api/search when called via
                                          fetch (Accept: application/json);
                                          otherwise redirects to "/?q=..." so
                                          the no-JS <form> fallback still works
  GET  /api/suggest?q=                -> autocomplete suggestions
  GET  /api/stats                     -> index size / crawl status
  POST /api/crawl                     -> kick off a background crawl of the
                                          given seed URLs (or the built-in
                                          starter seeds if none are given)

Run with:  python src/main.py   (serves on http://127.0.0.1:8000)
"""
import os
import sys
import threading
import traceback
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Make sure the Engine package is importable regardless of the working
# directory the app is launched from.
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.append(SRC_DIR)

from Engine.inverted_index import InvertedIndex
from Engine.web_crawler import WebCrawler


def _bootstrap_demo_index(index_obj):
    """Seed a tiny built-in index so the UI works even before a crawl."""
    demo_docs = [
        {
            "url": "https://example.com/browser",
            "title": "Null Browser",
            "description": "A privacy-focused desktop browser built with PyQt and QtWebEngine.",
            "content": "Null Browser is a privacy focused desktop browser with bookmarks tabs history and ad blocking."
        },
        {
            "url": "https://example.com/search",
            "title": "Null Search Engine",
            "description": "A local search engine that indexes pages and serves search results.",
            "content": "Null Search Engine is a local search engine that crawls pages and provides search suggestions and rankings."
        },
        {
            "url": "https://example.com/python",
            "title": "Python Programming",
            "description": "Python is a popular programming language for automation and web development.",
            "content": "Python is a programming language used for automation web development machine learning and data science."
        },
    ]
    if index_obj.document_count() == 0:
        index_obj.add_documents(demo_docs)

TEMPLATES_DIR = os.path.join(SRC_DIR, "templates")
DATA_DIR = os.path.join(os.path.dirname(SRC_DIR), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# A small, safe set of general-purpose seed pages used only if the person
# explicitly asks to bootstrap the index with no seeds of their own.
DEFAULT_SEEDS = [
    "https://en.wikipedia.org/wiki/Web_browser",
    "https://en.wikipedia.org/wiki/Search_engine",
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
]

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[NullSearchEngine] Index loaded with {index.document_count()} document(s) "
          f"from {index.index_file}")
    if index.document_count() == 0:
        print("[NullSearchEngine] Index is empty. POST /api/crawl to build it, "
              "e.g.: curl -X POST http://127.0.0.1:8000/api/crawl "
              "-H 'Content-Type: application/json' -d '{}'")
    yield


app = FastAPI(title="Null Search Engine", lifespan=lifespan)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Serve the existing css/js folders directly (they live under templates/,
# rather than a separate static/ dir, to avoid reshuffling the project).
app.mount("/css", StaticFiles(directory=os.path.join(TEMPLATES_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(TEMPLATES_DIR, "js")), name="js")

index = InvertedIndex(index_file=os.path.join(DATA_DIR, "search_index.json"))
index.load_index()
_bootstrap_demo_index(index)

crawl_state = {"running": False, "crawled": 0, "limit": 0, "last_error": None}
crawl_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        return templates.TemplateResponse(request=request, name="index.html")
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(f"<h1>Null Search Engine</h1><p>Template error: {e}</p>", status_code=500)


@app.get("/search")
async def search_page_or_api(request: Request, q: Optional[str] = None, limit: int = 20):
    """Supports two audiences with one URL, like a real search engine:
    - fetch()/XHR calls (Accept: application/json) get JSON results, used by
      the page's own JS and by Null Browser's address bar.
    - a plain top-level navigation (e.g. the <form> submitting with
      JavaScript disabled) gets redirected to "/?q=..." so index.html loads
      and runs the same search client-side.
    """
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return await api_search(q=q, limit=limit)
    if not q:
        return RedirectResponse(url="/")
    return RedirectResponse(url=f"/?q={q}")


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------
@app.get("/api/search")
async def api_search(q: Optional[str] = None, limit: int = 20):
    try:
        if not q or not q.strip():
            return JSONResponse({"results": [], "total": 0, "message": "Type something to search for."})

        limit = max(1, min(limit, 50))
        results = index.search(q, limit=limit)

        message = None
        if not results:
            message = (
                "No results found in the local index."
                if index.document_count() > 0 else
                "The search index is empty. POST /api/crawl to build it first."
            )

        return JSONResponse({"query": q, "results": results, "total": len(results), "message": message})
    except Exception as e:
        traceback.print_exc()
        # A search failure should never look like a server crash to the
        # caller - report it as a normal (empty) result set with a reason.
        return JSONResponse(
            {"results": [], "total": 0, "message": f"Search error: {e}"},
            status_code=200,
        )


@app.get("/api/suggest")
async def api_suggest(q: Optional[str] = None):
    try:
        suggestions = index.suggest(q or "", limit=8)
        return JSONResponse({"suggestions": suggestions})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"suggestions": [], "error": str(e)})


@app.get("/api/stats")
async def api_stats():
    return JSONResponse({
        "documents": index.document_count(),
        "terms": len(index.index),
        "crawl": crawl_state,
    })


class CrawlRequest(BaseModel):
    seeds: Optional[List[str]] = None
    max_pages: int = 40
    same_domain_only: bool = True


def _run_crawl(seeds, max_pages, same_domain_only):
    global crawl_state
    try:
        with crawl_lock:
            crawl_state.update(running=True, crawled=0, limit=max_pages, last_error=None)

        def progress(done, limit):
            crawl_state["crawled"] = done
            crawl_state["limit"] = limit

        crawler = WebCrawler(
            seeds, crawl_limit=max_pages, same_domain_only=same_domain_only, on_progress=progress
        )
        results = crawler.run()
        index.add_documents(results)
        print(f"[NullSearchEngine] Crawl finished: {len(results)} pages indexed, "
              f"{len(crawler.errors)} errors, {index.document_count()} total documents.")
    except Exception as e:
        traceback.print_exc()
        crawl_state["last_error"] = str(e)
    finally:
        crawl_state["running"] = False


@app.post("/api/crawl")
async def api_crawl(req: CrawlRequest):
    try:
        with crawl_lock:
            if crawl_state["running"]:
                raise HTTPException(status_code=409, detail="A crawl is already running")

        seeds = [s for s in (req.seeds or DEFAULT_SEEDS) if isinstance(s, str) and s.startswith(("http://", "https://"))]
        if not seeds:
            raise HTTPException(status_code=400, detail="No valid http(s) seed URLs were provided")

        max_pages = max(1, min(req.max_pages, 500))
        thread = threading.Thread(
            target=_run_crawl, args=(seeds, max_pages, req.same_domain_only), daemon=True
        )
        thread.start()
        return JSONResponse({"started": True, "seeds": seeds, "max_pages": max_pages})
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/crawl/status")
async def api_crawl_status():
    return JSONResponse(crawl_state)


if __name__ == "__main__":
    import uvicorn
    try:
        uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
    except OSError as e:
        print(f"Could not start the server (is port 8000 already in use?): {e}")
        sys.exit(1)
