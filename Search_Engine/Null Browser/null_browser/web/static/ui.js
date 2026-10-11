/* Null Browser internal pages - shared helpers (no inline scripts: pages are CSP-locked) */
"use strict";
const ICONS = {
  history: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4z"/>',
  download: '<path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  folder: '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>', edit: '<path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4"/>',
  shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>', lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.4 0 2-1 1.6-2.1-.4-1.2.3-2.4 1.6-2.4H17a4 4 0 0 0 4-4C21 6.5 17 3 12 3z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7.5" r="1"/><circle cx="15" cy="7.5" r="1"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>', power: '<path d="M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0"/>',
  languages: '<path d="M4 5h9M8.5 3v2M6 5c0 4 3 8 7 9M12 5c-1 4-4 7-8 9M14 20l4-9 4 9M15.5 17h5"/>', accessibility: '<circle cx="12" cy="5" r="2"/><path d="M5 9l7 1 7-1M12 10v5l-3 6M12 15l3 6"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>', gauge: '<path d="M4 18a9 9 0 1 1 16 0"/><path d="m12 14 4-5"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>', check: '<path d="m5 12 5 5 9-10"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  bug: '<path d="M8 8a4 4 0 0 1 8 0v7a4 4 0 0 1-8 0zM3 13h5M16 13h5M4 7l4 3M20 7l-4 3M5 20l3-3M19 20l-3-3"/>', file: '<path d="M7 3h7l5 5v13H7zM14 3v5h5"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>', alert: '<path d="M12 3 2 20h20zM12 10v4M12 17v.5"/>', pause: '<path d="M8 5v14M16 5v14"/>', play: '<path d="m7 4 13 8-13 8z"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
};
function icon(name, cls = "") { return `<svg class="i ${cls}" viewBox="0 0 24 24">${ICONS[name] || ""}</svg>`; }

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") e.className = v; else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "value" || k === "disabled" || k === "selected") e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
async function api(name, body = {}) {
  let r;
  try {
    const tok = (document.querySelector('meta[name="null-token"]') || {}).content || "";
    r = await fetch("/api/" + name, { method: "POST", headers: { "Content-Type": "application/json", "X-Null-Token": tok }, body: JSON.stringify(body) });
  } catch (e) { toast("Browser connection lost"); throw e; }
  const data = await r.json().catch(() => ({ error: "Bad response" }));
  if (!r.ok || data.error) { toast(data.error || "Something went wrong"); throw new Error(data.error || r.status); }
  return data;
}
function toast(msg, ms = 2600) {
  $$(".toast").forEach(t => t.remove());
  const t = h("div", { class: "toast" }, msg); document.body.append(t); setTimeout(() => t.remove(), ms);
}
const fmtBytes = n => { if (!n || n < 0) return "0 B"; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + " " + u[i]; };
const fmtTime = t => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function dayLabel(t) {
  const d = new Date(t * 1000), n = new Date(), y = new Date(Date.now() - 864e5);
  const same = (a, b) => a.toDateString() === b.toDateString();
  const long = d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  return same(d, n) ? "Today - " + long : same(d, y) ? "Yesterday - " + long : d.toLocaleDateString([], { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}
const faviconUrl = u => "/_/favicon?u=" + encodeURIComponent(u);
function favImg(u) { const i = h("img", { class: "fav", src: faviconUrl(u), alt: "", loading: "lazy" }); i.onerror = () => { i.style.visibility = "hidden"; }; return i; }
const shortUrl = u => u.replace(/^https?:\/\//, "").replace(/\/$/, "");
function debounce(fn, ms = 200) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function confirmDialog(title, text, okLabel = "OK", danger = false) {
  return new Promise(res => {
    const d = h("dialog", {}, h("h3", {}, title), h("div", { class: "muted" }, text),
      h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => { d.close(); res(false); } }, "Cancel"),
        h("button", { class: "btn " + (danger ? "danger" : "primary"), onclick: () => { d.close(); res(true); } }, okLabel)));
    d.addEventListener("close", () => d.remove()); document.body.append(d); d.showModal();
  });
}
const NAV = [["history", "History", "history"], ["bookmarks", "Bookmarks", "bookmark"], ["downloads", "Downloads", "download"], ["settings", "Settings", "settings"]];
/* Builds the standard page frame and returns the .content element. */
function shell({ active, title, searchPlaceholder, onSearch, nav, sidebarExtra }) {
  document.title = title;
  document.body.innerHTML = "";
  const search = onSearch ? h("div", { class: "search" }, h("span", { html: icon("search") }), h("input", { type: "text", id: "q", placeholder: searchPlaceholder || "Search", autocomplete: "off", spellcheck: "false" })) : h("div", { class: "search" });
  const top = h("div", { class: "topbar" }, h("div", { class: "brand" }, h("div", { class: "logo" }, "N"), title), search);
  const side = h("nav", { class: "sidebar nav" },
    ...(nav || NAV).map(([id, label, ic, href]) => h("a", { href: href || `null://${id}`, class: id === active ? "active" : "" }, h("span", { html: icon(ic) }), label)),
    sidebarExtra || "");
  const content = h("main", { class: "content" });
  document.body.append(top, h("div", { class: "layout" }, side, content));
  if (onSearch) $("#q").addEventListener("input", debounce(e => onSearch(e.target.value.trim()), 180));
  return content;
}
function switchRow(label, sub, checked, onchange, extra) {
  return h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, label), sub ? h("div", { class: "sub" }, sub) : ""), extra || "",
    h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!checked, onchange: e => onchange(e.target.checked) }), h("span")));
}
function selectRow(label, sub, options, value, onchange, extra) {
  return h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, label), sub ? h("div", { class: "sub" }, sub) : ""), extra || "",
    h("select", { onchange: e => onchange(e.target.value) }, options.map(o => { const [v, l] = Array.isArray(o) ? o : [o, o]; return h("option", { value: v, selected: v === value }, l); })));
}

function clearBrowsingDialog(after) {
  const range = h("select", {}, [["hour", "Last hour"], ["day", "Last 24 hours"], ["week", "Last 7 days"], ["month", "Last 4 weeks"], ["all", "All time"]].map(([v, l]) => h("option", { value: v, selected: v === "all" }, l)));
  const opts = [["history", "Browsing history", true], ["downloads", "Download history", true], ["cookies", "Cookies and other site data", true], ["cache", "Cached images and files", true], ["site_perms", "Site settings and permissions", false]];
  const boxes = opts.map(([k, l, on]) => h("label", { style: "display:flex;gap:10px;align-items:center;margin:8px 0;color:var(--text);font-size:14px" }, h("input", { type: "checkbox", id: "c_" + k, checked: on, style: "width:auto" }), l));
  const d = h("dialog", {}, h("h3", {}, "Clear browsing data"), h("label", {}, "Time range"), range, h("div", { style: "margin-top:10px" }, boxes),
    h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => d.close() }, "Cancel"),
      h("button", { class: "btn primary", onclick: async () => {
        const types = opts.map(o => o[0]).filter(k => $("#c_" + k).checked);
        await api("privacy/clear", { types, range: range.value }); d.close(); toast("Browsing data cleared"); after && after();
      } }, "Clear data")));
  d.addEventListener("close", () => d.remove()); document.body.append(d); d.showModal();
}
