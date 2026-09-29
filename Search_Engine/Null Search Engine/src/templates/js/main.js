// main.js - Null Search Engine frontend.
// A single, self-contained script (the previous app.js/search.js/storage.js/
// themes.js/voice.js files declared clashing globals and were never actually
// <script>-included by index.html, so search never worked). This file wires
// up theme switching, live search + suggestions against the FastAPI JSON
// API, and the bookmarks/history/settings panels, all with defensive error
// handling so a single failed fetch can't break the page.

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const qsa = (sel) => Array.from(document.querySelectorAll(sel));

  // ---------------------------------------------------------------------
  // Theme management
  // ---------------------------------------------------------------------
  const ThemeManager = {
    init() {
      const saved = localStorage.getItem("nullSearchTheme") || "light";
      this.setTheme(saved, false);

      const toggle = $("theme-toggle");
      if (toggle) toggle.addEventListener("click", () => this.toggleTheme());

      qsa(".theme-option").forEach((btn) => {
        btn.addEventListener("click", () => this.setTheme(btn.dataset.theme));
      });

      if (window.matchMedia) {
        window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
          if (this.currentTheme === "system") this.applyClass(e.matches ? "dark" : "light");
        });
      }
    },
    setTheme(theme, persist = true) {
      this.currentTheme = theme;
      this.applyClass(theme === "system"
        ? (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
        : theme);
      qsa(".theme-option").forEach((o) => o.classList.toggle("active", o.dataset.theme === theme));
      if (persist) {
        try { localStorage.setItem("nullSearchTheme", theme); } catch (e) { /* storage may be unavailable */ }
      }
    },
    applyClass(resolvedTheme) {
      document.body.classList.remove("light-theme", "dark-theme", "high-contrast-theme");
      document.body.classList.add(`${resolvedTheme}-theme`);
      const toggle = $("theme-toggle");
      if (toggle) {
        const icon = toggle.querySelector("i");
        if (icon) icon.className = resolvedTheme === "dark" ? "fas fa-sun" : "fas fa-moon";
      }
    },
    toggleTheme() {
      const next = document.body.classList.contains("dark-theme") ? "light" : "dark";
      this.setTheme(next);
    },
  };

  // ---------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function debounce(fn, delay) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  }

  async function fetchJSON(url, opts = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);
    try {
      const res = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
        ...opts,
      });
      if (!res.ok) {
        throw new Error(`Request failed (${res.status})`);
      }
      return await res.json();
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // ---------------------------------------------------------------------
  // Search
  // ---------------------------------------------------------------------
  const Search = {
    init() {
      this.input = $("search-input");
      this.form = $("search-form");
      this.suggestionsBox = $("search-suggestions");
      this.resultsContainer = $("all-results");
      this.resultsCount = document.querySelector(".results-count");

      if (this.form) {
        this.form.addEventListener("submit", (e) => {
          e.preventDefault();
          this.runSearch(this.input.value.trim());
        });
      }
      if (this.input) {
        this.input.addEventListener("input", debounce(() => this.updateSuggestions(), 200));
        this.input.addEventListener("keydown", (e) => {
          if (e.key === "Escape") this.hideSuggestions();
        });
        document.addEventListener("click", (e) => {
          if (this.suggestionsBox && !this.suggestionsBox.contains(e.target) && e.target !== this.input) {
            this.hideSuggestions();
          }
        });
      }

      qsa(".filter-button").forEach((btn) => {
        btn.addEventListener("click", () => {
          qsa(".filter-button").forEach((b) => b.classList.toggle("active", b === btn));
          this.applyTypeFilter(btn.dataset.filter);
        });
      });

      const advToggle = $("advanced-search-toggle");
      const advPanel = $("advanced-search-panel");
      if (advToggle && advPanel) {
        advToggle.addEventListener("click", () => advPanel.classList.toggle("active"));
      }
      const applyFilters = $("apply-filters");
      if (applyFilters) applyFilters.addEventListener("click", () => this.runSearch(this.input.value.trim()));
      const resetFilters = $("reset-filters");
      if (resetFilters) {
        resetFilters.addEventListener("click", () => {
          ["date-range", "file-type"].forEach((id) => { const el = $(id); if (el) el.value = "any"; });
          ["keywords", "exclude-terms"].forEach((id) => { const el = $(id); if (el) el.value = ""; });
        });
      }

      // Results tabs (All / Local / Bookmarks / History)
      qsa(".tab-button").forEach((btn) => {
        btn.addEventListener("click", () => {
          qsa(".tab-button").forEach((b) => b.classList.toggle("active", b === btn));
          qsa(".tab-content").forEach((c) => c.classList.toggle("active", c.id === `${btn.dataset.tab}-results`));
          if (btn.dataset.tab === "bookmarks") BookmarksPanel.render();
          if (btn.dataset.tab === "history") HistoryPanel.render();
        });
      });

      // If the page was loaded with ?q=..., run that search immediately -
      // this is also the no-JS fallback target from the <form> GET action.
      const params = new URLSearchParams(window.location.search);
      const initialQuery = params.get("q");
      if (initialQuery && this.input) {
        this.input.value = initialQuery;
        this.runSearch(initialQuery);
      }
    },

    async updateSuggestions() {
      const query = this.input.value.trim();
      if (!this.suggestionsBox) return;
      if (query.length < 2) {
        this.hideSuggestions();
        return;
      }
      try {
        const data = await fetchJSON(`/api/suggest?q=${encodeURIComponent(query)}`);
        const suggestions = data.suggestions || [];
        if (!suggestions.length) {
          this.hideSuggestions();
          return;
        }
        this.suggestionsBox.innerHTML = suggestions
          .map((s) => `<div class="suggestion-item" role="option">${escapeHtml(s)}</div>`)
          .join("");
        this.suggestionsBox.classList.add("active");
        qsa(".suggestion-item", this.suggestionsBox).forEach((el) => {
          el.addEventListener("click", () => {
            this.input.value = el.textContent;
            this.hideSuggestions();
            this.runSearch(el.textContent);
          });
        });
      } catch (err) {
        // Suggestions are a nice-to-have; fail silently rather than
        // interrupting the person's typing with an error.
        this.hideSuggestions();
      }
    },

    hideSuggestions() {
      if (this.suggestionsBox) {
        this.suggestionsBox.classList.remove("active");
        this.suggestionsBox.innerHTML = "";
      }
    },

    async runSearch(query) {
      if (!query) return;
      this.hideSuggestions();
      this.showLoading();

      if ($("save-history-toggle") == null || $("save-history-toggle").checked) {
        HistoryPanel.add(query);
      }

      const filters = this.collectFilters();
      const params = new URLSearchParams({ q: query, limit: "20", ...filters });

      try {
        const data = await fetchJSON(`/api/search?${params.toString()}`);
        this.renderResults(query, data.results || [], data.message);
      } catch (err) {
        this.renderError(
          "Couldn't reach the Null Search Engine server. Make sure it's " +
          "running (python src/main.py) and try again."
        );
      }
    },

    collectFilters() {
      const filters = {};
      const dateRange = $("date-range");
      if (dateRange && dateRange.value !== "any") filters.date_range = dateRange.value;
      const fileType = $("file-type");
      if (fileType && fileType.value !== "any") filters.file_type = fileType.value;
      const keywords = $("keywords");
      if (keywords && keywords.value.trim()) filters.keywords = keywords.value.trim();
      const excludeTerms = $("exclude-terms");
      if (excludeTerms && excludeTerms.value.trim()) filters.exclude = excludeTerms.value.trim();
      return filters;
    },

    showLoading() {
      if (!this.resultsContainer) return;
      this.resultsContainer.innerHTML = `
        <div class="loading-state">
          <i class="fas fa-spinner fa-spin"></i>
          <p>Searching...</p>
        </div>`;
    },

    renderError(message) {
      if (!this.resultsContainer) return;
      this.resultsContainer.innerHTML = `
        <div class="error-state">
          <i class="fas fa-exclamation-circle"></i>
          <p>${escapeHtml(message)}</p>
        </div>`;
      if (this.resultsCount) this.resultsCount.textContent = "Search unavailable";
    },

    renderResults(query, results, message) {
      if (!this.resultsContainer) return;

      if (this.resultsCount) {
        this.resultsCount.textContent = `${results.length} result${results.length === 1 ? "" : "s"} for "${query}"`;
      }

      if (!results.length) {
        this.resultsContainer.innerHTML = `
          <div class="no-results">
            <i class="fas fa-search"></i>
            <p>${escapeHtml(message || "No results found. Try different keywords, or crawl some seed pages first.")}</p>
          </div>`;
        return;
      }

      const list = document.createElement("div");
      list.className = "results-list fade-in";
      results.forEach((result) => {
        const item = document.createElement("div");
        item.className = "result-item text fade-in";
        item.innerHTML = `
          <div class="result-content">
            <h3><a href="${escapeHtml(result.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(result.title)}</a></h3>
            <p class="result-description">${escapeHtml(result.description)}</p>
            <div class="result-meta">
              <span class="result-url">${escapeHtml(result.url)}</span>
            </div>
            <div class="result-actions">
              <button class="bookmark-button" title="Bookmark"><i class="fas fa-bookmark"></i></button>
              <button class="share-button" title="Copy link"><i class="fas fa-share"></i></button>
            </div>
          </div>`;
        item.querySelector(".bookmark-button").addEventListener("click", () => {
          if ($("save-bookmarks-toggle") == null || $("save-bookmarks-toggle").checked) {
            BookmarksPanel.add(result);
            Notify.show("Bookmark added");
          }
        });
        item.querySelector(".share-button").addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText(result.url);
            Notify.show("Link copied to clipboard");
          } catch (e) {
            Notify.show("Could not copy link");
          }
        });
        list.appendChild(item);
      });

      this.resultsContainer.innerHTML = "";
      this.resultsContainer.appendChild(list);
    },

    applyTypeFilter(filter) {
      qsa(".result-item").forEach((el) => {
        el.style.display = filter === "all" || el.classList.contains(filter) ? "" : "none";
      });
    },
  };

  // ---------------------------------------------------------------------
  // Bookmarks (stored in localStorage; this is the search engine's own
  // bookmark list, separate from Null Browser's bookmark manager)
  // ---------------------------------------------------------------------
  const BookmarksPanel = {
    key: "nullSearchBookmarks",
    load() {
      try { return JSON.parse(localStorage.getItem(this.key) || "[]"); }
      catch (e) { return []; }
    },
    save(list) {
      try { localStorage.setItem(this.key, JSON.stringify(list)); } catch (e) { /* ignore */ }
    },
    add(result) {
      const list = this.load();
      if (!list.some((b) => b.url === result.url)) {
        list.unshift({ url: result.url, title: result.title, description: result.description });
        this.save(list.slice(0, 200));
      }
      this.render();
    },
    remove(url) {
      this.save(this.load().filter((b) => b.url !== url));
      this.render();
    },
    render() {
      const container = document.querySelector(".bookmarks-container");
      if (!container) return;
      const list = this.load();
      if (!list.length) {
        container.innerHTML = `<p class="no-results">No bookmarks yet. Click the bookmark icon on a result to save it.</p>`;
        return;
      }
      container.innerHTML = list.map((b) => `
        <div class="history-item">
          <i class="fas fa-bookmark"></i>
          <div class="history-content">
            <div class="history-query"><a href="${escapeHtml(b.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(b.title)}</a></div>
            <div class="history-time">${escapeHtml(b.url)}</div>
          </div>
          <button class="delete-history" data-url="${escapeHtml(b.url)}"><i class="fas fa-times"></i></button>
        </div>`).join("");
      qsa(".delete-history", container).forEach((btn) => {
        btn.addEventListener("click", () => this.remove(btn.dataset.url));
      });
    },
  };

  // ---------------------------------------------------------------------
  // Search history
  // ---------------------------------------------------------------------
  const HistoryPanel = {
    key: "nullSearchHistory",
    load() {
      try { return JSON.parse(localStorage.getItem(this.key) || "[]"); }
      catch (e) { return []; }
    },
    save(list) {
      try { localStorage.setItem(this.key, JSON.stringify(list)); } catch (e) { /* ignore */ }
    },
    add(query) {
      const list = this.load();
      list.unshift({ query, timestamp: new Date().toISOString() });
      this.save(list.slice(0, 100));
    },
    remove(query) {
      this.save(this.load().filter((h) => h.query !== query));
      this.render();
    },
    clear() {
      this.save([]);
      this.render();
    },
    render() {
      const container = document.querySelector(".history-container");
      if (!container) return;
      const list = this.load();
      if (!list.length) {
        container.innerHTML = `<p class="no-results">No search history yet.</p>`;
        return;
      }
      container.innerHTML = list.map((h) => `
        <div class="history-item">
          <i class="fas fa-history"></i>
          <div class="history-content">
            <div class="history-query">${escapeHtml(h.query)}</div>
            <div class="history-time">${new Date(h.timestamp).toLocaleString()}</div>
          </div>
          <button class="delete-history" data-query="${escapeHtml(h.query)}"><i class="fas fa-times"></i></button>
        </div>`).join("");
      qsa(".delete-history", container).forEach((btn) => {
        btn.addEventListener("click", () => this.remove(btn.dataset.query));
      });
    },
  };

  // ---------------------------------------------------------------------
  // Nav icon buttons -> jump to the matching results tab
  // ---------------------------------------------------------------------
  function wireNavShortcuts() {
    const historyNavBtn = document.querySelector("header #history-toggle");
    if (historyNavBtn) {
      historyNavBtn.addEventListener("click", () => {
        document.querySelector('.tab-button[data-tab="history"]')?.click();
      });
    }
    const bookmarksNavBtn = document.querySelector("header #bookmarks-toggle");
    if (bookmarksNavBtn) {
      bookmarksNavBtn.addEventListener("click", () => {
        document.querySelector('.tab-button[data-tab="bookmarks"]')?.click();
      });
    }
  }

  // ---------------------------------------------------------------------
  // Settings panel
  // ---------------------------------------------------------------------
  const SettingsPanel = {
    init() {
      const panel = $("settings-panel");
      const toggle = $("settings-toggle");
      const closeBtn = $("close-settings");
      const saveBtn = $("save-settings");
      if (toggle && panel) toggle.addEventListener("click", () => panel.classList.toggle("active"));
      if (closeBtn && panel) closeBtn.addEventListener("click", () => panel.classList.remove("active"));
      if (saveBtn) {
        saveBtn.addEventListener("click", () => {
          try {
            const settings = {
              voiceSearch: $("voice-search-toggle")?.checked ?? true,
              suggestions: $("suggestions-toggle")?.checked ?? true,
              saveHistory: $("save-history-toggle")?.checked ?? true,
              saveBookmarks: $("save-bookmarks-toggle")?.checked ?? true,
            };
            localStorage.setItem("nullSearchSettings", JSON.stringify(settings));
            Notify.show("Settings saved");
          } catch (e) {
            Notify.show("Could not save settings");
          }
          panel.classList.remove("active");
        });
      }

      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          panel?.classList.remove("active");
          $("advanced-search-panel")?.classList.remove("active");
        }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          $("search-input")?.focus();
        }
      });

      try {
        const saved = JSON.parse(localStorage.getItem("nullSearchSettings") || "{}");
        if ("voiceSearch" in saved && $("voice-search-toggle")) $("voice-search-toggle").checked = saved.voiceSearch;
        if ("suggestions" in saved && $("suggestions-toggle")) $("suggestions-toggle").checked = saved.suggestions;
        if ("saveHistory" in saved && $("save-history-toggle")) $("save-history-toggle").checked = saved.saveHistory;
        if ("saveBookmarks" in saved && $("save-bookmarks-toggle")) $("save-bookmarks-toggle").checked = saved.saveBookmarks;
      } catch (e) { /* ignore corrupt settings */ }
    },
  };

  // ---------------------------------------------------------------------
  // Lightweight toast notifications
  // ---------------------------------------------------------------------
  const Notify = {
    show(message) {
      const el = document.createElement("div");
      el.className = "notification";
      el.textContent = message;
      document.body.appendChild(el);
      requestAnimationFrame(() => el.classList.add("show"));
      setTimeout(() => {
        el.classList.remove("show");
        setTimeout(() => el.remove(), 300);
      }, 2500);
    },
  };

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    try { ThemeManager.init(); } catch (e) { console.error("Theme init failed", e); }
    try { Search.init(); } catch (e) { console.error("Search init failed", e); }
    try { SettingsPanel.init(); } catch (e) { console.error("Settings init failed", e); }
    try { wireNavShortcuts(); } catch (e) { console.error("Nav shortcuts failed", e); }
    try { BookmarksPanel.render(); HistoryPanel.render(); } catch (e) { /* panels are optional */ }
  });

  window.NullSearch = { ThemeManager, Search, BookmarksPanel, HistoryPanel, Notify };
})();
