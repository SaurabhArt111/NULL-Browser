"use strict";
/* New Tab page. Everything the user can change lives in settings.newtab and is edited live from the "Customize" drawer. */
(async function () {
  const d = await api("newtab/data");
  document.title = "New Tab";
  const css = h("link", { rel: "stylesheet", href: "/_/newtab.css" });
  document.head.append(css);
  await new Promise(r => { css.onload = r; css.onerror = r; setTimeout(r, 900); });

  const GRADIENTS = [
    ["aurora", "linear-gradient(135deg,#0f2027,#203a43 45%,#2c5364)", "dark"], ["sunset", "linear-gradient(135deg,#ff7e5f,#feb47b)", "light"],
    ["ocean", "linear-gradient(135deg,#2193b0,#6dd5ed)", "light"], ["forest", "linear-gradient(135deg,#134e5e,#71b280)", "dark"],
    ["violet", "linear-gradient(135deg,#41295a,#2f0743 60%,#6c5ce7)", "dark"], ["rose", "linear-gradient(135deg,#ee9ca7,#ffdde1)", "light"],
    ["ember", "linear-gradient(135deg,#232526,#414345 55%,#e96443)", "dark"], ["mint", "linear-gradient(135deg,#a8e6cf,#dcedc1)", "light"],
    ["midnight", "linear-gradient(160deg,#0f0c29,#302b63 55%,#24243e)", "dark"], ["sand", "linear-gradient(135deg,#f6d365,#fda085)", "light"],
  ];
  const COLORS = ["#14151c", "#1d1f29", "#2d3142", "#3a2a63", "#0b6e4f", "#1e6091", "#f6f7fb", "#ffffff", "#ffe8cc", "#e0f2fe"];
  const DEF = {
    bg: "default", color: "#1d1f29", gradient: "aurora", dim: 25, blur: 0, bg_rev: 0,
    logo: true, logo_text: "Null", search: true, search_style: "pill", engine_picker: true, status: true,
    shortcuts_mode: "auto", shortcuts: [], tile: "medium", clock: false, h24: false, greeting: false, position: "center", links: true,
  };
  let N = Object.assign({}, DEF, d.newtab || {});
  let hasBg = !!d.has_bg;
  const persist = debounce(() => api("settings/set", { key: "newtab", value: N }), 300);
  const change = (patch, panel = true) => { Object.assign(N, patch); persist(); paint(); if (panel) drawPanel(); };

  const eng = (() => {
    const sel = h("select", { onchange: async e => { await api("settings/set", { key: "search_engine", value: e.target.value }); input.focus(); label(); } },
      Object.values(d.engines).map(e => h("option", { value: e.id, selected: e.id === d.engine }, e.name)));
    return sel;
  })();
  const input = h("input", { type: "text", placeholder: "Search or type a URL", autocomplete: "off", spellcheck: "false", "aria-label": "Search or type a URL" });
  const label = () => { const e = d.engines[eng.value]; input.placeholder = `Search ${e.name} or type a URL`; };
  async function go(q) { if (!q) return; const r = await api("search/resolve", { q }); location.href = r.url; }
  input.addEventListener("keydown", e => { if (e.key === "Enter") go(input.value.trim()); });
  label();

  // ---------------------------------------------------------------------------------------------- page
  document.body.innerHTML = "";
  document.body.className = "nt";
  const bgEl = h("div", { class: "nt-bg" }), dimEl = h("div", { class: "nt-dim" });
  const page = h("div", { style: "width:100%;display:flex;flex-direction:column;align-items:center" });
  const panel = h("aside", { class: "nt-panel", "aria-label": "Customize this page" });
  const customBtn = h("button", { class: "nt-custom", title: "Customize", "data-hint": "Change the background, shortcuts and layout of this page", onclick: () => togglePanel(true) }, h("span", { html: icon("sliders", "sm") }), "Customize");
  document.body.append(bgEl, dimEl, page, customBtn, panel);
  let clockTimer = 0;

  function tone() {
    if (N.bg === "color") return lum(N.color) < .5 ? "dark" : "light";
    if (N.bg === "gradient") return (GRADIENTS.find(g => g[0] === N.gradient) || GRADIENTS[0])[2];
    if (N.bg === "image" && hasBg) return imageTone;
    return "";
  }
  function lum(hex) { const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || ""); if (!m) return .1; const [r, g, b] = [1, 2, 3].map(i => parseInt(m[i], 16) / 255); return .299 * r + .587 * g + .114 * b; }
  let imageTone = "dark";
  function sampleImage() {
    const img = new Image(); img.onload = () => {
      try { const c = document.createElement("canvas"); c.width = c.height = 16; const x = c.getContext("2d"); x.drawImage(img, 0, 0, 16, 16);
        const px = x.getImageData(0, 0, 16, 16).data; let s = 0; for (let i = 0; i < px.length; i += 4) s += (.299 * px[i] + .587 * px[i + 1] + .114 * px[i + 2]) / 255; imageTone = (s / 256) * (1 - N.dim / 100) < .55 ? "dark" : "light"; paint(true); } catch (e) { imageTone = "dark"; } };
    img.src = "/_/bg?v=" + N.bg_rev;
  }

  function paint(skipSample) {
    const t = tone();
    document.body.classList.remove("tone-dark", "tone-light"); if (t) document.body.classList.add("tone-" + t);
    bgEl.style.cssText = ""; dimEl.style.cssText = "";
    if (N.bg === "color") bgEl.style.background = N.color;
    else if (N.bg === "gradient") bgEl.style.background = (GRADIENTS.find(g => g[0] === N.gradient) || GRADIENTS[0])[1];
    else if (N.bg === "image" && hasBg) {
      bgEl.style.backgroundImage = `url(/_/bg?v=${N.bg_rev})`;
      if (N.blur) bgEl.style.cssText += `filter:blur(${N.blur}px);transform:scale(1.06);`;
      dimEl.style.background = `rgba(0,0,0,${N.dim / 100})`;
      if (!skipSample && !paint.sampled) { paint.sampled = true; sampleImage(); }
    }
    renderPage();
  }

  function greeting() { const h24 = new Date().getHours(); return h24 < 5 ? "Good night" : h24 < 12 ? "Good morning" : h24 < 18 ? "Good afternoon" : "Good evening"; }

  function renderPage() {
    clearInterval(clockTimer);
    page.innerHTML = "";
    const top = N.links ? h("div", { class: "nt-top" },
      [["history", "history", "Pages you have visited"], ["bookmarks", "bookmark", "Pages you saved"], ["downloads", "download", "Files you downloaded"], ["settings", "settings", "Privacy, appearance, search engine and more"]].map(([p, ic, hint]) =>
        h("a", { href: "null://" + p, title: p[0].toUpperCase() + p.slice(1), "data-hint": hint, "aria-label": p, class: "btn icon ghost", html: icon(ic) }))) : "";
    const main = h("div", { class: "nt-main" + (N.position === "upper" ? " upper" : "") });
    if (N.clock) {
      const c = h("div", { class: "nt-clock" }); const tick = () => { c.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: !N.h24 }); };
      tick(); clockTimer = setInterval(tick, 1000); main.append(c);
    }
    if (N.greeting) main.append(h("div", { class: "nt-greet" }, greeting()));
    if (d.private) {
      main.append(h("div", { class: "nt-private" }, h("div", { html: icon("eye").replace('class="i ', 'style="width:56px;height:56px" class="i ') }),
        h("h1", {}, "You're InPrivate"),
        h("p", {}, "Null Browser won't save your history, cookies or site data from this window. Downloads and bookmarks you create are kept. Your activity may still be visible to the sites you visit, your employer or school, and your internet provider.")));
    } else if (N.logo) {
      main.append(h("div", { class: "nt-brand" }, h("div", { class: "logo" }, "N"), h("div", { class: "word" }, N.logo_text || "Null")));
    }
    if (N.search) {
      const box = h("div", { class: "nt-search " + N.search_style }, h("span", { html: icon("search") }), input);
      main.append(box);
      if (N.engine_picker || N.status) {
        const row = h("div", { class: "nt-engine" });
        if (N.engine_picker) row.append("Search with", eng);
        if (N.status) {
          const ns = d.null_search, st = h("span", { class: "badge" });
          st.textContent = { running: "Null Search online", external: "Null Search online", starting: "Null Search starting…", stopped: "Null Search offline", unavailable: "Null Search unavailable", error: "Null Search error" }[ns.state] || ns.state;
          st.className = "badge " + (["running", "external"].includes(ns.state) ? "ok" : ns.state === "starting" ? "warn" : "");
          st.title = "Null Search"; st.setAttribute("data-hint", "Your local search engine. The browser starts it for you; Settings > Search engine controls it.");
          row.append(st);
        }
        main.append(row);
      }
    }
    if (!d.private) main.append(tiles());
    page.append(top, main);
    if (!document.activeElement || document.activeElement === document.body) { if (N.search) input.focus(); }
  }

  // ---------------------------------------------------------------------------------------------- shortcuts
  function hostOf(u) { try { return new URL(u).host; } catch (e) { return ""; } }
  function autoTiles() {
    const out = [], seen = new Set();
    const src = N.shortcuts_mode === "most_visited" ? d.top : N.shortcuts_mode === "bookmarks" ? d.bookmarks : [...d.bookmarks, ...d.top];
    src.forEach(t => { const host = hostOf(t.url); if (!host || seen.has(host) || out.length >= 10) return; seen.add(host); out.push({ title: t.title, url: t.url }); });
    return out;
  }
  function tiles() {
    const wrap = h("div", { class: "nt-tiles" });
    const mode = N.shortcuts_mode;
    if (mode === "hidden") return wrap;
    const custom = mode === "custom";
    const list = custom ? N.shortcuts : autoTiles();
    list.forEach((t, i) => wrap.append(tile(t, i, custom)));
    if (custom && N.shortcuts.length < 14) {
      wrap.append(h("a", { class: "tile add " + N.tile, href: "#", title: "Add shortcut", "data-hint": "Pin a website to this page", onclick: e => { e.preventDefault(); shortcutDialog(); } },
        h("div", { class: "ico", html: icon("plus") }), h("div", { class: "lbl" }, "Add shortcut")));
    }
    if (!list.length && !custom) wrap.append(h("div", { class: "muted", style: "color:var(--nt-muted);font-size:13px" }, "Sites you visit and bookmark will show up here."));
    return wrap;
  }
  function tile(t, i, editable) {
    const host = hostOf(t.url);
    const name = (t.title || host || t.url).slice(0, 26);
    const img = favImg(t.url); img.src = "/_/favicon?strict=1&u=" + encodeURIComponent(t.url);
    const a = h("a", { href: t.url, class: "tile " + N.tile, title: t.title || host, "data-hint": host || t.url },
      h("div", { class: "ico" }, (name[0] || "?").toUpperCase(), img), h("div", { class: "lbl ellipsis" }, name));
    if (editable) {
      a.append(h("button", { class: "more", title: "Edit shortcut", "data-hint": "Rename, change the address or remove it", html: icon("edit", "sm"), onclick: e => { e.preventDefault(); e.stopPropagation(); shortcutDialog(i); } }));
      a.setAttribute("draggable", "true");
      a.addEventListener("dragstart", e => { e.dataTransfer.setData("text/x-null-tile", String(i)); e.dataTransfer.effectAllowed = "move"; a.classList.add("dragging"); });
      a.addEventListener("dragend", () => a.classList.remove("dragging"));
      a.addEventListener("dragover", e => { if ([...e.dataTransfer.types].includes("text/x-null-tile")) { e.preventDefault(); a.classList.add("over"); } });
      a.addEventListener("dragleave", () => a.classList.remove("over"));
      a.addEventListener("drop", e => {
        e.preventDefault(); a.classList.remove("over");
        const from = parseInt(e.dataTransfer.getData("text/x-null-tile"), 10); if (isNaN(from) || from === i) return;
        const l = N.shortcuts.slice(); const [m] = l.splice(from, 1); l.splice(i, 0, m); change({ shortcuts: l });
      });
    }
    return a;
  }
  function normUrl(u) {
    u = (u || "").trim(); if (!u) return "";
    if (!/^[a-z][a-z0-9+.-]*:/i.test(u)) u = "https://" + u;
    try { const x = new URL(u); return ["http:", "https:"].includes(x.protocol) ? x.href : ""; } catch (e) { return ""; }
  }
  function shortcutDialog(index) {
    const cur = index != null ? N.shortcuts[index] : { title: "", url: "" };
    const name = h("input", { type: "text", value: cur.title, placeholder: "Name (optional)" });
    const url = h("input", { type: "text", value: cur.url, placeholder: "https://example.com" });
    const err = h("div", { style: "color:var(--danger);font-size:12px;min-height:16px;margin-top:6px" });
    const save = () => {
      const u = normUrl(url.value); if (!u) { err.textContent = "Enter a valid web address (http or https)."; url.focus(); return; }
      const l = N.shortcuts.slice(); const item = { title: name.value.trim(), url: u };
      if (index != null) l[index] = item; else l.push(item);
      dlg.close(); change({ shortcuts: l });
    };
    const dlg = h("dialog", {}, h("h3", {}, index != null ? "Edit shortcut" : "Add shortcut"), h("label", {}, "Name"), name, h("label", {}, "URL"), url, err,
      h("div", { class: "actions" },
        index != null ? h("button", { class: "btn danger", title: "Remove shortcut", onclick: () => { const l = N.shortcuts.slice(); l.splice(index, 1); dlg.close(); change({ shortcuts: l }); } }, "Remove") : "",
        h("span", { style: "flex:1" }),
        h("button", { class: "btn", onclick: () => dlg.close() }, "Cancel"), h("button", { class: "btn primary", onclick: save }, "Done")));
    dlg.addEventListener("close", () => dlg.remove());
    dlg.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); save(); } });
    document.body.append(dlg); dlg.showModal(); (index != null ? name : url).focus();
  }

  // ---------------------------------------------------------------------------------------------- customise drawer
  function seg(options, value, onpick) {
    return h("div", { class: "seg" }, options.map(([v, l, hint]) => h("button", { class: v === value ? "on" : "", title: l, "data-hint": hint || "", onclick: () => onpick(v) }, l)));
  }
  function toggle(label, key, hint) {
    return h("div", { class: "opt" }, h("div", { class: "grow", title: label, "data-hint": hint || "" }, label),
      h("label", { class: "switch" }, h("input", { type: "checkbox", checked: !!N[key], onchange: e => change({ [key]: e.target.checked }) }), h("span")));
  }
  function slider(label, key, min, max, unit) {
    const v = h("span", { class: "muted", style: "width:42px;text-align:right" }, N[key] + unit);
    return h("div", { class: "opt" }, h("div", { class: "grow" }, label),
      h("input", { type: "range", min, max, value: N[key], oninput: e => { v.textContent = e.target.value + unit; change({ [key]: +e.target.value }, false); } }), v);
  }
  async function uploadBackground(file) {
    if (!file) return;
    if (!/^image\//.test(file.type)) { toast("Choose an image file"); return; }
    try {
      const url = URL.createObjectURL(file);
      const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("bad image")); i.src = url; });
      const k = Math.min(1, 2560 / Math.max(img.naturalWidth, img.naturalHeight));
      const c = document.createElement("canvas"); c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      await api("newtab/set_bg", { data: c.toDataURL("image/jpeg", .88) });
      hasBg = true; paint.sampled = false; change({ bg: "image", bg_rev: Date.now() });
      toast("Background updated", 1400);
    } catch (e) { if (!String(e.message).includes("Browser")) toast("That image couldn't be used"); }
  }
  function drawPanel() {
    const keep = panel.querySelector(".body"), top = keep ? keep.scrollTop : 0;
    panel.innerHTML = "";
    const file = h("input", { type: "file", accept: "image/*", style: "display:none", onchange: e => { uploadBackground(e.target.files[0]); e.target.value = ""; } });
    const bgControls = [];
    if (N.bg === "color") bgControls.push(
      h("div", { class: "chips", style: "margin:8px 0" }, COLORS.map(c => h("button", { class: "swatch" + (c.toLowerCase() === N.color.toLowerCase() ? " on" : ""), style: `background:${c}`, title: c, "aria-label": c, onclick: () => change({ color: c }) }))),
      h("div", { class: "opt" }, h("div", { class: "grow" }, "Custom colour"), h("input", { type: "color", value: N.color, oninput: e => change({ color: e.target.value }, false), onchange: () => drawPanel() })));
    if (N.bg === "gradient") bgControls.push(h("div", { class: "grad", style: "margin:8px 0" }, GRADIENTS.map(([id, css]) => h("button", { class: id === N.gradient ? "on" : "", style: `background:${css}`, title: id[0].toUpperCase() + id.slice(1), "aria-label": id, onclick: () => change({ gradient: id }) }))));
    if (N.bg === "image") bgControls.push(
      h("div", { class: "opt" }, h("button", { class: "btn", title: "Upload an image", "data-hint": "JPG, PNG, WebP or GIF from your computer. It is stored only on this PC.", onclick: () => file.click() }, h("span", { html: icon("upload", "sm") }), hasBg ? "Choose another image" : "Upload image"),
        hasBg ? h("button", { class: "btn ghost", title: "Remove image", onclick: async () => { await api("newtab/clear_bg"); hasBg = false; paint.sampled = false; change({ bg: "default" }); } }, "Remove") : ""),
      hasBg ? [slider("Darken", "dim", 0, 80, "%"), slider("Blur", "blur", 0, 20, "px")] : h("div", { class: "sub muted" }, "Pick a photo to use as your background."));
    const sc = [];
    if (N.shortcuts_mode === "custom") {
      N.shortcuts.forEach((s, i) => sc.push(h("div", { class: "sc" }, h("div", { class: "grow" }, h("div", { class: "ellipsis" }, s.title || hostOf(s.url)), h("div", { class: "u ellipsis" }, s.url)),
        h("button", { class: "btn icon ghost", title: "Move up", disabled: i === 0, html: icon("arrow_up", "sm"), onclick: () => { const l = N.shortcuts.slice(); [l[i - 1], l[i]] = [l[i], l[i - 1]]; change({ shortcuts: l }); } }),
        h("button", { class: "btn icon ghost", title: "Move down", disabled: i === N.shortcuts.length - 1, html: icon("arrow_down", "sm"), onclick: () => { const l = N.shortcuts.slice(); [l[i + 1], l[i]] = [l[i], l[i + 1]]; change({ shortcuts: l }); } }),
        h("button", { class: "btn icon ghost", title: "Edit shortcut", html: icon("edit", "sm"), onclick: () => shortcutDialog(i) }),
        h("button", { class: "btn icon ghost", title: "Remove shortcut", html: icon("trash", "sm"), onclick: () => { const l = N.shortcuts.slice(); l.splice(i, 1); change({ shortcuts: l }); } }))));
      sc.push(h("div", { class: "opt" }, h("button", { class: "btn", disabled: N.shortcuts.length >= 14, onclick: () => shortcutDialog() }, h("span", { html: icon("plus", "sm") }), "Add shortcut"),
        h("span", { class: "sub muted" }, `${N.shortcuts.length}/14`)));
    }
    panel.append(
      h("header", {}, h("h2", {}, "Customize this page"), h("button", { class: "btn icon ghost", title: "Close", "aria-label": "Close", html: icon("x"), onclick: () => togglePanel(false) })),
      h("div", { class: "body" }, file,
        h("h3", {}, "Background"),
        seg([["default", "Default", "Follow the browser theme"], ["color", "Colour", "A solid colour"], ["gradient", "Gradient", "A colourful gradient"], ["image", "Image", "Your own photo"]], N.bg, v => { paint.sampled = false; change({ bg: v }); }),
        bgControls,
        h("h3", {}, "Shortcuts"),
        seg([["auto", "Auto", "Bookmarks bar plus most visited sites"], ["custom", "My shortcuts", "Only the sites you add"], ["most_visited", "Most visited", "Sites you open the most"], ["bookmarks", "Bookmarks", "Your bookmarks bar"], ["hidden", "Hidden", "Show no shortcuts"]], N.shortcuts_mode, v => change({ shortcuts_mode: v })),
        h("div", { style: "height:8px" }),
        sc,
        h("div", { class: "opt" }, h("div", { class: "grow" }, "Shortcut size"), seg([["small", "S"], ["medium", "M"], ["large", "L"]], N.tile, v => change({ tile: v }))),
        h("h3", {}, "Layout"),
        toggle("Show logo", "logo", "The Null mark and name above the search box"),
        N.logo ? h("div", { class: "opt" }, h("div", { class: "grow" }, "Logo text"), h("input", { type: "text", value: N.logo_text, maxlength: 24, style: "width:150px", oninput: e => change({ logo_text: e.target.value }, false) })) : "",
        toggle("Show search box", "search", "Search or type an address right on the page"),
        N.search ? [h("div", { class: "opt" }, h("div", { class: "grow" }, "Search style"), seg([["pill", "Pill"], ["square", "Square"], ["glass", "Glass"], ["minimal", "Line"]], N.search_style, v => change({ search_style: v }))),
          toggle("Show search engine picker", "engine_picker", "Choose which engine the box uses"), toggle("Show Null Search status", "status", "Whether your local search engine is running")] : "",
        toggle("Show clock", "clock"), N.clock ? toggle("24-hour clock", "h24") : "", toggle("Show greeting", "greeting"),
        toggle("Show quick links", "links", "History, Bookmarks, Downloads and Settings icons at the top right"),
        h("div", { class: "opt" }, h("div", { class: "grow" }, "Content position"), seg([["center", "Centered"], ["upper", "Higher"]], N.position, v => change({ position: v }))),
        h("button", { class: "btn danger reset", title: "Reset this page", "data-hint": "Remove every customisation and your uploaded background", onclick: async () => {
          if (!await confirmDialog("Reset New Tab page?", "Your background, shortcuts and layout choices will be removed.", "Reset", true)) return;
          await api("newtab/clear_bg").catch(() => {}); hasBg = false; paint.sampled = false; N = Object.assign({}, DEF); persist(); paint(); drawPanel(); } }, "Reset to default")));
    panel.querySelector(".body").scrollTop = top;
  }
  function togglePanel(open) { if (open) drawPanel(); panel.classList.toggle("open", open); customBtn.style.visibility = open ? "hidden" : ""; }
  document.addEventListener("keydown", e => { if (e.key === "Escape" && panel.classList.contains("open")) togglePanel(false); });
  document.addEventListener("mousedown", e => { if (panel.classList.contains("open") && !panel.contains(e.target) && !e.target.closest("dialog") && !customBtn.contains(e.target)) togglePanel(false); });

  paint();
  if (location.hash === "#customize") togglePanel(true);
})();
