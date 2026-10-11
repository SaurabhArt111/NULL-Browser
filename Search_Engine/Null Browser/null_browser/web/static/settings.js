"use strict";
(async function () {
  const D = await api("settings/get");
  const S = D.settings;
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const SECTIONS = [
    ["you", "You and Null Browser", "eye", "/"], ["privacy", "Privacy and security", "shield", "/privacy"], ["content", "Site settings", "sliders", "/content"],
    ["performance", "Performance", "gauge", "/performance"], ["appearance", "Appearance", "palette", "/appearance"], ["search", "Search engine", "search", "/search"],
    ["default", "Default browser", "globe", "/default"], ["startup", "On startup", "power", "/startup"], null,
    ["languages", "Languages", "languages", "/languages"], ["downloads", "Downloads", "download", "/downloads"], ["accessibility", "Accessibility", "accessibility", "/accessibility"],
    ["system", "System", "cpu", "/system"], ["reset", "Reset settings", "refresh", "/reset"], null, ["about", "About Null Browser", "info", "/about"],
  ];
  const ENFORCE = { engine: ["Prompts & decisions enforced", "ok"], setting: ["Enforced", "ok"], shim: ["Enforced (API gate)", "ok"], restart: ["Applies after restart", "warn"], stored: ["Saved, no engine hook yet", ""] };
  const ACCENTS = ["#6c5ce7", "#0a84ff", "#00b894", "#e17055", "#e84393", "#fdcb6e", "#2d3436", "#d63031"];
  function sectionKey() { if (path === "/") return "you"; return path.split("/")[1]; }
  const root = shell({ active: "settings", title: "Settings", searchPlaceholder: "Search settings", onSearch: onSearch, nav: [] });
  const side = $(".sidebar");
  side.innerHTML = "";
  SECTIONS.forEach(s => { if (!s) { side.append(h("hr")); return; } side.append(h("a", { href: "null://settings" + (s[3] === "/" ? "" : s[3]), class: sectionKey() === s[0] ? "active" : "" }, h("span", { html: icon(s[2]) }), s[1])); });
  const banner = h("div", { class: "card", style: "display:none;margin-bottom:16px;border-color:var(--warn)" },
    h("div", { class: "row" }, h("div", { class: "grow" }, h("b", {}, "Relaunch needed"), h("div", { class: "sub" }, "Some changes apply after Null Browser restarts.")), h("button", { class: "btn primary", onclick: () => api("app/restart") }, "Relaunch")));

  async function set(key, value, quiet) {
    await api("settings/set", { key, value }); S[key] = value;
    if (D.restart_keys.includes(key)) banner.style.display = "block";
    if (!quiet) toast("Saved", 1200);
  }
  const card = (...rows) => h("div", { class: "card", style: "margin-bottom:14px" }, rows.flat());
  const link = (title, sub, href, right) => h("a", { class: "row click", href, style: "color:var(--text);text-decoration:none" }, h("div", { class: "grow" }, h("div", { class: "title" }, title), sub ? h("div", { class: "sub" }, sub) : ""), right || "", h("span", { html: icon("chevron", "sm"), style: "color:var(--muted)" }));
  const actionRow = (title, sub, label, fn, cls = "") => h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, title), sub ? h("div", { class: "sub" }, sub) : ""), h("button", { class: "btn " + cls, onclick: fn }, label));
  const textRow = (title, sub, key, ph) => h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, title), sub ? h("div", { class: "sub" }, sub) : ""),
    h("input", { type: "text", value: S[key] || "", placeholder: ph || "", style: "width:260px", onchange: e => set(key, e.target.value.trim()) }));
  const R = {};

  R.you = () => {
    const ns = D.engine;
    return [h("h1", {}, "You and Null Browser"),
      card(textRow("Profile name", "Used in the menu and notifications. Null Browser keeps everything local - there is no account or sync.", "profile_name", "You"),
        h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Storage"), h("div", { class: "sub" }, D.meta.data_dir)), h("button", { class: "btn", onclick: () => api("app/open_data_dir") }, "Open folder"))),
      h("h2", {}, "Linked search engine"),
      card(link("Null Search", ["running", "external"].includes(ns.state) ? `Online at ${ns.url} - ${(ns.stats && ns.stats.documents) || 0} pages indexed` : (ns.detail || "Not running"), "null://settings/search",
        h("span", { class: "badge " + (["running", "external"].includes(ns.state) ? "ok" : "") }, ns.state))),
      h("h2", {}, "Quick links"),
      card(link("Site settings", "Permissions, cookies, JavaScript, pop-ups and more", "null://settings/content"), link("Clear browsing data", "History, cookies, cache and more", "null://settings/privacy"), link("Developer tools", "F12 opens DevTools docked to the page", "null://settings/system"))];
  };
  R.privacy = () => {
    const rules = h("div", { class: "card", style: "margin-bottom:14px" });
    const ruleIn = h("input", { type: "text", placeholder: "ads.example.com  or  ||tracker.example.net^", style: "width:300px" });
    async function loadRules() {
      const a = await api("adblock/info"); rules.innerHTML = "";
      rules.append(h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Custom block rules"), h("div", { class: "sub" }, `${a.rules_total} rules loaded, ${a.blocked_total} requests blocked this session`)), ruleIn, h("button", { class: "btn", onclick: async () => { if (!ruleIn.value.trim()) return; const r = await api("adblock/add_rule", { rule: ruleIn.value }); if (!r.rule) return toast("Not a valid domain rule"); ruleIn.value = ""; loadRules(); } }, "Add")));
      a.custom.forEach(r => rules.append(h("div", { class: "row", style: "min-height:44px" }, h("div", { class: "grow ellipsis" }, r), h("button", { class: "btn icon ghost", html: icon("x", "sm"), onclick: async () => { await api("adblock/remove_rule", { rule: r }); loadRules(); } }))));
      a.allow.forEach(r => rules.append(h("div", { class: "row", style: "min-height:44px" }, h("div", { class: "grow ellipsis" }, h("span", { class: "badge ok" }, "ads allowed"), "  " + r), h("button", { class: "btn icon ghost", html: icon("x", "sm"), onclick: async () => { await api("adblock/allow", { host: r, allow: false }); loadRules(); } }))));
    }
    loadRules();
    const exit = new Set(S.clear_on_exit || []);
    return [h("h1", {}, "Privacy and security"),
      card(actionRow("Clear browsing data", "Delete history, cookies, cache and more", "Clear data…", () => clearBrowsingDialog())),
      h("h2", {}, "Tracking protection"),
      card(switchRow("Block ads", "Built-in ad blocker (works without extensions)", S.adblock, v => set("adblock", v)),
        switchRow("Block trackers", "Analytics and tracking scripts loaded from other sites", S.block_trackers, v => set("block_trackers", v)),
        switchRow("Send “Do Not Track” and Global Privacy Control", "Asks sites not to sell or share your data", S.send_dnt, v => set("send_dnt", v)),
        link("Third-party cookies", "Currently: " + D.perm_defaults.cookies_label, "null://settings/content/cookies")),
      h("h2", {}, "Security"),
      card(switchRow("Upgrade address-bar URLs to HTTPS", "Typed addresses without a scheme try https:// first and fall back to http:// only if the secure connection fails", S.https_first, v => set("https_first", v)),
        link("Site settings", "Control what sites can use and show", "null://settings/content")),
      h("h2", {}, "Clear on exit"),
      card(h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Delete when Null Browser closes"), h("div", { class: "sub" }, "Choose what is wiped automatically")),
        h("div", { class: "chips" }, [["history", "History"], ["cookies", "Cookies"], ["cache", "Cache"], ["downloads", "Download list"]].map(([k, l]) => h("label", { class: "badge", style: "cursor:pointer;display:flex;gap:6px;align-items:center;padding:5px 10px" }, h("input", { type: "checkbox", checked: exit.has(k), onchange: e => { e.target.checked ? exit.add(k) : exit.delete(k); set("clear_on_exit", [...exit]); } }), l))))),
      h("h2", {}, "Ad blocker rules"), rules];
  };
  R.content = () => {
    const cat = D.catalog; const groups = [["Permissions", "Permissions"], ["Content", "Content"], ["Additional", "Additional content settings"]];
    const out = [h("h1", {}, "Site settings"), h("p", { class: "muted" }, "Choose what information sites can use and what they can show you. Each setting has a default and per-site exceptions. The badge on each setting says how it is enforced; nothing is faked."),
      card(actionRow("Reset all site permissions", "Removes every per-site exception you have set", "Reset…", async () => { if (await confirmDialog("Reset site permissions?", "All per-site allow/block decisions will be removed.", "Reset", true)) { await api("perm/reset_all"); toast("Site permissions reset"); location.reload(); } }, "danger"))];
    groups.forEach(([g, title]) => out.push(h("h2", {}, title), card(cat.filter(c => c.group === g).map(c => {
      const opt = c.options.find(o => o.value === c.current) || c.options[0];
      return link(c.label, c.desc, "null://settings/content/" + c.id, h("div", { style: "display:flex;gap:8px;align-items:center" }, c.exceptions ? h("span", { class: "badge" }, c.exceptions + " exception" + (c.exceptions > 1 ? "s" : "")) : "", h("span", { class: "badge " + ENFORCE[c.enforce][1] }, opt.label)));
    }))));
    return out;
  };
  R.contentDetail = (id) => {
    const c = D.catalog.find(x => x.id === id);
    if (!c) return [h("h1", {}, "Unknown setting"), h("a", { href: "null://settings/content" }, "Back to site settings")];
    const list = h("div", { class: "card", style: "margin-bottom:14px" });
    async function loadSites() {
      const r = await api("perm/sites", { feature: id }); list.innerHTML = "";
      if (!r.items.length) list.append(h("div", { class: "empty", style: "padding:26px" }, "No exceptions. Sites follow the default above."));
      r.items.forEach(s => list.append(h("div", { class: "row", style: "min-height:48px" }, favImg(s.origin), h("div", { class: "grow ellipsis" }, s.origin),
        h("select", { onchange: async e => { await api("perm/set_site", { origin: s.origin, feature: id, value: e.target.value }); toast("Saved", 1200); } }, c.options.map(o => h("option", { value: o.value, selected: o.value === s.value }, o.label))),
        h("button", { class: "btn icon ghost", title: "Remove exception", html: icon("trash", "sm"), onclick: async () => { await api("perm/set_site", { origin: s.origin, feature: id, value: "default" }); loadSites(); } }))));
    }
    if (c.per_site) loadSites();
    const radios = c.options.map(o => h("label", { class: "row click", style: "cursor:pointer" }, h("input", { type: "radio", name: "def", value: o.value, checked: o.value === c.current, style: "accent-color:var(--accent)",
      onchange: async () => { await api("perm/set_default", { feature: id, value: o.value }); c.current = o.value; if (id === "js_optimization") banner.style.display = "block"; toast("Saved", 1200); } }), h("div", { class: "grow" }, h("div", { class: "title" }, o.label))));
    const [elabel, ecls] = ENFORCE[c.enforce];
    const out = [h("div", { class: "toolbar" }, h("a", { class: "btn icon ghost", href: "null://settings/content", html: icon("chevron").replace("<svg", '<svg style="transform:rotate(180deg)"') }), h("h1", { style: "margin:0" }, c.label)),
      h("p", { class: "muted" }, c.desc + ". ", h("span", { class: "badge " + ecls }, elabel)), h("h2", {}, "Default behavior"), card(radios)];
    if (c.per_site) {
      const input = h("input", { type: "text", placeholder: "https://example.com", style: "width:260px" });
      out.push(h("h2", {}, "Customized behaviors"), list, card(h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Add a site exception"), h("div", { class: "sub" }, "Starts with the opposite of the default - change it in the list")), input,
        h("button", { class: "btn", onclick: async () => { const v = input.value.trim(); if (!v) return; const other = c.options.find(o => o.value !== c.current); const r = await api("perm/set_site", { origin: v, feature: id, value: other.value }); if (!r.origin) return; toast("Exception added"); input.value = ""; loadSites(); } }, "Add"))));
    }
    return out;
  };
  R.performance = () => [h("h1", {}, "Performance"),
    card(switchRow("Memory Saver", "Frees memory from tabs you haven't used for a while. They reload when you return.", S.memory_saver, v => set("memory_saver", v)),
      selectRow("Deactivate inactive tabs after", "", [[5, "5 minutes"], [10, "10 minutes"], [15, "15 minutes"], [30, "30 minutes"], [60, "1 hour"]].map(([v, l]) => [String(v), l]), String(S.memory_saver_minutes), v => set("memory_saver_minutes", +v))),
    card(switchRow("Use graphics acceleration when available", "Needs a restart", S.hardware_acceleration, v => set("hardware_acceleration", v)),
      switchRow("Smooth scrolling", "", S.smooth_scrolling, v => set("smooth_scrolling", v)))];
  R.appearance = () => [h("h1", {}, "Appearance"),
    card(h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Theme"), h("div", { class: "sub" }, "System follows your operating system's dark mode")),
      h("div", { class: "segmented" }, [["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => h("button", { class: S.theme === v ? "on" : "", onclick: async e => { await set("theme", v); $$(".segmented button").forEach(b => b.classList.remove("on")); e.target.classList.add("on"); document.documentElement.dataset.theme = v; } }, l)))),
      h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Accent color")), h("div", { class: "chips" }, ACCENTS.map(c => h("div", { class: "swatch " + (S.accent === c ? "on" : ""), style: `background:${c}`, onclick: async e => { await set("accent", c); $$(".swatch").forEach(s => s.classList.remove("on")); e.target.classList.add("on"); document.documentElement.style.setProperty("--accent", c); } }))))),
    card(switchRow("Show bookmarks bar", "Ctrl+Shift+B", S.show_bookmarks_bar, v => set("show_bookmarks_bar", v)),
      switchRow("Show home button", "", S.show_home_button, v => set("show_home_button", v)),
      textRow("Home page", "Opened by the home button (Alt+Home)", "homepage", "null://newtab"),
      switchRow("Tab previews", "Show the full title and address when hovering a tab", S.tab_hover_cards, v => set("tab_hover_cards", v))),
    card(switchRow("Auto dark mode for web contents", "Forces a dark rendering on sites that don't support dark mode", S.web_dark_mode, v => set("web_dark_mode", v)))];
  R.search = () => {
    const ns = D.engine, engs = Object.values(D.engines);
    const status = h("span", { class: "badge " + (["running", "external"].includes(ns.state) ? "ok" : ns.state === "error" ? "err" : "") }, ns.state);
    const custom = h("div", { class: "card", style: "margin-bottom:14px" });
    function addEngine() {
      const n = h("input", { type: "text" }), k = h("input", { type: "text", placeholder: "@mysearch" }), u = h("input", { type: "text", placeholder: "https://example.com/search?q=%s" });
      const d = h("dialog", {}, h("h3", {}, "Add search engine"), h("label", {}, "Name"), n, h("label", {}, "Shortcut"), k, h("label", {}, "URL with %s"), u,
        h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => d.close() }, "Cancel"), h("button", { class: "btn primary", onclick: async () => { if (!n.value || !u.value.includes("%s")) return toast("Name and a URL containing %s are required"); await set("custom_engines", [...(S.custom_engines || []), { name: n.value, keyword: k.value, url: u.value }]); location.reload(); } }, "Save")));
      d.addEventListener("close", () => d.remove()); document.body.append(d); d.showModal();
    }
    (S.custom_engines || []).forEach((e, i) => custom.append(h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, e.name), h("div", { class: "sub ellipsis" }, e.url)), h("span", { class: "badge" }, e.keyword || ""), h("button", { class: "btn icon ghost", html: icon("trash", "sm"), onclick: async () => { const l = S.custom_engines.slice(); l.splice(i, 1); await set("custom_engines", l); location.reload(); } }))));
    custom.append(h("div", { class: "row" }, h("div", { class: "grow muted" }, "Add search engines with %s in place of the query"), h("button", { class: "btn", onclick: addEngine }, "Add")));
    return [h("h1", {}, "Search engine"),
      card(selectRow("Search engine used in the address bar", "Type @google, @null, @ddg, @bing or @brave followed by a query to pick one for a single search", engs.map(e => [e.id, e.name]), S.search_engine, v => set("search_engine", v)),
        switchRow("Search suggestions", "Send what you type to the search engine to get suggestions", S.search_suggestions, v => set("search_suggestions", v))),
      h("h2", {}, "Null Search (local search engine linked to this browser)"),
      card(h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Server status"), h("div", { class: "sub" }, ["unavailable", "error"].includes(ns.state) ? ns.detail : (ns.available ? `${ns.url} - ${(ns.stats && ns.stats.documents) || 0} pages indexed` : "Null Search Engine folder not found"))), status,
        h("button", { class: "btn", onclick: async () => { await api("engine/start"); toast("Starting…"); setTimeout(() => location.reload(), 2500); } }, "Start"),
        h("button", { class: "btn", onclick: async () => { await api("engine/stop"); setTimeout(() => location.reload(), 600); } }, "Stop")),
        switchRow("Start Null Search with the browser", "Launches the bundled FastAPI server in the background and stops it on exit", S.autostart_null_search, v => set("autostart_null_search", v)),
        h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Port"), h("div", { class: "sub" }, "Restart the server after changing")), h("input", { type: "number", value: S.null_search_port, min: 1024, max: 65535, style: "width:100px", onchange: e => set("null_search_port", +e.target.value) })),
        actionRow("Index my bookmarks in Null Search", `Crawls the ${D.meta.bookmark_count} bookmarked page(s) so you can find them from Null Search`, "Index now", async () => { const r = await api("engine/index_bookmarks"); toast(r.message); }),
        actionRow("Open Null Search", "", "Open", () => { location.href = ns.url; })),
      h("h2", {}, "Custom search engines"), custom];
  };
  R.default = () => [h("h1", {}, "Default browser"),
    card(actionRow("Make Null Browser your default browser", "Opens your system's default apps settings. Choose Null Browser for HTTP, HTTPS and HTML.", "Open system settings", () => api("app/set_default_browser")))];
  R.startup = () => {
    const urls = h("textarea", { rows: 4, style: "width:100%;margin:10px 0", placeholder: "https://example.com", onchange: e => set("startup_urls", e.target.value.split("\n").map(s => s.trim()).filter(Boolean)) }, (S.startup_urls || []).join("\n"));
    return [h("h1", {}, "On startup"),
      card([["newtab", "Open the New Tab page"], ["continue", "Continue where you left off"], ["urls", "Open specific pages"]].map(([v, l]) => h("label", { class: "row click" }, h("input", { type: "radio", name: "su", checked: S.startup_mode === v, style: "accent-color:var(--accent)", onchange: () => set("startup_mode", v) }), h("div", { class: "grow" }, l)))),
      card(h("div", { class: "row", style: "display:block" }, h("div", { class: "title" }, "Pages to open (one per line)"), urls))];
  };
  R.languages = () => [h("h1", {}, "Languages"),
    card(textRow("Preferred languages", "Sent to websites in the Accept-Language header, comma separated (e.g. en-US,hi,gu). Applies to new page loads.", "accept_languages", "en-US,en"),
      switchRow("Check spelling", "Needs Qt spellcheck dictionaries (.bdic) installed", S.spellcheck, v => set("spellcheck", v)))];
  R.downloads = () => [h("h1", {}, "Downloads"),
    card(h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Location"), h("div", { class: "sub" }, S.download_dir || D.meta.default_download_dir)), h("button", { class: "btn", onclick: async () => { const r = await api("app/pick_folder"); if (r.path) { await set("download_dir", r.path); location.reload(); } } }, "Change")),
      switchRow("Ask where to save each file", "", S.ask_download_location, v => set("ask_download_location", v)),
      switchRow("Warn before keeping dangerous files", "Executables, installers and scripts", S.warn_dangerous_downloads, v => set("warn_dangerous_downloads", v)),
      switchRow("Show the downloads panel when a download starts", "", S.open_downloads_panel, v => set("open_downloads_panel", v))),
    card(link("Automatic downloads", "Whether a site may download several files in a row", "null://settings/content/automatic_downloads"))];
  R.accessibility = () => {
    const sizes = [[12, "Small"], [14, "Medium-small"], [16, "Medium (recommended)"], [18, "Large"], [20, "Very large"], [24, "Huge"]];
    const zooms = [50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200, 250, 300];
    return [h("h1", {}, "Accessibility"),
      card(selectRow("Font size", "", sizes.map(([v, l]) => [String(v), l]), String(S.font_size), v => set("font_size", +v)),
        selectRow("Minimum font size", "Stops text from becoming unreadably small", [["0", "None"], ["9", "9"], ["12", "12"], ["14", "14"], ["16", "16"]], String(S.min_font_size), v => set("min_font_size", +v)),
        selectRow("Default page zoom", "Individual sites remember their own zoom", zooms.map(z => [String(z), z + "%"]), String(S.default_zoom), v => set("default_zoom", +v)))];
  };
  R.system = () => [h("h1", {}, "System"),
    card(switchRow("Show desktop notifications", "Download alerts and website notifications you allowed use your operating system's notification centre", S.desktop_notifications, v => set("desktop_notifications", v)),
      switchRow("Keep running in the system tray when closed", "Closing the last window hides Null Browser to the tray so downloads continue", S.background_running, v => set("background_running", v))),
    h("h2", {}, "Developer"),
    card(selectRow("DevTools dock position", "F12 / Ctrl+Shift+I toggles DevTools for the current tab", [["right", "Dock to right"], ["bottom", "Dock to bottom"], ["window", "Separate window"]], S.devtools_dock, v => set("devtools_dock", v)),
      h("div", { class: "row" }, h("div", { class: "grow" }, h("div", { class: "title" }, "Remote debugging port"), h("div", { class: "sub" }, "0 disables it. Lets Chrome DevTools / Playwright / Puppeteer attach on http://localhost:PORT. Needs a restart.")), h("input", { type: "number", value: S.remote_debugging_port, min: 0, max: 65535, style: "width:100px", onchange: e => set("remote_debugging_port", +e.target.value) })),
      link("Logs & errors", "Self-healing error handler output", "null://logs"), link("Version & build info", "", "null://version")),
    card(actionRow("Relaunch in safe mode", "Starts with ad blocking and the JavaScript API gate off - use if something is broken", "Relaunch", () => api("app/restart", { safe: true })),
      actionRow("Open data folder", D.meta.data_dir, "Open", () => api("app/open_data_dir")))];
  R.reset = () => [h("h1", {}, "Reset settings"),
    card(actionRow("Restore settings to their original defaults", "Theme, search engine, startup and privacy options return to defaults. Bookmarks and history are not removed.", "Reset settings", async () => { if (await confirmDialog("Reset settings?", "Your settings will return to their defaults.", "Reset", true)) { await api("settings/reset"); location.href = "null://settings/reset"; } }, "danger"),
      actionRow("Reset site permissions", "Remove all per-site allow/block decisions", "Reset", async () => { if (await confirmDialog("Reset site permissions?", "", "Reset", true)) { await api("perm/reset_all"); toast("Done"); } }, "danger"))];
  R.about = () => [h("h1", {}, "About Null Browser"),
    card(h("table", { class: "kv" }, Object.entries(D.meta.versions).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v))))),
    card(link("All internal pages", "null://about", "null://about"), link("Logs & errors", "", "null://logs"))];

  async function renderCurrent() {
    root.innerHTML = ""; root.append(banner);
    const parts = path.split("/").filter(Boolean); let els;
    if (!parts.length) els = R.you();
    else if (parts[0] === "content" && parts[1]) els = R.contentDetail(parts[1]);
    else if (R[parts[0]]) els = R[parts[0]]();
    else els = [h("h1", {}, "Settings"), h("p", { class: "muted" }, "That settings page doesn't exist."), h("a", { href: "null://settings" }, "Back to settings")];
    root.append(...els);
  }
  function onSearch(q) {
    if (!q) return renderCurrent();
    root.innerHTML = ""; root.append(banner);
    const t = q.toLowerCase(); let n = 0;
    for (const s of SECTIONS) {
      if (!s || s[0] === "content") continue;
      const holder = h("div"); holder.append(...R[s[0]]());
      const rows = $$(".card > .row", holder).filter(r => r.textContent.toLowerCase().includes(t));
      if (rows.length) { n += rows.length; root.append(h("h2", {}, s[1]), h("div", { class: "card", style: "margin-bottom:14px" }, rows)); }
    }
    const hits = D.catalog.filter(c => (c.label + c.desc).toLowerCase().includes(t));
    if (hits.length) { n += hits.length; root.append(h("h2", {}, "Site settings"), h("div", { class: "card", style: "margin-bottom:14px" }, hits.map(c => link(c.label, c.desc, "null://settings/content/" + c.id)))); }
    if (!n) root.append(h("div", { class: "empty" }, "No settings found for “" + q + "”"));
  }
  renderCurrent();
})();
