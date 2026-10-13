"use strict";
(function () {
  const $ = s => document.querySelector(s);
  const hdr = { "Content-Type": "application/json", "X-Null-Search": "1" };
  const msg = $("#crawl-msg"), bar = $("#crawl-bar"), go = $("#crawl-go"), stop = $("#crawl-stop");
  let poll = 0;

  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: hdr, body: JSON.stringify(body || {}) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || d.error || r.statusText);
    return d;
  }
  function show(s) {
    go.disabled = s.running; stop.disabled = !s.running;
    bar.hidden = !s.running && !s.finished_at;
    bar.max = s.max_pages || 100; bar.value = s.pages_indexed || 0;
    msg.textContent = s.running
      ? `Crawling… ${s.pages_indexed}/${s.max_pages} pages, ${s.queued} queued, ${s.errors} errors. ${s.last_url ? "Now: " + s.last_url.slice(0, 80) : ""}`
      : s.finished_at ? `Finished (${s.message}): ${s.pages_indexed} pages indexed, ${s.skipped} skipped, ${s.errors} errors.` : "No crawl has run yet.";
  }
  async function tick() {
    try {
      const s = await (await fetch("/api/crawl/status")).json();
      show(s);
      if (s.running) { poll = setTimeout(tick, 1000); } else if (poll) { poll = 0; setTimeout(() => location.reload(), 800); }
    } catch (e) { poll = setTimeout(tick, 3000); }
  }
  $("#crawl-form").addEventListener("submit", async e => {
    e.preventDefault();
    const urls = $("#urls").value.split(/\s+/).map(s => s.trim()).filter(Boolean);
    try {
      show(await post("/api/crawl", { urls, max_pages: +$("#max_pages").value || 50, depth: +$("#depth").value, same_site: $("#same_site").checked }));
      poll = setTimeout(tick, 800);
    } catch (err) { msg.textContent = "Could not start: " + err.message; }
  });
  stop.addEventListener("click", () => post("/api/crawl/stop"));
  document.querySelectorAll("[data-delete-url]").forEach(b => b.addEventListener("click", async () => { await post("/api/index/delete", { url: b.dataset.deleteUrl }); location.reload(); }));
  document.querySelectorAll("[data-delete-host]").forEach(b => b.addEventListener("click", async () => {
    if (confirm("Remove every page from " + b.dataset.deleteHost + "?")) { await post("/api/index/delete", { host: b.dataset.deleteHost }); location.reload(); }
  }));
  $("#clear-all").addEventListener("click", async () => { if (confirm("Delete the entire local index? This cannot be undone.")) { await post("/api/index/clear"); location.reload(); } });
  fetch("/api/crawl/status").then(r => r.json()).then(s => { show(s); if (s.running) poll = setTimeout(tick, 1000); });
})();
