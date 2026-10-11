"use strict";
(async function () {
  const c = shell({ active: "logs", title: "Logs & errors", nav: [["about", "About", "info"], ["version", "Version", "cpu"], ["logs", "Logs & errors", "bug"], ["history", "History", "history"], ["settings", "Settings", "settings"]] });
  async function load() {
    const d = await api("logs/get"); c.innerHTML = "";
    c.append(h("h1", {}, "Logs & errors"), h("div", { class: "toolbar" },
      h("button", { class: "btn", onclick: load }, h("span", { html: icon("refresh", "sm") }), "Refresh"),
      h("button", { class: "btn", onclick: async () => { await api("app/open_data_dir"); } }, h("span", { html: icon("folder", "sm") }), "Open data folder"),
      h("span", { class: "muted" }, `${d.errors.length} captured error(s)`)),
      h("h2", {}, "Captured errors"),
      d.errors.length ? h("div", { class: "card" }, d.errors.slice().reverse().map(e => h("details", { class: "row", style: "display:block" }, h("summary", {}, new Date(e.t * 1000).toLocaleTimeString() + "  " + e.title), h("pre", {}, e.trace)))) : h("div", { class: "card" }, h("div", { class: "empty" }, "No errors captured this session")),
      h("h2", {}, "Recent log"), h("pre", { style: "max-height:480px" }, d.log.map(l => `${new Date(l.t * 1000).toLocaleTimeString()} ${l.level.padEnd(7)} ${l.msg}`).join("\n") || "(empty)"));
  }
  load();
})();
