"""Site permission catalog, defaults, per-site overrides and the JS API shim.

Enforcement tiers (shown honestly in null://settings/content):
  engine   - Chromium asks the browser; Null Browser shows a prompt / applies the stored decision.
  setting  - applied through QtWebEngine settings, the request interceptor or the cookie filter.
  shim     - the JS API is removed (Block) or gated behind a native prompt (Ask) by an injected script.
  restart  - applied as a Chromium command-line flag on next launch.
  stored   - saved and shown, but Qt exposes no hook to enforce it yet.
"""
import json
from urllib.parse import urlsplit

ALLOW, ASK, BLOCK = "allow", "ask", "block"
_AAB = [("ask", "Sites can ask"), ("allow", "Allow"), ("block", "Block")]
_AB = [("allow", "Allow"), ("block", "Block")]

# id, label, description, group, options, default, per_site, enforcement
_RAW = [
    ("location", "Location", "Sites can ask to know your location", "Permissions", _AAB, ASK, True, "engine"),
    ("camera", "Camera", "Sites can ask to use your camera", "Permissions", _AAB, ASK, True, "engine"),
    ("microphone", "Microphone", "Sites can ask to use your microphone", "Permissions", _AAB, ASK, True, "engine"),
    ("motion_sensors", "Motion sensors", "Sites can use motion and orientation sensors", "Permissions", _AB, ALLOW, True, "shim"),
    ("notifications", "Notifications", "Sites can ask to send notifications", "Permissions", _AAB, ASK, True, "engine"),
    ("background_sync", "Background sync", "Recently closed sites can finish sending and receiving data", "Permissions", _AB, ALLOW, True, "shim"),
    ("midi", "MIDI device control & reprogram", "Sites can ask to control and reprogram MIDI devices", "Permissions", _AAB, ASK, True, "shim"),
    ("usb", "USB devices", "Sites can ask to connect to USB devices", "Permissions", _AAB, ASK, True, "shim"),
    ("serial", "Serial ports", "Sites can ask to connect to serial ports", "Permissions", _AAB, ASK, True, "shim"),
    ("file_editing", "File editing", "Sites can ask to edit files and folders on your device", "Permissions", _AAB, ASK, True, "shim"),
    ("hid", "HID devices", "Sites can ask to connect to HID devices", "Permissions", _AAB, ASK, True, "shim"),
    ("clipboard", "Clipboard", "Sites can ask to see text and images on your clipboard", "Permissions", _AAB, ASK, True, "engine"),
    ("payment_handlers", "Payment handlers", "Sites can install payment handlers", "Permissions", _AB, ALLOW, True, "shim"),
    ("ar", "Augmented reality", "Sites can ask to create a 3D map of your surroundings", "Permissions", _AAB, ASK, True, "shim"),
    ("vr", "Virtual reality", "Sites can ask to use virtual reality devices", "Permissions", _AAB, ASK, True, "shim"),
    ("hand_tracking", "Hand tracking", "Sites can ask to track your hand positions", "Permissions", _AAB, ASK, True, "shim"),
    ("device_use", "Your device use", "Sites can ask to know when you're actively using your device", "Permissions", _AAB, ASK, True, "shim"),
    ("window_management", "Window management", "Sites can ask to use information about your displays", "Permissions", _AAB, ASK, True, "shim"),
    ("fonts", "Fonts", "Sites can ask to use fonts installed on your device", "Permissions", _AAB, ASK, True, "engine"),
    ("auto_pip", "Automatic picture-in-picture", "Sites can ask to enter picture-in-picture automatically", "Permissions", _AAB, ASK, True, "shim"),
    ("scroll_zoom_shared_tabs", "Scrolling and zooming shared tabs", "Sites can ask to scroll and zoom tabs you share", "Permissions", _AAB, ASK, True, "stored"),
    ("web_app_install", "Web app installations", "Sites can ask to install web apps", "Permissions", _AAB, ASK, True, "shim"),
    ("local_network", "Local network", "Sites can ask to connect to devices on your local network", "Permissions", _AAB, ASK, True, "stored"),
    ("apps_on_device", "Apps on device", "Sites can ask to check which related apps you have installed", "Permissions", _AAB, ASK, True, "shim"),
    ("screen_capture", "Screen sharing", "Sites can ask to capture your screen or windows", "Permissions", _AAB, ASK, True, "engine"),
    ("mouse_lock", "Cursor lock", "Sites can ask to hide and capture your mouse pointer", "Permissions", _AAB, ASK, True, "engine"),
    # ---- Content
    ("cookies", "Cookies and site data", "Third-party cookies are blocked by default", "Content",
     [("allow", "Allow all cookies"), ("block_third", "Block third-party cookies"), ("block", "Block all cookies")], "block_third", True, "setting"),
    ("javascript", "JavaScript", "Sites can use JavaScript", "Content", _AB, ALLOW, True, "setting"),
    ("images", "Images", "Sites can show images", "Content", _AB, ALLOW, True, "setting"),
    ("popups", "Pop-ups and redirects", "Don't allow sites to send pop-ups or use redirects", "Content", [("allow", "Allow"), ("block", "Block")], BLOCK, True, "setting"),
    ("intrusive_ads", "Intrusive ads", "Block ads on sites that show intrusive or misleading ads", "Content", [("allow", "Allow"), ("block", "Block")], BLOCK, True, "setting"),
    ("sound", "Sound", "Sites can play sound", "Content", [("automatic", "Automatic"), ("mute", "Mute")], "automatic", True, "setting"),
    ("automatic_downloads", "Automatic downloads", "Sites can download several files in a row", "Content", _AAB, ALLOW, True, "setting"),
    ("autoplay", "Autoplay media", "Sites can play audio and video without interaction", "Content", [("allow", "Allow"), ("block", "Require interaction")], ALLOW, False, "setting"),
    ("insecure_content", "Insecure content", "Insecure content is blocked on secure sites", "Content", [("allow", "Allow"), ("block", "Block")], BLOCK, True, "setting"),
    # ---- Additional content settings
    ("protected_content", "Protected content IDs", "Sites can play protected content (DRM, Widevine-style key requests)", "Additional", _AB, ALLOW, True, "shim"),
    ("js_optimization", "JavaScript optimization & security", "Allow sites to use V8 optimization (turn off for extra security; needs restart)", "Additional", _AB, ALLOW, False, "restart"),
    ("third_party_signin", "Third-party sign-in", "Sites can show sign-in prompts from identity services", "Additional", _AB, ALLOW, True, "shim"),
]

