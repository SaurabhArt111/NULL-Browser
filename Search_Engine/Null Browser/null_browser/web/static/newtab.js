"use strict";
(async function () {
  const d = await api("newtab/data");
  document.title = "New Tab";
  document.body.innerHTML = "";
  document.body.style.cssText = "display:flex;flex-direction:column;align-items:center;min-height:100vh;padding:0 24px";
  const status = h("span", { class: "badge" }, "");
  const label = () => { const e = d.engines[eng.value]; input.placeholder = `Search ${e.name} or type a URL`; };
  const eng = h("select", { onchange: async e => { await api("settings/set", { key: "search_engine", value: e.target.value }); input.focus(); label(); } },
    Object.values(d.engines).map(e => h("option", { value: e.id, selected: e.id === d.engine }, e.name)));
  const input = h("input", { type: "text", placeholder: "Search or type a URL", autocomplete: "off", spellcheck: "false", autofocus: true });
  async function go(q) { if (!q) return; const r = await api("search/resolve", { q }); location.href = r.url; }
  input.addEventListener("keydown", e => { if (e.key === "Enter") go(input.value.trim()); });
  const box = h("div", { class: "search", style: "width:min(640px,92vw);max-width:none;margin-top:6px;flex:none" }, h("span", { html: icon("search") }), input);
  input.style.cssText = "padding:15px 20px 15px 48px;font-size:16px;box-shadow:var(--shadow);background:var(--surface)";
  label();
  const tiles = [], seen = new Set();
  [...d.bookmarks.map(b => ({ title: b.title, url: b.url })), ...d.top.map(t => ({ title: t.title, url: t.url }))].forEach(t => {
    let host; try { host = new URL(t.url).host; } catch (e) { return; }
    if (seen.has(host) || tiles.length >= 10) return; seen.add(host); tiles.push({ ...t, host });
  });
  const grid = h("div", { style: "display:flex;flex-wrap:wrap;justify-content:center;gap:10px;width:min(680px,94vw);margin-top:34px;flex:none" },
    tiles.map(t => h("a", { href: t.url, style: "display:flex;flex-direction:column;align-items:center;gap:8px;padding:14px 8px;width:116px;border-radius:16px;color:var(--text);text-decoration:none", class: "tile" },
      h("div", { style: "width:48px;height:48px;border-radius:50%;background:var(--surface);box-shadow:var(--shadow);display:grid;place-items:center" }, (() => { const i = favImg(t.url); i.style.cssText = "width:26px;height:26px"; return i; })()),
      h("div", { class: "ellipsis", style: "font-size:12px;max-width:100%" }, (t.title || t.host).slice(0, 24)))));
  grid.addEventListener("mouseover", e => { const a = e.target.closest(".tile"); if (a) a.style.background = "var(--surface-2)"; });
  grid.addEventListener("mouseout", e => { const a = e.target.closest(".tile"); if (a) a.style.background = ""; });
  const links = h("div", { style: "position:fixed;top:14px;right:18px;display:flex;gap:6px" },
    [["history", "history"], ["bookmarks", "bookmark"], ["downloads", "download"], ["settings", "settings"]].map(([p, ic]) =>
      h("a", { href: "null://" + p, title: p[0].toUpperCase() + p.slice(1), class: "btn icon ghost", html: icon(ic) })));
  const engLine = h("div", { style: "display:flex;gap:10px;align-items:center;margin-top:16px;color:var(--muted);font-size:13px" }, "Search with", eng, status);
  const ns = d.null_search;
  status.textContent = { running: "Null Search online", external: "Null Search online", starting: "Null Search starting…", stopped: "Null Search offline", unavailable: "Null Search unavailable", error: "Null Search error" }[ns.state] || ns.state;
  status.className = "badge " + (["running", "external"].includes(ns.state) ? "ok" : ns.state === "starting" ? "warn" : "");
  if (d.private) {
    document.body.append(links, h("div", { style: "margin-top:16vh;text-align:center" },
      h("div", { html: icon("eye").replace('class="i ', 'style="width:56px;height:56px" class="i ') }),
      h("h1", { style: "font-size:30px" }, "You're InPrivate"),
      h("p", { class: "muted", style: "max-width:520px" }, "Null Browser won't save your history, cookies or site data from this window. Downloads and bookmarks you create are kept. Your activity may still be visible to the sites you visit, your employer or school, and your internet provider.")),
      box, engLine);
  } else {
    document.body.append(links, h("div", { style: "margin-top:15vh;display:flex;align-items:center;gap:14px" },
      h("div", { class: "logo", style: "width:60px;height:60px;font-size:34px;border-radius:18px" }, "N"),
      h("div", { style: "font-size:54px;font-weight:600;letter-spacing:-1.5px" }, "Null")), box, engLine, grid);
  }
  input.focus();
})();
