"use strict";
(function () {
  let query = "", folder = "", all = [], folders = [];
  const content = shell({ active: "bookmarks", title: "Bookmarks", searchPlaceholder: "Search bookmarks", onSearch: q => { query = q; render(); },
    sidebarExtra: [h("hr"), h("button", { onclick: () => edit() }, h("span", { html: icon("plus") }), "Add bookmark"),
      h("button", { onclick: exportHtml }, h("span", { html: icon("download") }), "Export bookmarks"),
      h("button", { onclick: () => $("#file").click() }, h("span", { html: icon("folder") }), "Import bookmarks"),
      h("input", { type: "file", id: "file", accept: ".html,.htm", style: "display:none", onchange: importHtml })] });
  const chips = h("div", { class: "chips", style: "margin-bottom:14px" });
  const card = h("div", { class: "card" });
  content.append(h("h1", {}, "Bookmarks"), chips, card);
  async function load() { const r = await api("bookmarks/list"); all = r.items; folders = r.folders; render(); }
  function render() {
    chips.innerHTML = "";
    chips.append(h("button", { class: "btn " + (folder === "" ? "primary" : ""), onclick: () => { folder = ""; render(); } }, "All"));
    folders.forEach(f => chips.append(h("button", { class: "btn " + (folder === f ? "primary" : ""), onclick: () => { folder = f; render(); } }, h("span", { html: icon("folder", "sm") }), f)));
    card.innerHTML = "";
    const q = query.toLowerCase();
    const items = all.filter(b => (!folder || b.folder === folder) && (!q || (b.title + " " + b.url).toLowerCase().includes(q)));
    if (!items.length) { card.append(h("div", { class: "empty" }, all.length ? "No bookmarks match" : "Bookmarks you add appear here. Press Ctrl+D on any page.")); return; }
    items.forEach(b => card.append(h("div", { class: "row click", onclick: e => { if (!e.target.closest("button")) location.href = b.url; } }, favImg(b.url),
      h("div", { class: "grow" }, h("div", { class: "title ellipsis" }, b.title || b.url), h("div", { class: "sub ellipsis" }, shortUrl(b.url))),
      h("span", { class: "badge" }, b.folder),
      h("button", { class: "btn icon ghost", title: "Edit", html: icon("edit", "sm"), onclick: () => edit(b) }),
      h("button", { class: "btn icon ghost", title: "Delete", html: icon("trash", "sm"), onclick: async () => { await api("bookmarks/delete", { id: b.id }); toast("Bookmark deleted"); load(); } }))));
  }
  function edit(b) {
    const name = h("input", { type: "text", value: b ? b.title : "" }), url = h("input", { type: "url", value: b ? b.url : "https://" });
    const fo = h("input", { type: "text", value: b ? b.folder : (folder || "Bookmarks bar"), list: "fl" });
    const dl = h("datalist", { id: "fl" }, folders.map(f => h("option", { value: f })));
    const d = h("dialog", {}, h("h3", {}, b ? "Edit bookmark" : "Add bookmark"), h("label", {}, "Name"), name, h("label", {}, "URL"), url, h("label", {}, "Folder"), fo, dl,
      h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => d.close() }, "Cancel"),
        h("button", { class: "btn primary", onclick: async () => {
          const body = { title: name.value, url: url.value, folder: fo.value || "Bookmarks bar" };
          await api(b ? "bookmarks/update" : "bookmarks/add", b ? { id: b.id, ...body } : body); d.close(); load();
        } }, "Save")));
    d.addEventListener("close", () => d.remove()); document.body.append(d); d.showModal(); name.focus();
  }
  async function exportHtml() {
    const r = await api("bookmarks/export"); const a = h("a", { href: URL.createObjectURL(new Blob([r.html], { type: "text/html" })), download: "null-bookmarks.html" });
    document.body.append(a); a.click(); a.remove();
  }
  async function importHtml(e) {
    const f = e.target.files[0]; if (!f) return; const html = await f.text();
    const r = await api("bookmarks/import", { html }); toast(`Imported ${r.added} bookmarks`); load(); e.target.value = "";
  }
  load();
})();