CATALOG = [dict(id=i, label=l, desc=d, group=g, options=[{"value": v, "label": t} for v, t in o],
                default=df, per_site=ps, enforce=e) for i, l, d, g, o, df, ps, e in _RAW]
BY_ID = {c["id"]: c for c in CATALOG}

QT_PERMISSION_MAP = {
    "Geolocation": ["location"],
    "MediaAudioCapture": ["microphone"],
    "MediaVideoCapture": ["camera"],
    "MediaAudioVideoCapture": ["camera", "microphone"],
    "DesktopVideoCapture": ["screen_capture"],
    "DesktopAudioVideoCapture": ["screen_capture"],
    "Notifications": ["notifications"],
    "ClipboardReadWrite": ["clipboard"],
    "LocalFontsAccess": ["fonts"],
    "MouseLock": ["mouse_lock"],
}

PROMPT_VERBS = {
    "location": "know your location", "camera": "use your camera", "microphone": "use your microphone",
    "notifications": "show notifications", "clipboard": "see text and images copied to the clipboard",
    "fonts": "use fonts installed on your device", "screen_capture": "share your screen",
    "mouse_lock": "hide and lock your mouse pointer", "midi": "control and reprogram your MIDI devices",
    "usb": "connect to a USB device", "serial": "connect to a serial port",
    "file_editing": "edit files on your device", "hid": "connect to an HID device",
    "ar": "create a 3D map of your surroundings", "vr": "use your virtual reality devices",
    "hand_tracking": "track your hand positions", "device_use": "know when you're actively using this device",
    "window_management": "manage windows on all your displays", "auto_pip": "enter picture-in-picture automatically",
    "web_app_install": "install this site as an app", "apps_on_device": "check which related apps you have installed",
    "motion_sensors": "use your motion sensors", "local_network": "connect to devices on your local network",
    "scroll_zoom_shared_tabs": "scroll and zoom tabs you share",
}

