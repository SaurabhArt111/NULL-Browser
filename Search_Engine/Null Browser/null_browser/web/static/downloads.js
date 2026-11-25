"use strict";
(function () {
  let query = "", items = [];
  const content = shell({ active: "downloads", title: "Downloads", searchPlaceholder: "Search downloads", onSearch: q => { query = q; render(); },
    sidebarExtra: [h("hr"), h("button", { onclick: async () => { await api("downloads/clear"); load(); } }, h("span", { html: icon("trash") }), "Clear all")] });
  const card = h("div", { class: "card" });
  content.append(h("h1", {}, "Downloads"), card);
  const stateBadge = { completed: ["Completed", "ok"], cancelled: ["Cancelled", ""], interrupted: ["Failed", "err"], in_progress: ["Downloading", "warn"] };
  function render() {
    const q = query.toLowerCase();
    const list = items.filter(d => !q || ((d.filename || "") + d.url).toLowerCase().includes(q));
    card.innerHTML = "";
    if (!list.length) { card.append(h("div", { class: "empty" }, "No downloads yet")); return; }
    let lastDay = "";
    for (const d of list) {
      const day = dayLabel(d.started); if (day !== lastDay) { card.append(h("div", { class: "day" }, day)); lastDay = day; }
      const pct = d.total > 0 ? Math.min(100, d.received / d.total * 100) : 0, active = d.state === "in_progress";
      const [txt, cls] = stateBadge[d.state] || [d.state, ""];
      const missing = d.state === "completed" && !d.exists;
      card.append(h("div", { class: "row" }, h("span", { html: icon("file") }),
        h("div", { class: "grow" },
          h("div", { class: "title ellipsis" }, missing ? h("s", {}, d.filename) : d.filename),
          h("div", { class: "sub ellipsis" }, active ? `${fmtBytes(d.received)}${d.total > 0 ? " of " + fmtBytes(d.total) : ""}${d.paused ? " - paused" : ""}` :
            [missing ? "File moved or deleted - " : "", /^https?:/.test(d.url) ? h("a", { href: d.url, title: d.url, style: "color:inherit" }, shortUrl(d.url)) : shortUrl(d.url)]),
          active ? h("div", { class: "progress" }, h("i", { style: `width:${d.total > 0 ? pct : 100}%;${d.total > 0 ? "" : "opacity:.4"}` })) : ""),
        h("span", { class: "badge " + cls }, txt),
        active ? [h("button", { class: "btn icon ghost", title: d.paused ? "Resume" : "Pause", html: icon(d.paused ? "play" : "pause", "sm"), onclick: () => act(d.paused ? "resume" : "pause", d) }),
                  h("button", { class: "btn icon ghost", title: "Cancel", html: icon("x", "sm"), onclick: () => act("cancel", d) })] :
          [d.state === "completed" && !missing ? h("button", { class: "btn icon ghost", title: "Open file", html: icon("external", "sm"), onclick: () => act("open", d) }) : "",
           d.path ? h("button", { class: "btn icon ghost", title: "Show in folder", html: icon("folder", "sm"), onclick: () => act("show", d) }) : "",
           h("button", { class: "btn icon ghost", title: "Remove from list", html: icon("trash", "sm"), onclick: () => act("remove", d) })]));
    }
  }
  async function act(a, d) { await api("downloads/" + a, { id: d.id }); load(); }
  // Only redraw when something changed (redrawing every second made the list flicker and lost hover / selection),
  // and poll quickly only while a download is running.
  let last = "", timer = 0;
  async function load() {
    const next = (await api("downloads/list")).items, sig = JSON.stringify(next);
    if (sig !== last) { last = sig; items = next; render(); }
    clearTimeout(timer);
    timer = setTimeout(() => { if (!document.hidden) load().catch(() => {}); else load.pending = true; }, items.some(d => d.state === "in_progress") ? 700 : 4000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && load.pending) { load.pending = false; load().catch(() => {}); } });
  load();
})();
