"""
web_crawler.py - A small polite, multi-threaded crawler for the Null Search
Engine. Given a list of seed URLs, it stays within each seed's domain,
respects robots.txt where available, and extracts title/description/text
content suitable for indexing.

This is intentionally conservative (low thread count, small default page
limit, per-request delay) - it's meant to build a modest personal index,
not to scrape the web aggressively.
"""
import threading
import queue
import time
import json
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

DEFAULT_MAX_THREADS = 4
DEFAULT_CRAWL_LIMIT = 40
DEFAULT_TIMEOUT = 6
DEFAULT_DELAY = 0.3  # seconds between requests, per worker thread
USER_AGENT = "NullSearchBot/1.0 (+https://github.com/null-browser)"


class WebCrawler:
    def __init__(self, start_urls, max_threads=DEFAULT_MAX_THREADS,
                 crawl_limit=DEFAULT_CRAWL_LIMIT, timeout=DEFAULT_TIMEOUT,
                 delay=DEFAULT_DELAY, same_domain_only=True, on_progress=None):
        self.start_urls = [u for u in (start_urls or []) if isinstance(u, str) and u.strip()]
        self.max_threads = max(1, min(max_threads, 16))
        self.crawl_limit = max(1, crawl_limit)
        self.timeout = timeout
        self.delay = delay
        self.same_domain_only = same_domain_only
        self.on_progress = on_progress  # optional callback(pages_crawled, limit)

        self.visited = set()
        self.queue = queue.Queue()
        self.results = []
        self._lock = threading.Lock()
        self._robots_cache = {}
        self.errors = []

        for url in self.start_urls:
            self.queue.put(url)

    # -- robots.txt -------------------------------------------------------
    def _allowed_by_robots(self, url):
        try:
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in self._robots_cache:
                rp = RobotFileParser()
                rp.set_url(urljoin(origin, "/robots.txt"))
                try:
                    rp.read()
                except Exception:
                    rp = None  # if robots.txt can't be fetched, default to allow
                self._robots_cache[origin] = rp
            rp = self._robots_cache[origin]
            if rp is None:
                return True
            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True  # never let a robots.txt problem block crawling entirely

    # -- fetching / parsing -------------------------------------------------
    def fetch(self, url):
        try:
            headers = {"User-Agent": USER_AGENT}
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return None
            return response.text
        except requests.RequestException as e:
            with self._lock:
                self.errors.append(f"{url}: {e}")
            return None

    def parse(self, url, html):
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            with self._lock:
                self.errors.append(f"{url}: parse error ({e})")
            return

        title = soup.title.string.strip() if soup.title and soup.title.string else url
        description_tag = soup.find("meta", attrs={"name": "description"})
        description = description_tag["content"].strip() if description_tag and description_tag.get("content") else ""

        # Strip script/style before extracting text
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "h1", "h2", "h3", "li"])]
        content = " ".join(t for t in paragraphs if t)[:2000]

        if not content and not description:
            return  # nothing worth indexing on this page

        with self._lock:
            self.results.append({
                "url": url,
                "title": title,
                "description": description,
                "content": content,
            })

        try:
            for link in soup.find_all("a", href=True):
                absolute_url = urljoin(url, link["href"]).split("#")[0]
                if not absolute_url.startswith(("http://", "https://")):
                    continue
                if self.same_domain_only and urlparse(absolute_url).netloc != urlparse(url).netloc:
                    continue
                with self._lock:
                    if absolute_url not in self.visited:
                        self.queue.put(absolute_url)
        except Exception as e:
            with self._lock:
                self.errors.append(f"{url}: link extraction error ({e})")

    # -- worker / orchestration --------------------------------------------
    def worker(self):
        while True:
            with self._lock:
                if len(self.visited) >= self.crawl_limit:
                    return
            try:
                url = self.queue.get(timeout=1)
            except queue.Empty:
                return

            with self._lock:
                if url in self.visited or len(self.visited) >= self.crawl_limit:
                    self.queue.task_done()
                    continue
                self.visited.add(url)

            try:
                if self._allowed_by_robots(url):
                    html = self.fetch(url)
                    if html:
                        self.parse(url, html)
                if self.on_progress:
                    try:
                        self.on_progress(len(self.visited), self.crawl_limit)
                    except Exception:
                        pass
                time.sleep(self.delay)
            except Exception as e:
                with self._lock:
                    self.errors.append(f"{url}: unexpected error ({e})")
            finally:
                self.queue.task_done()

    def run(self):
        if not self.start_urls:
            return []
        threads = [threading.Thread(target=self.worker, daemon=True) for _ in range(self.max_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=self.timeout * self.crawl_limit + 30)
        return self.results


if __name__ == "__main__":
    seed_urls = ["https://en.wikipedia.org/wiki/Web_crawler"]
    crawler = WebCrawler(seed_urls, crawl_limit=10)
    crawled_results = crawler.run()

    with open("crawled_data.json", "w", encoding="utf-8") as f:
        json.dump(crawled_results, f, indent=2)

    print(f"Crawling finished: {len(crawled_results)} pages indexed, {len(crawler.errors)} errors.")