SHIM_FEATURES = [c["id"] for c in CATALOG if c["enforce"] == "shim"]
import secrets
ASK_PREFIX = "__NULLPERM_" + secrets.token_hex(8) + "__:"   # per-process nonce: pages cannot forge the shim prompt


def origin_of(url):
    """Normalised origin string (scheme://host[:port]) for a URL / QUrl string."""
    try:
        u = urlsplit(str(url))
        port = u.port
    except ValueError:
        return ""
    if not u.scheme or not u.hostname:
        return ""
    p = f":{port}" if port and (u.scheme, port) not in (("http", 80), ("https", 443)) else ""
    host = u.hostname
    try:
        host = host.encode("idna").decode("ascii")          # JS location.origin is punycode
    except UnicodeError:
        pass
    return f"{u.scheme}://{host}{p}"


class PermissionManager:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings
        self.cache = {}                    # (origin, feature) -> value, kept in RAM for IO-thread lookups
        self.session = {}                  # decisions made in private windows: never written to disk
        self.on_change = None              # callable(): app regenerates the JS gate when anything changes
        self.reload()

    def _changed(self):
        cb = self.on_change
        if cb:
            try:
                cb()
            except Exception:
                pass

    def reload(self):
        self.cache = {(r["origin"], r["feature"]): r["value"] for r in self.db.site_perms_list()}

    def default(self, feature):
        over = self.settings.get("permission_defaults") or {}
        if feature in over and any(o["value"] == over[feature] for o in BY_ID[feature]["options"]):
            return over[feature]
        return BY_ID[feature]["default"]

    def set_default(self, feature, value):
        if feature not in BY_ID or not any(o["value"] == value for o in BY_ID[feature]["options"]):
            return False
        over = dict(self.settings.get("permission_defaults") or {})
        over[feature] = value
        self.settings.set("permission_defaults", over)
        self._changed()
        return True

    def site(self, origin, feature):
        return self.cache.get((origin, feature))

    def effective(self, origin, feature, private=False):
        if BY_ID[feature]["per_site"] and origin:
            v = (self.session.get((origin, feature)) if private else None) or self.cache.get((origin, feature))
            if v:
                return v
        return self.default(feature)

    def set_site(self, origin, feature, value, private=False):
        ok = self._set_site(origin, feature, value, private)
        if ok:
            self._changed()
        return ok

    def _set_site(self, origin, feature, value, private=False):
        if feature not in BY_ID or not origin:
            return False
        if private:
            if value in (None, "", "default"):
                self.session.pop((origin, feature), None)
            else:
                if not any(o["value"] == value for o in BY_ID[feature]["options"]):
                    return False
                self.session[(origin, feature)] = value
            return True
        if value in (None, "", "default"):
            self.session.pop((origin, feature), None)
            if not private:
                self.cache.pop((origin, feature), None)
                self.db.set_site_perm(origin, feature, None)
        else:
            if not any(o["value"] == value for o in BY_ID[feature]["options"]):
                return False
            self.cache[(origin, feature)] = value
            self.db.set_site_perm(origin, feature, value)
        return True

    def reset_site(self, origin):
        for k in [k for k in self.cache if k[0] == origin]:
            self.cache.pop(k, None)
        for k in [k for k in self.session if k[0] == origin]:
            self.session.pop(k, None)
        self.db.clear_site_perms(origin)
        self._changed()

    def reset_all_sites(self):
        self.cache.clear()
        self.session.clear()
        self.db.clear_site_perms()
        self._changed()

    def catalog_with_state(self):
        out = []
        for c in CATALOG:
            d = dict(c)
            d["current"] = self.default(c["id"])
            d["exceptions"] = sum(1 for k in self.cache if k[1] == c["id"])
            out.append(d)
        return out

    # -- JS shim -------------------------------------------------------------------------
    def shim_table(self, private=False):
        """Defaults + per-site exceptions for every API the JS gate controls. One profile-level script carries the
        whole table and picks its row by location.origin, so there is no per-navigation script swap to race."""
        sites = {}
        for (origin, feature), value in self.cache.items():
            if feature in SHIM_FEATURES:
                sites.setdefault(origin, {})[feature] = value
        if private:
            for (origin, feature), value in self.session.items():
                if feature in SHIM_FEATURES:
                    sites.setdefault(origin, {})[feature] = value
        return {"defaults": {f: self.default(f) for f in SHIM_FEATURES}, "sites": sites}

    def shim_source(self, private=False):
        table = json.dumps(self.shim_table(private)).replace("</", "<\\/")
        return SHIM_JS.replace("__TABLE__", table).replace("__PREFIX__", json.dumps(ASK_PREFIX))


