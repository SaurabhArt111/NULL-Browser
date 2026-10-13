/* Null Browser internal pages - shared helpers (no inline scripts: pages are CSP-locked) */
"use strict";
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
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
async function api(name, body = {}) {
  let r;
  try {
    const tok = (document.querySelector('meta[name="null-token"]') || {}).content || "";
    const call = (n, b) => fetch("/api/" + n, { method: "POST", headers: { "Content-Type": "application/json", "X-Null-Token": tok }, body: JSON.stringify(b) });
    const json = JSON.stringify(body);
    if (json.length > 8000) {                       // the browser core can only take small request bodies in one go: send pieces
      const id = Math.random().toString(36).slice(2) + Date.now().toString(36), size = 6000, n = Math.ceil(json.length / size);
      for (let i = 0; i < n; i++) {
        const pr = await call("blob/put", { id, i, n, data: json.slice(i * size, (i + 1) * size) });
        if (!pr.ok) { const e = await pr.json().catch(() => ({})); toast(e.error || "Upload failed"); throw new Error(e.error || pr.status); }
      }
      r = await call(name, { _blob: id });
    } else r = await call(name, body);
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
  const top = h("div", { class: "topbar" }, h("div", { class: "brand", title: "Null Browser", "data-hint": "You are on a built-in page" }, h("div", { class: "logo" }, "N"), title), search);
  const side = h("nav", { class: "sidebar nav" },
    ...(nav || NAV).map(([id, label, ic, href]) => h("a", { href: href || `null://${id}`, title: label, class: id === active ? "active" : "" }, h("span", { html: icon(ic) }), label)),
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
  const range = h("select", {}, [["15min", "Last 15 minutes"], ["hour", "Last hour"], ["day", "Last 24 hours"], ["week", "Last 7 days"], ["month", "Last 4 weeks"], ["all", "All time"]].map(([v, l]) => h("option", { value: v, selected: v === "15min" }, l)));
  /* Like Chrome: only the cache is ticked by default. History, cookies (your sign-ins) and the rest are kept unless you tick them. */
  const opts = [["history", "Browsing history", false, "Pages you visited"], ["cookies", "Cookies and other site data", false, "You will be signed out of most sites"], ["cache", "Cached images and files", true, "Frees disk space; sites may load slower once"], ["downloads", "Download history", false, "The list only; files stay on disk"], ["site_perms", "Site settings and permissions", false, "Camera, location, pop-up choices per site"]];
  const boxes = opts.map(([k, l, on, sub]) => h("label", { style: "display:flex;gap:10px;align-items:flex-start;margin:10px 0;color:var(--text);font-size:14px" }, h("input", { type: "checkbox", id: "c_" + k, checked: on, style: "width:auto;margin-top:3px" }), h("span", {}, l, h("div", { class: "muted", style: "font-size:12px" }, sub))));
  const d = h("dialog", {}, h("h3", {}, "Clear browsing data"), h("label", {}, "Time range"), range, h("div", { style: "margin-top:10px" }, boxes),
    h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => d.close() }, "Cancel"),
      h("button", { class: "btn primary", onclick: async () => {
        const types = opts.map(o => o[0]).filter(k => $("#c_" + k).checked);
        await api("privacy/clear", { types, range: range.value }); d.close(); toast("Browsing data cleared"); after && after();
      } }, "Clear data")));
  d.addEventListener("close", () => d.remove()); document.body.append(d); d.showModal();
}

/* Hover tips for every control: <el title="Name" data-hint="what it does" data-key="Ctrl+X">. The native title is removed
   so the browser's plain tooltip never competes with this one. Works for keyboard focus too. */
(function tips() {
  const el = document.createElement("div"); el.className = "tip"; el.setAttribute("role", "tooltip"); el.hidden = true;
  let timer = 0, owner = null;
  const HINTS = {
    "Edit": "Change the name, address or folder", "Delete": "Remove this item for good", "Resume": "Continue this download", "Pause": "Pause this download for now",
    "Cancel": "Stop and discard this download", "Open file": "Open with the default app", "Show in folder": "Reveal the file in your file manager",
    "Remove from list": "Hide it here; the file stays on disk", "Remove from history": "Forget this visit", "History": "Pages you have visited",
    "Bookmarks": "Pages you saved", "Downloads": "Files you downloaded", "Settings": "Privacy, appearance, search engine and more",
    "Customize": "Change the background, shortcuts and layout of this page", "Back": "Go back one level", "Remove rule": "Stop blocking this pattern",
    "Remove search engine": "Delete this custom search engine"
  };
  const find = n => n && n.closest ? n.closest("[title],[data-tip-title]") : null;
  function adopt(n) { if (n.hasAttribute("title")) { n.setAttribute("data-tip-title", n.getAttribute("title")); n.removeAttribute("title"); } }
  function show(n) {
    const t = n.getAttribute("data-tip-title"); if (!t) return;
    el.textContent = "";
    const b = document.createElement("b"); b.textContent = t; el.append(b);
    const k = n.getAttribute("data-key"); if (k) { const s = document.createElement("kbd"); s.textContent = k; el.append(s); }
    const hint = n.getAttribute("data-hint") || HINTS[t]; if (hint) { const d = document.createElement("div"); d.textContent = hint; el.append(d); }
    el.hidden = false; owner = n;
    const r = n.getBoundingClientRect(), w = el.offsetWidth, hgt = el.offsetHeight;
    let x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8);
    let y = r.bottom + 8; if (y + hgt > innerHeight - 8) y = Math.max(8, r.top - hgt - 8);
    el.style.left = x + "px"; el.style.top = y + "px";
  }
  function hide() { clearTimeout(timer); el.hidden = true; owner = null; }
  document.addEventListener("mouseover", e => { const n = find(e.target); if (!n) return; adopt(n); if (n === owner) return; hide(); timer = setTimeout(() => show(n), 450); });
  document.addEventListener("mouseout", e => { const n = find(e.target); if (n && !n.contains(e.relatedTarget)) hide(); });
  document.addEventListener("focusin", e => { const n = find(e.target); if (n) { adopt(n); if (e.target.matches(":focus-visible")) show(n); } });
  for (const t of ["focusout", "mousedown", "keydown", "scroll", "wheel", "blur"]) addEventListener(t, hide, true);
  addEventListener("DOMContentLoaded", () => document.body.append(el));
  if (document.body) document.body.append(el);
  new MutationObserver(() => { if (!el.isConnected && document.body) document.body.append(el); }).observe(document.documentElement, { childList: true });
})();
