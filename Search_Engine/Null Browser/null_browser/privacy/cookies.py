"""Third-party cookie policy used by the profile's cookie filter.

`QWebEngineCookieStore.setCookieFilter` calls Python on Chromium's IO thread for *every* cookie read and write of every
request. So the verdict is memoised per (first-party host, cookie domain, setting generation) and the filter is only
installed when some policy other than "allow everything" is in force.

Cookies between sites of the same company are not treated as third-party (the idea behind Chrome's Related Website Sets):
blocking `twimg.com` cookies on `x.com` or `fbcdn.net` on `facebook.com` only breaks sign-in and media for no privacy gain.
"""

RELATED = (
    ("x.com", "twitter.com", "twimg.com", "t.co", "abs.twimg.com"),
    ("facebook.com", "fb.com", "fbcdn.net", "fb.watch", "instagram.com", "cdninstagram.com", "messenger.com", "threads.net", "facebook.net"),
    ("youtube.com", "youtu.be", "google.com", "googlevideo.com", "ytimg.com", "ggpht.com", "gstatic.com", "googleapis.com",
     "youtube-nocookie.com", "googleusercontent.com", "accounts.google.com"),
    ("reddit.com", "redd.it", "redditmedia.com", "redditstatic.com"),
    ("microsoft.com", "live.com", "microsoftonline.com", "office.com", "bing.com", "msn.com", "linkedin.com"),
    ("amazon.com", "media-amazon.com", "ssl-images-amazon.com", "primevideo.com", "amazon.in", "amazon.co.uk"),
    ("twitch.tv", "ttvnw.net", "twitchcdn.net", "jtvnw.net"),
    ("github.com", "githubusercontent.com", "githubassets.com"),
    ("apple.com", "icloud.com", "cdn-apple.com", "mzstatic.com"),
)
_GROUP = {}
for _i, _g in enumerate(RELATED):
    for _d in _g:
        _GROUP[_d] = _i


def registrable(host):
    parts = host.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def group_of(host):
    host = host.lower().strip(".")
    parts = host.split(".")
    for i in range(len(parts) - 1):
        g = _GROUP.get(".".join(parts[i:]))
        if g is not None:
            return g
    return None


def same_party(a, b):
    """Are two hosts the same site, or sites of one company?"""
    if not a or not b:
        return False
    ra, rb = registrable(a), registrable(b)
    if ra == rb:
        return True
    ga, gb = group_of(a), group_of(b)
    return ga is not None and ga == gb


class CookiePolicy:
    """Callable for `cookieStore().setCookieFilter`."""

    def __init__(self, perms):
        self.perms = perms
        self._memo = {}

    def invalidate(self):
        self._memo.clear()

    def needed(self):
        """False when nothing can ever be blocked, so the filter need not run at all."""
        if self.perms.default("cookies") != "allow":
            return True
        return any(f == "cookies" for (_o, f) in self.perms.cache)

    def __call__(self, req):
        try:
            first = req.firstPartyUrl                      # data members of FilterRequest, not methods
            if first.scheme() not in ("http", "https"):
                return True
            fh = first.host()
            key = (fh, req.origin.host(), bool(req.thirdParty))
            v = self._memo.get(key)
            if v is None:
                v = self._decide(fh, req)
                if len(self._memo) > 4000:
                    self._memo.clear()
                self._memo[key] = v
            return v
        except Exception:
            return True

    def _decide(self, first_host, req):
        from ..core.permissions import origin_of
        verdict = self.perms.effective(origin_of(f"{req.firstPartyUrl.scheme()}://{first_host}"), "cookies")
        if verdict == "block":
            return False
        if verdict == "block_third" and req.thirdParty and not same_party(first_host, req.origin.host()):
            return False
        return True