SHIM_JS = r"""
(function () {
  'use strict';
  if (window.__nullShim) return; window.__nullShim = true;
  const T = __TABLE__, PREFIX = __PREFIX__;
  const own = Object.prototype.hasOwnProperty;
  const P = Object.assign({}, T.defaults, own.call(T.sites, location.origin) ? T.sites[location.origin] : {});
  const nativeConfirm = window.confirm.bind(window);
  const decided = {};                                   // "Allow this time" / dismissed prompts last for the page's lifetime
  function denied(what) { return new DOMException('Permission denied by site settings (' + what + ')', 'NotAllowedError'); }
  function askSync(f) {
    if (own.call(decided, f)) return decided[f];
    let r = false; try { r = !!nativeConfirm(PREFIX + f); } catch (e) {}
    return (decided[f] = r);
  }
  function hide(obj, key) { try { if (obj && key in obj) Object.defineProperty(obj, key, { get() { return undefined; }, set() {}, configurable: true }); } catch (e) {} }
  function del(obj, key) { try { delete obj[key]; } catch (e) {} hide(obj, key); }
  function gate(obj, method, feature, fallback) {
    try {
      if (!obj || typeof obj[method] !== 'function' || P[feature] === 'allow') return;
      const orig = obj[method];
      const wrapped = function () {
        if (P[feature] === 'block') return fallback ? fallback.apply(this, arguments) : Promise.reject(denied(feature));
        if (P[feature] === 'ask' && !askSync(feature)) return fallback ? fallback.apply(this, arguments) : Promise.reject(denied(feature));
        return orig.apply(this, arguments);
      };
      try { Object.defineProperty(obj, method, { value: wrapped, configurable: true, writable: true }); } catch (e) { obj[method] = wrapped; }
    } catch (e) {}
  }
  const nav = navigator;
  gate(nav, 'requestMIDIAccess', 'midi');
  if (P.usb === 'block') del(Navigator.prototype, 'usb'); else gate(nav.usb, 'requestDevice', 'usb');
  if (P.serial === 'block') del(Navigator.prototype, 'serial'); else gate(nav.serial, 'requestPort', 'serial');
  if (P.hid === 'block') del(Navigator.prototype, 'hid'); else gate(nav.hid, 'requestDevice', 'hid');
  ['showOpenFilePicker', 'showSaveFilePicker', 'showDirectoryPicker'].forEach(function (m) {
    if (P.file_editing === 'block') del(window, m); else gate(window, m, 'file_editing');
  });
  try {
    if (nav.xr) {
      const xr = nav.xr, req = xr.requestSession && xr.requestSession.bind(xr), sup = xr.isSessionSupported && xr.isSessionSupported.bind(xr);
      const featureFor = function (mode) { return mode === 'immersive-ar' ? 'ar' : mode === 'immersive-vr' ? 'vr' : null; };
      if (req) xr.requestSession = function (mode, opts) {
        const f = featureFor(mode);
        const wants = JSON.stringify(opts || {}).indexOf('hand-tracking') >= 0;
        for (const feat of [f, wants ? 'hand_tracking' : null]) {
          if (!feat) continue;
          if (P[feat] === 'block' || (P[feat] === 'ask' && !askSync(feat))) return Promise.reject(denied(feat));
        }
        return req(mode, opts);
      };
      if (sup) xr.isSessionSupported = function (mode) { const f = featureFor(mode); if (f && P[f] === 'block') return Promise.resolve(false); return sup(mode); };
    }
  } catch (e) {}
  try {
    if (window.IdleDetector) {
      if (P.device_use === 'block') del(window, 'IdleDetector'); else gate(window.IdleDetector, 'requestPermission', 'device_use');
    }
  } catch (e) {}
  if (P.window_management === 'block') { del(window, 'getScreenDetails'); try { Object.defineProperty(Screen.prototype, 'isExtended', { get() { return false; }, configurable: true }); } catch (e) {} }
  else gate(window, 'getScreenDetails', 'window_management');
  if (P.apps_on_device !== 'allow') gate(nav, 'getInstalledRelatedApps', 'apps_on_device', function () { return Promise.resolve([]); });
  if (P.motion_sensors === 'block') {
    ['Accelerometer', 'Gyroscope', 'Magnetometer', 'LinearAccelerationSensor', 'GravitySensor',
     'AbsoluteOrientationSensor', 'RelativeOrientationSensor', 'AmbientLightSensor', 'DeviceMotionEvent', 'DeviceOrientationEvent'].forEach(function (k) { del(window, k); });
  }
  const blockedEvents = {};
  if (P.motion_sensors === 'block') { blockedEvents.devicemotion = 1; blockedEvents.deviceorientation = 1; blockedEvents.deviceorientationabsolute = 1; }
  if (P.web_app_install !== 'allow') blockedEvents.beforeinstallprompt = 1;
  if (Object.keys(blockedEvents).length) {
    const add = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function (t) { if (blockedEvents[t]) return; return add.apply(this, arguments); };
  }
  if (P.web_app_install !== 'allow') { try { Object.defineProperty(window, 'onbeforeinstallprompt', { set() {}, get() { return null; }, configurable: true }); } catch (e) {} }
  if (P.background_sync === 'block') {
    ['SyncManager', 'PeriodicSyncManager'].forEach(function (k) { del(window, k); });
    try { if (window.ServiceWorkerRegistration) { del(ServiceWorkerRegistration.prototype, 'sync'); del(ServiceWorkerRegistration.prototype, 'periodicSync'); } } catch (e) {}
  }
  if (P.payment_handlers === 'block') { ['PaymentRequest', 'PaymentRequestUpdateEvent', 'PaymentResponse'].forEach(function (k) { del(window, k); }); }
  if (P.protected_content === 'block' && nav.requestMediaKeySystemAccess)
    nav.requestMediaKeySystemAccess = function () { return Promise.reject(denied('protected_content')); };
  if (P.third_party_signin === 'block') { ['IdentityCredential', 'IdentityProvider', 'FederatedCredential'].forEach(function (k) { del(window, k); }); }
  if (P.auto_pip !== 'allow' && nav.mediaSession && nav.mediaSession.setActionHandler) {
    const sah = nav.mediaSession.setActionHandler.bind(nav.mediaSession);
    nav.mediaSession.setActionHandler = function (a, h) { if (a === 'enterpictureinpicture' && (P.auto_pip === 'block' || !askSync('auto_pip'))) return; return sah(a, h); };
  }
})();
"""
