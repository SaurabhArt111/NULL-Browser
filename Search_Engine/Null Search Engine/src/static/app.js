/* Null Search - suggestions, theme toggle, small progressive enhancements. No inline scripts (CSP). */
"use strict";
(function () {
  const $ = (s, r = document) => r.querySelector(s);

  // Broken favicons / thumbnails simply disappear (the letter avatar underneath stays).
  document.addEventListener("error", e => { const t = e.target; if (t && t.tagName === "IMG" && t.hasAttribute("data-hide-on-error")) t.remove(); }, true);

  // Theme toggle (light / dark / follow system).
  const root = document.documentElement;
  document.querySelectorAll("[data-theme-toggle]").forEach(btn => btn.addEventListener("click", () => {
    const dark = root.getAttribute("data-theme") === "dark" || (!root.hasAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("ns-theme", next); } catch (e) {}
  }));

  document.querySelectorAll("form[data-autosubmit]").forEach(f => f.addEventListener("change", () => f.submit()));

  // Autocomplete.
  const input = $("[data-suggest]"), box = $("#sug");
  if (!input || !box) return;
  let items = [], sel = -1, seq = 0, timer = 0;
  const icon = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
  function close() { box.classList.remove("open"); box.textContent = ""; items = []; sel = -1; }
  function render() {
    box.textContent = "";
    items.forEach((s, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "option"); b.setAttribute("aria-selected", String(i === sel));
      b.innerHTML = icon; b.append(document.createTextNode(s));
      b.addEventListener("mousedown", e => { e.preventDefault(); go(s); });
      box.append(b);
    });
    box.classList.toggle("open", items.length > 0);
  }
  function go(s) { input.value = s; input.form.requestSubmit ? input.form.requestSubmit() : input.form.submit(); }
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) return close();
    timer = setTimeout(async () => {
      const my = ++seq;
      try {
        const r = await fetch("/api/suggest?q=" + encodeURIComponent(q));
        const d = await r.json();
        if (my === seq && document.activeElement === input) { items = (d[1] || []).slice(0, 8); sel = -1; render(); }
      } catch (e) { close(); }
    }, 120);
  });
  input.addEventListener("keydown", e => {
    if (!items.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (e.key === "ArrowDown") sel = sel + 1 >= items.length ? -1 : sel + 1; else sel = sel - 1 < -1 ? items.length - 1 : sel - 1;
      render(); if (sel >= 0) input.value = items[sel];
    } else if (e.key === "Escape") close();
  });
  input.addEventListener("blur", () => setTimeout(close, 100));
  document.addEventListener("keydown", e => {
    if (e.key === "/" && document.activeElement !== input && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); input.select(); }
  });
})();
