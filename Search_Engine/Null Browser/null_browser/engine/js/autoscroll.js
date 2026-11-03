/* Null Browser: Chrome-style middle-click auto-scroll, done inside the page.
 *
 * Why in the page: Qt WebEngine turns Chromium's "panning" cursors into the generic window-resize arrows, so the native
 * auto-scroll looked like a vertical resizer. Here the cursor is a CSS cursor (an SVG), the anchor is drawn by us, and
 * Chromium's own auto-scroll never starts (we swallow the middle mouse-down), so nothing depends on the platform.
 *
 * Behaviour (matches Chrome on Windows):
 *  - middle-click on a scrollable page (not on a link) drops the anchor; move the pointer to scroll, farther = faster
 *  - press / drag / release  -> scrolling stops on release
 *  - click and release without moving -> stays on until any click, key, wheel, Esc, blur or navigation
 *  - the cursor is a disc with a triangle per scrollable direction at rest, and one arrow pointing the scroll direction when moving
 */
(function () {
  "use strict";
  if (window.__nullAutoscroll) return;
  window.__nullAutoscroll = true;

  var DEAD = 12, HOLD_MS = 280, MAX_SPEED = 3600;
  var st = null;                 // {x, y, ax, el, t0, moved, sticky, raf, last, fx, fy, style, anchor}
  var cursorStyle = null, host = null, shadow = null;

  function svgCursor(axes, dir) {
    // 32x32 cursor. axes: "v" | "h" | "vh"; dir: null (resting anchor) or [dx, dy] unit vector
    var c = 16, s = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">';
    function tri(dx, dy, dist, hb, ht, fill, stroke) {
      var tx = c + dx * dist, ty = c + dy * dist, bx = c + dx * (dist - ht), by = c + dy * (dist - ht), nx = -dy, ny = dx;
      return '<path d="M' + tx.toFixed(2) + ' ' + ty.toFixed(2) + 'L' + (bx + nx * hb).toFixed(2) + ' ' + (by + ny * hb).toFixed(2) +
             'L' + (bx - nx * hb).toFixed(2) + ' ' + (by - ny * hb).toFixed(2) + 'Z" fill="' + fill + '"' + (stroke ? ' stroke="' + stroke + '" stroke-width="1.4" stroke-linejoin="round"' : '') + '/>';
    }
    if (!dir) {
      s += '<circle cx="16" cy="16" r="11" fill="#fff" stroke="#1d1d1f" stroke-opacity=".85" stroke-width="1"/>';
      s += '<circle cx="16" cy="16" r="2.4" fill="#1d1d1f"/>';
      var dirs = [];
      if (axes.indexOf("v") >= 0) dirs.push([0, -1], [0, 1]);
      if (axes.indexOf("h") >= 0) dirs.push([-1, 0], [1, 0]);
      dirs.forEach(function (d) { s += tri(d[0], d[1], 8.2, 3.4, 3.4, "#1d1d1f"); });
    } else {
      var dx = dir[0], dy = dir[1];
      s += '<circle cx="' + (c - dx * 4) + '" cy="' + (c - dy * 4) + '" r="3.2" fill="#1d1d1f" stroke="#fff" stroke-width="1.6"/>';
      s += tri(dx, dy, 8.2, 4.2, 4.8, "#1d1d1f", "#fff");
    }
    return s + "</svg>";
  }

  function setCursor(axes, dir) {
    if (!cursorStyle) {
      cursorStyle = document.createElement("style");
      cursorStyle.setAttribute("data-null-autoscroll", "");
      (document.head || document.documentElement).appendChild(cursorStyle);
    }
    var uri = "data:image/svg+xml;utf8," + encodeURIComponent(svgCursor(axes, dir));
    cursorStyle.textContent = "html,html *,html *:hover{cursor:url(\"" + uri + "\") 16 16,all-scroll !important}";
  }
  function clearCursor() { if (cursorStyle) { cursorStyle.remove(); cursorStyle = null; } }

  function drawAnchor(x, y) {
    // the cursor itself is the anchor graphic; this invisible shield just keeps hover effects / tooltips from firing under it
    host = document.createElement("div");
    host.setAttribute("data-null-autoscroll", "");
    host.style.cssText = "all:initial;position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:2147483647;background:transparent;pointer-events:auto;";
    (document.documentElement).appendChild(host);
  }
  function removeAnchor() { if (host) { host.remove(); host = null; } }

  function scrollableAxes(el) {
    var root = document.scrollingElement || document.documentElement;
    function can(e) {
      var cs = getComputedStyle(e), isRoot = (e === root || e === document.body || e === document.documentElement);
      var v = (isRoot || /(auto|scroll|overlay)/.test(cs.overflowY)) && e.scrollHeight > e.clientHeight + 1;
      var h = (isRoot || /(auto|scroll|overlay)/.test(cs.overflowX)) && e.scrollWidth > e.clientWidth + 1;
      if (isRoot && cs.overflowY === "hidden" && e !== root) v = false;
      return { v: v, h: h };
    }
    for (var e = el; e && e !== document.documentElement && e !== document.body; e = e.parentElement) {
      var a = can(e);
      if (a.v || a.h) return { el: e, v: a.v, h: a.h };
    }
    var r = can(root);
    return { el: root, v: r.v, h: r.h };
  }

  function overLink(el) {
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      if ((e.tagName === "A" && e.hasAttribute("href")) || e.tagName === "AREA") return true;
    }
    return false;
  }

  function speed(d) {
    var a = Math.abs(d) - DEAD;
    if (a <= 0) return 0;
    var v = Math.min(MAX_SPEED, Math.pow(a, 1.2) * 5.2);
    return d < 0 ? -v : v;
  }

  function dirOf(dx, dy, axes) {
    if (Math.hypot(dx, dy) <= DEAD) return null;
    if (axes === "v") return [0, dy > 0 ? 1 : -1];
    if (axes === "h") return [dx > 0 ? 1 : -1, 0];
    var o = Math.round(Math.atan2(dy, dx) / (Math.PI / 4));
    var ds = [[1, 0], [.7071, .7071], [0, 1], [-.7071, .7071], [-1, 0], [-.7071, -.7071], [0, -1], [.7071, -.7071]];
    return ds[((o % 8) + 8) % 8];
  }

  function tick(now) {
    if (!st) return;
    var dt = Math.min(64, now - st.last) / 1000;
    st.last = now;
    var dx = st.cx - st.x, dy = st.cy - st.y;
    var vx = st.ax.indexOf("h") >= 0 ? speed(dx) : 0, vy = st.ax.indexOf("v") >= 0 ? speed(dy) : 0;
    st.fx += vx * dt; st.fy += vy * dt;
    var ix = st.fx < 0 ? Math.ceil(st.fx) : Math.floor(st.fx), iy = st.fy < 0 ? Math.ceil(st.fy) : Math.floor(st.fy);
    if (ix || iy) {
      st.fx -= ix; st.fy -= iy;
      var el = st.el;
      if (el === document.scrollingElement || el === document.documentElement || el === document.body) window.scrollBy(ix, iy);
      else { el.scrollLeft += ix; el.scrollTop += iy; }
    }
    var d = dirOf(dx, dy, st.ax), key = d ? d.join(",") : "";
    if (key !== st.curDir) { st.curDir = key; setCursor(st.ax, d); }
    st.raf = requestAnimationFrame(tick);
  }

  function stop() {
    if (!st) return;
    cancelAnimationFrame(st.raf);
    st = null;
    clearCursor();
    removeAnchor();
    window.removeEventListener("mousemove", onMove, true);
  }

  function onMove(e) {
    if (!st) return;
    st.cx = e.clientX; st.cy = e.clientY;
    if (Math.hypot(e.clientX - st.x, e.clientY - st.y) > DEAD) st.moved = true;
  }

  function targetOf(e) {
    var t = e.target;
    return (t && t.nodeType === 1) ? t : (document.elementFromPoint(e.clientX, e.clientY) || document.documentElement);
  }

  function start(e) {
    var info = scrollableAxes(targetOf(e));
    var axes = (info.v ? "v" : "") + (info.h ? "h" : "");
    if (!axes) return false;
    st = { x: e.clientX, y: e.clientY, cx: e.clientX, cy: e.clientY, ax: axes, el: info.el, t0: performance.now(), moved: false,
           sticky: false, last: performance.now(), fx: 0, fy: 0, curDir: "" };
    drawAnchor(e.clientX, e.clientY);
    setCursor(axes, null);
    window.addEventListener("mousemove", onMove, true);
    st.raf = requestAnimationFrame(tick);
    return true;
  }

  function swallow(e) { e.preventDefault(); e.stopImmediatePropagation(); }

  window.addEventListener("mousedown", function (e) {
    if (st) {                                   // any button ends auto-scroll; that click is consumed (like Chrome)
      swallow(e);
      stop();
      return;
    }
    if (e.button !== 1 || e.defaultPrevented) return;
    var t = targetOf(e);
    if (overLink(t)) return;                    // middle-click on a link opens it in a new tab
    if (t.closest && t.closest("input,textarea,select,[contenteditable='true'],[contenteditable='']")) return;
    if (start(e)) swallow(e);
  }, true);

  window.addEventListener("mouseup", function (e) {
    if (!st) return;
    if (e.button === 1) {
      swallow(e);
      var held = performance.now() - st.t0;
      if (st.moved && held > HOLD_MS) stop();   // press-drag-release: stop on release
      else st.sticky = true;                    // quick click: stays on until the next click / key
    }
  }, true);
  window.addEventListener("auxclick", function (e) { if (st && e.button === 1) swallow(e); }, true);
  window.addEventListener("click", function (e) { if (st) { swallow(e); stop(); } }, true);
  window.addEventListener("contextmenu", function (e) { if (st) { swallow(e); stop(); } }, true);
  window.addEventListener("keydown", function () { stop(); }, true);
  window.addEventListener("wheel", function () { stop(); }, { capture: true, passive: true });
  window.addEventListener("blur", stop, true);
  window.addEventListener("pagehide", stop, true);
  document.addEventListener("visibilitychange", function () { if (document.hidden) stop(); });

  // test hook (does nothing unless the page asks): lets the self-test read the state without touching page globals
  Object.defineProperty(window, "__nullAutoscrollState", { configurable: true, get: function () { return st ? { ax: st.ax, sticky: st.sticky } : null; } });
})();
