"""Hosts whose media / API traffic is never sent through the filter engine.

Every network request of every page passes through `AdBlocker.interceptRequest` on Chromium's IO thread, in Python, holding the
GIL. Video players issue hundreds of range / segment requests per minute (YouTube `videoplayback`, X `video.twimg.com`, Reddit
`v.redd.it` ...). They are not ads that a network rule can tell apart, they are all different URLs (so the decision cache
never hits) and matching them costs milliseconds each. Skipping them removes the load from the hot path and also means a
filter-list update can never break playback.

Only *non-script* resource types are exempted, so scripts and frames from these hosts are still filtered.
"""

# registrable-ish suffixes of media CDNs
MEDIA_CDNS = (
    "googlevideo.com", "video.twimg.com", "v.redd.it", "fbcdn.net", "cdninstagram.com", "ttvnw.net", "vimeocdn.com",
    "dmcdn.net", "tiktokcdn.com", "tiktokcdn-us.com", "akamaized.net", "hls.ttvnw.net",
)
SKIP_TYPES = frozenset(("media", "image", "font", "other", "xmlhttprequest", "ping"))
MEDIA_EXT = (".mp4", ".m4s", ".m4v", ".m4a", ".webm", ".ts", ".m3u8", ".mpd", ".mp3", ".aac", ".ogg", ".opus", ".weba")


def is_media_host(host):
    for c in MEDIA_CDNS:
        if host == c or host.endswith("." + c):
            return True
    return False


def is_media_path(path):
    p = path.lower()
    return p.endswith(MEDIA_EXT) or "/videoplayback" in p
