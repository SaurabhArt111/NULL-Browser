"""
inverted_index.py - A small TF-IDF search index for the Null Search Engine.

Builds an inverted index (term -> [(doc_id, tf_idf), ...]) from crawled page
data, plus a metadata store (doc_id -> {title, description, content}) so
search results can be rendered with a title/snippet without re-fetching the
page. Designed to degrade gracefully: a missing/corrupt index file, an empty
query, or a query with no matches never raises - callers always get a
(possibly empty) list back.
"""
import os
import json
import math
import re
import threading
from collections import defaultdict

DEFAULT_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "search_index.json"
)

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text):
    """Lower-cases and splits text into simple word tokens."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


class InvertedIndex:
    def __init__(self, index_file=None):
        self.index = defaultdict(list)         # term -> [(doc_id, tf_idf), ...]
        self.doc_lengths = {}                   # doc_id -> word count
        self.documents = {}                     # doc_id -> {title, description, content, url}
        self.index_file = index_file or DEFAULT_INDEX_PATH
        self._lock = threading.Lock()

    def build_index(self, crawled_data):
        """Builds (or rebuilds) the inverted index with TF-IDF ranking from a
        list of {"url", "title", "description", "content"} dicts. Documents
        with no usable content are skipped rather than raising."""
        with self._lock:
            self.index = defaultdict(list)
            self.doc_lengths = {}
            self.documents = {}

            valid_docs = [d for d in crawled_data if isinstance(d, dict) and d.get("url") and d.get("content")]
            doc_count = len(valid_docs)
            if doc_count == 0:
                self.save_index()
                return

            term_frequencies = defaultdict(lambda: defaultdict(int))
            document_frequencies = defaultdict(int)

            for doc in valid_docs:
                doc_id = doc["url"]
                self.documents[doc_id] = {
                    "url": doc_id,
                    "title": (doc.get("title") or doc_id)[:200],
                    "description": (doc.get("description") or "")[:400],
                    "content": (doc.get("content") or "")[:2000],
                }
                words = tokenize(doc["content"])
                self.doc_lengths[doc_id] = max(len(words), 1)
                unique_words = set(words)

                for word in words:
                    term_frequencies[word][doc_id] += 1
                for word in unique_words:
                    document_frequencies[word] += 1

            for word, doc_dict in term_frequencies.items():
                idf = math.log((doc_count + 1) / (1 + document_frequencies[word])) + 1
                for doc_id, tf in doc_dict.items():
                    tf_idf = (tf / self.doc_lengths[doc_id]) * idf
                    self.index[word].append((doc_id, tf_idf))

            # Keep postings lists sorted best-first so search() doesn't need
            # to re-sort huge lists per query.
            for word in self.index:
                self.index[word].sort(key=lambda pair: pair[1], reverse=True)

            self.save_index()

    def add_documents(self, crawled_data):
        """Merges new documents into the existing index (used when crawling
        incrementally instead of rebuilding from scratch each time)."""
        merged = list(self.documents.values())
        existing_urls = {d["url"] for d in merged}
        for doc in crawled_data:
            if isinstance(doc, dict) and doc.get("url") and doc["url"] not in existing_urls:
                merged.append(doc)
        self.build_index(merged)

    def save_index(self):
        """Saves the inverted index + metadata to a JSON file. Failures are
        logged, not raised - a search engine that can't write to disk should
        still work in-memory for the current process."""
        try:
            os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump({
                    "index": self.index,
                    "doc_lengths": self.doc_lengths,
                    "documents": self.documents,
                }, f)
        except OSError as e:
            print(f"[InvertedIndex] Could not save index to {self.index_file}: {e}")

    def load_index(self):
        """Loads the inverted index from disk. Returns True on success, False
        if there was nothing to load or the file was corrupt (in which case
        the index is simply left empty rather than crashing the app)."""
        if not os.path.exists(self.index_file):
            return False
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self.index = defaultdict(list, {k: [tuple(p) for p in v] for k, v in data.get("index", {}).items()})
                self.doc_lengths = data.get("doc_lengths", {})
                self.documents = data.get("documents", {})
            return True
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"[InvertedIndex] Could not load index from {self.index_file}: {e}")
            return False

    def search(self, query, limit=20):
        """Retrieves documents relevant to a given query using summed TF-IDF
        scores, returning plain result dicts ready for a JSON API response."""
        if not query or not query.strip():
            return []

        query_terms = tokenize(query)
        if not query_terms:
            return []

        scores = defaultdict(float)
        for term in query_terms:
            for doc_id, tf_idf in self.index.get(term, []):
                scores[doc_id] += tf_idf

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        results = []
        for doc_id, score in ranked:
            meta = self.documents.get(doc_id, {})
            results.append({
                "url": doc_id,
                "title": meta.get("title", doc_id),
                "description": meta.get("description") or (meta.get("content", "")[:180]),
                "content": meta.get("content", ""),
                "score": round(score, 4),
            })
        return results

    def suggest(self, prefix, limit=8):
        """Returns up to `limit` indexed terms starting with `prefix`, used
        for the search-box autocomplete dropdown."""
        prefix = (prefix or "").lower().strip()
        if len(prefix) < 2:
            return []
        matches = sorted(t for t in self.index.keys() if t.startswith(prefix))
        return matches[:limit]

    def document_count(self):
        return len(self.documents)


if __name__ == "__main__":
    indexer = InvertedIndex()
    indexer.load_index()
    query = "search engine"
    for result in indexer.search(query):
        print(f"{result['url']} ({result['score']}): {result['title']}")
