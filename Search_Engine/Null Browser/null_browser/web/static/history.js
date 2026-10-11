"use strict";
(function () {
  let query = new URLSearchParams(location.search).get("q") || "";
  let rows = [], selected = new Set(), done = false, loading = false;
  const content = shell({
    active: "history", title: "History", searchPlaceholder: "Search history", onSearch: q => { query = q; reload(); },
    sidebarExtra: [h("hr"), h("button", { onclick: () => clearBrowsingDialog(reload) }, h("span", { html: icon("trash") }), "Clear browsing data")]
  });
  if (query) $("#q").value = query;
  const bar = h("div", { class: "toolbar", style: "display:none" });
  const card = h("div", { class: "card" });
  const more = h("button", { class: "btn", style: "margin:16px auto;display:none", onclick: () => load() }, "Load more");
  content.append(h("h1", {}, "History"), bar, card, more);
  function renderBar() {
    bar.style.display = selected.size ? "flex" : "none"; bar.innerHTML = "";
    bar.append(h("b", {}, selected.size + " selected"), h("button", { class: "btn danger", onclick: delSelected }, h("span", { html: icon("trash", "sm") }), "Delete"),
      h("button", { class: "btn ghost", onclick: () => { selected.clear(); render(); } }, "Cancel"));
  }
  function render() {
    card.innerHTML = "";
    if (!rows.length) { card.append(h("div", { class: "empty" }, loading ? "Loading…" : query ? "No results found" : "Your browsing history will appear here")); more.style.display = "none"; renderBar(); return; }
    let lastDay = "";
    for (const r of rows) {
      const day = dayLabel(r.ts);
      if (day !== lastDay) { card.append(h("div", { class: "day" }, day)); lastDay = day; }
      card.append(h("div", { class: "row click", onclick: e => { if (!e.target.closest("input,button")) location.href = r.url; } },
        h("input", { type: "checkbox", checked: selected.has(r.id), onchange: e => { e.target.checked ? selected.add(r.id) : selected.delete(r.id); renderBar(); } }),
        h("span", { class: "muted", style: "width:62px;font-size:12px" }, fmtTime(r.ts)), favImg(r.url),
        h("div", { class: "grow" }, h("div", { class: "title ellipsis" }, r.title || shortUrl(r.url)), h("div", { class: "sub ellipsis" }, shortUrl(r.url))),
        h("button", { class: "btn icon ghost", title: "Remove from history", html: icon("x", "sm"), onclick: async () => { await api("history/delete", { ids: [r.id] }); rows = rows.filter(x => x.id !== r.id); render(); } })));
    }
    more.style.display = done ? "none" : "block"; renderBar();
  }
  async function load() {
    if (loading) return; loading = true;
    const before = rows.length ? rows[rows.length - 1].ts : null;
    const r = await api("history/list", { q: query, before, limit: 150 });
    rows = rows.concat(r.items); done = r.items.length < 150; loading = false; render();
  }
  function reload() { rows = []; done = false; selected.clear(); render(); load(); }
  async function delSelected() { await api("history/delete", { ids: [...selected] }); selected.clear(); reload(); }
  reload();
  if (new URLSearchParams(location.search).get("clear") === "1") clearBrowsingDialog(reload);   // Ctrl+Shift+Del
})();
