/* Null Browser: H.264 / AAC playback shim.
 *
 * Runs in the page's own world at document start, ONLY when this engine cannot decode H.264 (checked below) and the browser has
 * ffmpeg. Players that use Media Source Extensions (X, Reddit, Instagram, Facebook, Twitch, ...) are told that avc1 / mp4a are
 * supported; the SourceBuffer they get is a stand-in that sends every fragmented-MP4 piece the page appends to the browser
 * (QWebChannel, so the page's Content-Security-Policy is not involved), gets WebM (VP9 + Opus) back and feeds that to a real
 * SourceBuffer. Plain <video src="...mp4"> files are handled by the same bridge (see the bottom of this file).
 * Everything else about the page is left alone. If anything here cannot start, the page behaves exactly as without it.
 */
(function () {
  "use strict";
  if (window.__nullVideo || !window.MediaSource || !window.qt || !qt.webChannelTransport) return;
  var MS = window.MediaSource, NATIVE_IS = MS.isTypeSupported.bind(MS);
  try { if (NATIVE_IS('video/mp4; codecs="avc1.42E01E"') && NATIVE_IS('audio/mp4; codecs="mp4a.40.2"')) return; } catch (e) { return; }
  window.__nullVideo = true;
  var LOG = false;
  function log() { if (LOG) try { console.debug.apply(console, ["[null-video]"].concat([].slice.call(arguments))); } catch (e) {} }

  /* ------------------------------------------------------------------ bridge */
  var bridge = null, waiting = [], pend = new Map(), progs = new Map(), nextId = 1;
  new QWebChannel(qt.webChannelTransport, function (ch) {
    bridge = ch.objects.nullVideo;
    bridge.done.connect(function (id, ok, payload) {
      var p = pend.get(id); if (!p) return; pend.delete(id); p(ok, payload);
    });
    bridge.progress.connect(function (id, kind, payload) { var p = progs.get(id); if (p) p(kind, payload); });
    waiting.splice(0).forEach(function (f) { f(); });
  });
  function whenReady(f) { if (bridge) f(); else waiting.push(f); }

  function b64(u8) {
    var s = "", n = 0x8000;
    for (var i = 0; i < u8.length; i += n) s += String.fromCharCode.apply(null, u8.subarray(i, i + n));
    return btoa(s);
  }
  function unb64(s) {
    var bin = atob(s), n = bin.length, out = new Uint8Array(n);
    for (var i = 0; i < n; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  /* ------------------------------------------------------------------ MP4 helpers */
  function u32(b, o) { return ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0; }
  function t4(b, o) { return String.fromCharCode(b[o], b[o + 1], b[o + 2], b[o + 3]); }
  function boxAt(b, o, end) {            // -> {type, size, head} or null if the header is incomplete; size -1 = unknown
    if (o + 8 > end) return null;
    var s = u32(b, o), head = 8;
    if (s === 1) { if (o + 16 > end) return null; s = u32(b, o + 8) * 4294967296 + u32(b, o + 12); head = 16; }
    else if (s === 0) s = -1;
    return { type: t4(b, o + 4), size: s, head: head };
  }
  function children(b, o, end) {
    var out = [];
    while (o + 8 <= end) {
      var bx = boxAt(b, o, end); if (!bx || bx.size < 8) break;
      out.push({ type: bx.type, start: o, body: o + bx.head, end: Math.min(end, o + bx.size) }); o += bx.size;
    }
    return out;
  }
  function child(b, box, type) { var c = children(b, box.body, box.end); for (var i = 0; i < c.length; i++) if (c[i].type === type) return c[i]; return null; }
  function concat(list) {
    var n = 0, i; for (i = 0; i < list.length; i++) n += list[i].length;
    var out = new Uint8Array(n), o = 0; for (i = 0; i < list.length; i++) { out.set(list[i], o); o += list[i].length; }
    return out;
  }
  function timescales(init) {            // track id -> timescale, from the init segment's moov
    var map = {}, top = children(init, 0, init.length);
    for (var i = 0; i < top.length; i++) if (top[i].type === "moov") {
      children(init, top[i].body, top[i].end).forEach(function (trak) {
        if (trak.type !== "trak") return;
        var tkhd = child(init, trak, "tkhd"), mdia = child(init, trak, "mdia"), mdhd = mdia && child(init, mdia, "mdhd");
        if (!tkhd || !mdhd) return;
        var id = init[tkhd.body] === 1 ? u32(init, tkhd.body + 20) : u32(init, tkhd.body + 12);
        map[id] = init[mdhd.body] === 1 ? u32(init, mdhd.body + 20) : u32(init, mdhd.body + 12);
      });
    }
    return map;
  }
  function fragSeconds(init, frag, scales) {   // playing time of the first track fragment in `frag` (0 when unknown)
    try {
      var top = children(frag, 0, frag.length);
      for (var i = 0; i < top.length; i++) if (top[i].type === "moof") {
        var traf = child(frag, top[i], "traf"); if (!traf) continue;
        var tfhd = child(frag, traf, "tfhd"), trun = child(frag, traf, "trun"); if (!tfhd || !trun) continue;
        var tf = u32(frag, tfhd.body) & 0xffffff, id = u32(frag, tfhd.body + 4), o = tfhd.body + 8, defDur = 0;
        if (tf & 1) o += 8; if (tf & 2) o += 4; if (tf & 8) defDur = u32(frag, o);
        var rf = u32(frag, trun.body) & 0xffffff, count = u32(frag, trun.body + 4), p = trun.body + 8, total = 0;
        if (rf & 1) p += 4; if (rf & 4) p += 4;
        var step = ((rf & 0x100) ? 4 : 0) + ((rf & 0x200) ? 4 : 0) + ((rf & 0x400) ? 4 : 0) + ((rf & 0x800) ? 4 : 0);
        if (rf & 0x100) { for (var k = 0; k < count; k++) total += u32(frag, p + k * step); } else total = defDur * count;
        return scales[id] ? total / scales[id] : 0;
      }
    } catch (e) {}
    return 0;
  }

  /* ------------------------------------------------------------------ which types we take over */
  var RX = /^\s*(video|audio)\/(mp4|x-m4v|x-m4a|quicktime|3gpp)\s*;\s*codecs\s*=\s*"?([^";]*)"?/i;
  var VID = /^(avc[1-4]|hvc1|hev1|dvh[1e]|mp4v)/i, AUD = /^(mp4a\.(40\.\d+|69|6b)|ac-3|ec-3|mp3)/i, OK_NATIVE = /^(vp0?[89]|av01|opus|flac|vorbis)/i;
  function plan(type) {                  // -> {video, audio, out} when we have to convert this type, else null
    try {
      if (NATIVE_IS(type)) return null;
      var m = RX.exec(type); if (!m) return null;
      var cs = m[3].split(",").map(function (s) { return s.trim(); }).filter(Boolean), v = false, a = false;
      if (!cs.length) return null;
      for (var i = 0; i < cs.length; i++) {
        if (VID.test(cs[i])) v = true; else if (AUD.test(cs[i])) a = true; else if (!OK_NATIVE.test(cs[i])) return null;
      }
      if (!v && !a) return null;
      return { video: v, audio: a, outV: v ? 'video/webm; codecs="vp9"' : "", outA: a ? 'audio/webm; codecs="opus"' : "" };
    } catch (e) { return null; }
  }

  /* ------------------------------------------------------------------ the stand-in SourceBuffer */
  var proxies = new WeakMap(), reals = new WeakMap(), proxiesSeen = false;

  /* A page that declared one muxed type (avc1 + mp4a) gets one stand-in that owns two real buffers: Chromium's WebM parser is
     strict about the order of blocks of different tracks inside one converted piece, separate buffers avoid the problem. */
  class ProxySB extends EventTarget { constructor(ms, rsbs, pl, type) {
    super();
    var self = this;
    Object.defineProperty(this, "_s", { value: { ms: ms, rsbs: rsbs, rsb: rsbs[0], plan: pl, type: type, u: false, left: 0, done: null, gen: 0,
      ftyp: null, init: null, acc: new Uint8Array(0), queue: [], scales: {}, handlers: {} } });
    reals.set(this, rsbs);
    rsbs.forEach(function (r) { proxies.set(r, self); });
    rsbs.forEach(function (rsb, idx) {
      ["updatestart", "update", "updateend", "error", "abort"].forEach(function (ev) {
        rsb.addEventListener(ev, function () {
          var s = self._s;
          if (s.left > 0) {                                 // our own append into a real buffer
            if (ev === "updateend" && --s.left === 0) { var w = s.done; s.done = null; w(); }
            else if (ev === "error") log("real SourceBuffer error");
            return;
          }
          if (idx === 0) self.dispatchEvent(new Event(ev));
        });
      });
    });
  } }
  ["buffered", "audioTracks", "videoTracks", "textTracks"].forEach(function (k) {
    Object.defineProperty(ProxySB.prototype, k, { get: function () { return this._s.rsb[k]; }, enumerable: true, configurable: true });
  });
  ["timestampOffset", "appendWindowStart", "appendWindowEnd", "mode"].forEach(function (k) {
    Object.defineProperty(ProxySB.prototype, k, {
      get: function () { return this._s.rsb[k]; }, set: function (v) { this._s.rsbs.forEach(function (r) { r[k] = v; }); }, enumerable: true, configurable: true });
  });
  Object.defineProperty(ProxySB.prototype, "updating", { get: function () { var s = this._s; return s.u || s.rsbs.some(function (r) { return r.updating; }); }, enumerable: true, configurable: true });
  ["onupdatestart", "onupdate", "onupdateend", "onerror", "onabort"].forEach(function (k) {
    var ev = k.slice(2);
    Object.defineProperty(ProxySB.prototype, k, {
      get: function () { return this._s.handlers[k] || null; },
      set: function (f) {
        var s = this._s; if (s.handlers[k]) this.removeEventListener(ev, s.handlers[k]);
        s.handlers[k] = typeof f === "function" ? f : null; if (s.handlers[k]) this.addEventListener(ev, s.handlers[k]);
      }, enumerable: true, configurable: true });
  });
  function later(self, evs) { setTimeout(function () { evs.forEach(function (e) { self.dispatchEvent(new Event(e)); }); }, 0); }

  ProxySB.prototype.appendBuffer = function (data) {
    var s = this._s;
    if (this.updating) throw new DOMException("The SourceBuffer is still processing an update.", "InvalidStateError");
    var u8 = ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : new Uint8Array(data);
    s.u = true; s.queue.push(new Uint8Array(u8));         // copy: the page may reuse its buffer straight away
    var self = this, gen = s.gen;
    setTimeout(function () { if (gen === s.gen) { self.dispatchEvent(new Event("updatestart")); self._pump(gen); } }, 0);
  };
  ProxySB.prototype._done = function (gen) {
    var s = this._s; if (gen !== s.gen) return;
    s.u = false; this.dispatchEvent(new Event("update")); this.dispatchEvent(new Event("updateend"));
  };
  ProxySB.prototype._pump = function (gen) {
    var s = this._s, self = this;
    if (gen !== s.gen) return;
    var chunk = s.queue.shift(); if (!chunk) return self._done(gen);
    var buf = concat([s.acc, chunk]), off = 0, frags = [];
    for (;;) {                                              // take every complete top-level box; keep an incomplete tail
      var bx = boxAt(buf, off, buf.length); if (!bx) break;
      if (bx.size < 0) { off = buf.length; break; }          // open-ended box: not valid in a fragmented stream, ignore it
      if (off + bx.size > buf.length) break;
      var box = buf.subarray(off, off + bx.size);
      if (bx.type === "ftyp") { s.ftyp = box; }
      else if (bx.type === "moov") {
        s.init = s.ftyp ? concat([s.ftyp, box]) : box.slice(); s.scales = timescales(s.init);
      } else if (bx.type === "moof") {
        var nx = boxAt(buf, off + bx.size, buf.length);
        if (nx && nx.type === "mdat" && nx.size > 0) {
          if (off + bx.size + nx.size > buf.length) break;   // mdat not complete yet
          frags.push(buf.subarray(off, off + bx.size + nx.size)); off += bx.size + nx.size; continue;
        }
        if (!nx) break;                                      // wait for the box after the moof
        frags.push(box);
      }
      off += bx.size;
    }
    s.acc = buf.slice(off);
    if (!frags.length) return self._pump(gen);              // nothing to convert yet (init segment, partial data)
    if (!s.init) { log("fragment before init segment: dropped"); return self._pump(gen); }
    var data = concat(frags), secs = fragSeconds(s.init, data, s.scales), init = s.init, pl = s.plan;
    var jobs = [];
    if (pl.video) jobs.push({ rsb: s.rsbs[0], v: true, a: false });
    if (pl.audio) jobs.push({ rsb: s.rsbs[pl.video ? 1 : 0], v: false, a: true });
    var out = [], left = jobs.length;
    whenReady(function () {
      if (gen !== s.gen) return;
      jobs.forEach(function (j, i) {
        var id = nextId++;
        pend.set(id, function (ok, payload) {
          if (gen !== s.gen) return;
          if (!ok) console.warn("[null-video] conversion failed:", payload);
          out[i] = ok ? unb64(payload) : null;
          if (--left === 0) self._append(gen, jobs, out);
        });
        bridge.mse(id, b64(init), b64(data), j.v, j.a, Math.round(secs * 1000));
      });
    });
  };
  ProxySB.prototype._append = function (gen, jobs, out) {
    var s = this._s, self = this;
    if (gen !== s.gen) return;
    var todo = [];
    jobs.forEach(function (j, i) { if (out[i]) todo.push([j.rsb, out[i]]); });
    if (!todo.length) return self._pump(gen);
    s.left = todo.length; s.done = function () { self._pump(gen); };
    todo.forEach(function (t) {
      try { t[0].appendBuffer(t[1]); }
      catch (e) { console.warn("[null-video] append failed:", e && e.name); if (--s.left === 0) { s.done = null; self._pump(gen); } }
    });
  };
  ProxySB.prototype.abort = function () {
    var s = this._s, was = s.u;
    s.gen++; s.queue = []; s.acc = new Uint8Array(0); s.left = 0; s.done = null;
    s.rsbs.forEach(function (r) { try { r.abort(); } catch (e) {} });
    if (was) { s.u = false; later(this, ["abort", "updateend"]); }
  };
  ProxySB.prototype.remove = function (a, b) {
    var s = this._s; if (this.updating) throw new DOMException("The SourceBuffer is still processing an update.", "InvalidStateError");
    s.rsbs.forEach(function (r) { r.remove(a, b); });
  };
  ProxySB.prototype.changeType = function (type) {
    var pl = plan(type), s = this._s;
    if (!pl || (pl.video ? 1 : 0) + (pl.audio ? 1 : 0) !== s.rsbs.length) throw new DOMException("Unsupported type", "NotSupportedError");
    s.plan = pl; s.rsbs[0].changeType(pl.video ? pl.outV : pl.outA); if (s.rsbs[1]) s.rsbs[1].changeType(pl.outA);
  };
  Object.defineProperty(ProxySB.prototype, Symbol.toStringTag, { value: "SourceBuffer" });

  /* ------------------------------------------------------------------ patches */
  MS.isTypeSupported = function isTypeSupported(type) { return NATIVE_IS(type) || !!plan(type); };
  var nAdd = MS.prototype.addSourceBuffer, nRemove = MS.prototype.removeSourceBuffer;
  MS.prototype.addSourceBuffer = function addSourceBuffer(type) {
    var pl = plan(type);
    if (!pl) return nAdd.call(this, type);
    var rsbs = [];
    if (pl.video) rsbs.push(nAdd.call(this, pl.outV));
    if (pl.audio) rsbs.push(nAdd.call(this, pl.outA));
    log("converting", type);
    proxiesSeen = true; track(null);
    return new ProxySB(this, rsbs, pl, type);
  };
  MS.prototype.removeSourceBuffer = function removeSourceBuffer(sb) {
    var r = sb && reals.get(sb); if (!r) return nRemove.call(this, sb);
    var self = this; r.forEach(function (x) { nRemove.call(self, x); });
  };
  ["sourceBuffers", "activeSourceBuffers"].forEach(function (k) {
    var d = Object.getOwnPropertyDescriptor(MS.prototype, k); if (!d || !d.get) return;
    Object.defineProperty(MS.prototype, k, { configurable: true, enumerable: true, get: function () {
      var list = d.get.call(this);
      return new Proxy(list, { get: function (t, p) {
        if (typeof p === "string" && /^\d+$/.test(p)) { var x = t[p]; return (x && proxies.get(x)) || x; }
        var v = t[p]; return typeof v === "function" ? v.bind(t) : v;
      } });
    } });
  });
  var nCan = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function canPlayType(type) {
    var r = nCan.call(this, type);
    return r || (plan(String(type)) ? "probably" : "");
  };
  try {
    var MC = window.MediaCapabilities && MediaCapabilities.prototype, nDec = MC && MC.decodingInfo;
    if (nDec) MC.decodingInfo = function decodingInfo(cfg) {
      return nDec.call(this, cfg).then(function (r) {
        if (r.supported || !cfg) return r;
        var ok = true, any = false;
        [cfg.video, cfg.audio].forEach(function (c) { if (c && c.contentType) { any = true; if (!(NATIVE_IS(c.contentType) || plan(c.contentType))) ok = false; } });
        return any && ok ? { supported: true, smooth: true, powerEfficient: false, keySystemAccess: null, configuration: cfg } : r;
      });
    };
  } catch (e) {}

  /* ------------------------------------------------------------------ small gaps at the start / between pieces */
  /* Converted audio and video rarely begin at exactly the same instant. Real players skip such gaps themselves; this only
     nudges an element that is stalled with data a few tenths of a second ahead. */
  var media = new Set(), jumper = 0;
  function track(el) { if (el) media.add(el); if (!jumper) jumper = setInterval(jump, 250); }
  function jump() {
    try { document.querySelectorAll("video,audio").forEach(function (m) { if (/^blob:/.test(m.currentSrc || m.src)) media.add(m); }); } catch (e) {}
    media.forEach(function (el) {
      if (!el.isConnected && !el.parentNode && el.readyState === 0) { media.delete(el); return; }
      if ((el.paused && !el.autoplay) || el.seeking || el.ended || el.readyState >= 3 || !el.buffered.length) return;
      var t = el.currentTime;
      for (var i = 0; i < el.buffered.length; i++) {
        var a = el.buffered.start(i), b = el.buffered.end(i);
        if (t >= a - 0.01 && t < b) return;                 // data is there; the player is only buffering
        if (a > t && a - t < 1.0) { el.currentTime = a + 0.005; return; }
      }
    });
  }
  var nPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function play() { if (proxiesSeen) track(this); return nPlay.apply(this, arguments); };
  
  /* ------------------------------------------------------------------ plain <video src="...mp4"> */
  /* A whole file cannot be fed to a SourceBuffer, so the browser downloads it, converts it with ffmpeg and streams the WebM
     back; the element plays a MediaSource that fills while it converts. */
  var nSrc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "src"), conv = new WeakMap();
  function mp4ish(url) {
    try { var u = new URL(String(url), document.baseURI); return /^https?:$/.test(u.protocol) && /\.(mp4|m4v|mov)(?![a-z0-9])/i.test(u.pathname); }
    catch (e) { return false; }
  }
  function stopFile(el) {
    var st = conv.get(el); if (!st) return;
    conv.delete(el); progs.delete(st.id);
    if (bridge) try { bridge.cancel(st.id); } catch (e) {}
  }
  function convertFile(el, url) {
    stopFile(el);
    var abs = new URL(String(url), document.baseURI).href;
    var st = { url: abs, id: nextId++, q: { video: [], audio: [] }, sb: {}, ended: false, ms: new MediaSource(), info: null, got: false, finished: 0 };
    conv.set(el, st);
    track(el);
    nSrc.set.call(el, URL.createObjectURL(st.ms));
    function pump(kind) {
      var sb = st.sb[kind]; if (!sb || sb.updating || conv.get(el) !== st) return;
      var q = st.q[kind];
      if (q.length) {
        var n = 0, parts = [];
        while (q.length && n < 1048576) { var c = unb64(q.shift()); parts.push(c); n += c.length; }
        try { sb.appendBuffer(concat(parts)); } catch (e) { console.warn("[null-video] append failed:", e && e.name); }
        return;
      }
      if (st.ended && st.ms.readyState === "open" && !Object.keys(st.sb).some(function (k) { return st.sb[k].updating || st.q[k].length; })) {
        try { st.ms.endOfStream(); } catch (e) {}
      }
    }
    st.ms.addEventListener("sourceopen", function () {
      whenReady(function () {
        if (conv.get(el) !== st) return;
        progs.set(st.id, function (kind, payload) {
          if (conv.get(el) !== st) return;
          if (kind === "meta") {
            st.info = JSON.parse(payload);
            if (st.info.video) { st.sb.video = nAdd.call(st.ms, 'video/webm; codecs="vp9"'); st.sb.video.addEventListener("updateend", function () { pump("video"); }); }
            if (st.info.audio) { st.sb.audio = nAdd.call(st.ms, 'audio/webm; codecs="opus"'); st.sb.audio.addEventListener("updateend", function () { pump("audio"); }); }
            if (st.info.duration > 0) { try { st.ms.duration = st.info.duration; } catch (e) {} }
          } else if (kind === "video" || kind === "audio") { st.got = true; st.q[kind].push(payload); pump(kind); }
          else if (kind === "end") { st.ended = true; pump("video"); pump("audio"); }
          else {                                              // error: hand the element back to the page as it was
            console.warn("[null-video] could not convert", st.url, payload);
            stopFile(el);
            if (!st.got) nSrc.set.call(el, st.url); else try { st.ms.endOfStream("decode"); } catch (e) {}
          }
        });
        bridge.prog(st.id, st.url, location.href, navigator.userAgent);
      });
    }, { once: true });
  }
  Object.defineProperty(HTMLMediaElement.prototype, "src", { configurable: true, enumerable: true,
    get: function () { var st = conv.get(this); return st ? st.url : nSrc.get.call(this); },
    set: function (v) { if (mp4ish(v)) convertFile(this, v); else { stopFile(this); nSrc.set.call(this, v); } } });
  var nSetAttr = Element.prototype.setAttribute;
  HTMLMediaElement.prototype.setAttribute = function setAttribute(name, value) {
    if (String(name).toLowerCase() === "src") { this.src = value; return; }
    return nSetAttr.apply(this, arguments);
  };
  document.addEventListener("error", function (e) {         // <video src> / <source> that the parser already tried and could not play
    var t = e.target, el = t instanceof HTMLMediaElement ? t : (t instanceof HTMLSourceElement ? t.parentElement : null);
    if (!(el instanceof HTMLMediaElement) || conv.has(el)) return;
    var url = t instanceof HTMLSourceElement ? t.src : (el.currentSrc || nSrc.get.call(el));
    if ((t !== el || (el.error && el.error.code === 4)) && mp4ish(url)) convertFile(el, url);
  }, true);
})();
