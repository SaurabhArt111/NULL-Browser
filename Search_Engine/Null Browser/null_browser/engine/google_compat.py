"""Compatibility for Google's sign-in page.

Google refuses to sign you in ("This browser or app may not be secure") when it believes the browser is an embedded web view. One of
the things it looks at is the browser's brand list: Chrome announces "Google Chrome", an engine embedded in another program announces
only "Chromium". For Google's own sites (and only those) Null Browser announces both, in the request header (`Sec-CH-UA`) and in
`navigator.userAgentData`, and provides the `window.chrome` object that Chrome has.

This is a compatibility aid, not a guarantee: Google also uses signals nobody outside Google knows, and may still say no. Nothing here
is sent to sites other than Google's, and nothing is sent to anyone but the sites you open. Switch it off in Settings -> Google account.
"""
import re

# hosts that get the Chrome brand (suffix match)
HOSTS = ("google.com", "youtube.com", "gstatic.com")
HOSTS_REGEX = r"(^|\.)(google\.[a-z.]{2,6}|youtube\.com|gstatic\.com)$"


def chrome_major(user_agent):
    m = re.search(r"Chrome/(\d+)", user_agent or "")
    return m.group(1) if m else "130"


def client_hints(user_agent):
    """Value of the Sec-CH-UA request header for Google's hosts."""
    v = chrome_major(user_agent)
    return f'"Chromium";v="{v}", "Google Chrome";v="{v}", "Not_A Brand";v="24"'.encode()


def is_google_host(host):
    host = (host or "").lower()
    return host.endswith(HOSTS) and (host in HOSTS or host.endswith(tuple("." + h for h in HOSTS)))


SCRIPT = r"""(function () {
  try {
    if (!/__HOSTS__/.test(location.hostname)) return;
    var M = "__MAJOR__", FULL = M + ".0.0.0";
    var brands = [{ brand: "Chromium", version: M }, { brand: "Google Chrome", version: M }, { brand: "Not_A Brand", version: "24" }];
    var full = [{ brand: "Chromium", version: FULL }, { brand: "Google Chrome", version: FULL }, { brand: "Not_A Brand", version: "24.0.0.0" }];
    var copy = function (l) { return l.map(function (b) { return { brand: b.brand, version: b.version }; }); };
    var uad = navigator.userAgentData;
    if (uad) {
      var proto = Object.getPrototypeOf(uad);
      Object.defineProperty(proto, "brands", { configurable: true, enumerable: true, get: function () { return copy(brands); } });
      var orig = proto.getHighEntropyValues;
      if (orig) proto.getHighEntropyValues = function (hints) {
        return orig.call(this, hints).then(function (v) { if (v) { v.brands = copy(brands); if ("fullVersionList" in v || (hints || []).indexOf("fullVersionList") >= 0) v.fullVersionList = copy(full); } return v; });
      };
      proto.toJSON = function () { return { brands: copy(brands), mobile: this.mobile, platform: this.platform }; };
    }
    if (!window.chrome) window.chrome = { app: { isInstalled: false }, runtime: {}, loadTimes: function () { return {}; }, csi: function () { return {}; } };
  } catch (e) {}
})();"""


def script_source(major, hosts_regex=HOSTS_REGEX):
    return SCRIPT.replace("__HOSTS__", hosts_regex.replace("/", r"\/")).replace("__MAJOR__", str(major))
