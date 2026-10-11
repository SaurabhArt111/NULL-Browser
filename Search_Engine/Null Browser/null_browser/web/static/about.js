"use strict";
(async function () {
  const NAVX = [["about", "About", "info"], ["version", "Version", "cpu"], ["logs", "Logs & errors", "bug"], ["history", "History", "history"], ["settings", "Settings", "settings"]];
  const page = document.body.dataset.page;
  const c = shell({ active: page, title: page === "version" ? "Version" : "About Null Browser", nav: NAVX });
  const a = await api("about/info");
  if (page === "version") {
    c.append(h("h1", {}, "Version"), h("div", { class: "card" }, h("table", { class: "kv" }, Object.entries(a.versions).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v))))));
    return;
  }
  c.append(h("h1", {}, "Null Browser " + a.versions["Null Browser"]),
    h("p", { class: "muted" }, "A privacy-first desktop browser with its own interface, built-in pages, permission system, ad blocker and a linked local search engine."),
    h("h2", {}, "Internal pages"),
    h("div", { class: "card" }, a.pages.map(p => h("a", { class: "row click", href: p.url, style: "color:var(--text);text-decoration:none" }, h("span", { html: icon(p.icon) }), h("div", { class: "grow" }, h("div", { class: "title" }, p.url), h("div", { class: "sub" }, p.desc))))),
    h("h2", {}, "Keyboard shortcuts"),
    h("div", { class: "card" }, a.shortcuts.map(([k, d]) => h("div", { class: "row", style: "min-height:42px" }, h("div", { class: "grow" }, d), h("span", { class: "badge" }, k)))));
})();
