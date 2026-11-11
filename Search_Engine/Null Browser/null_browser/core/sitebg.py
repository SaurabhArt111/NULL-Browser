"""Remembers the page colour of each site, so a dark site does not flash white while it loads.

Until a page paints, the view shows its background colour. Web pages used to start white (like Chrome), which on a dark site
(X, Reddit, GitHub dark ...) is a bright flash on every navigation. After a page finishes loading its colour is read once and kept
per host; the next visit starts with that colour. Private windows neither read nor write this. Only host name and colour are kept.
"""
import json
import logging
import os
import re

from . import paths

log = logging.getLogger("null.sitebg")
FILE = "site-colors.json"
MAX = 600
_HEX = re.compile(r"^#[0-9a-f]{6}$")

# Runs in the page after it loaded: the colour behind its content, or '' when it is transparent (the canvas is then white / theme).
READ_JS = r"""(function(){try{function c(e){if(!e)return '';var v=getComputedStyle(e).backgroundColor||'';
var m=v.match(/^rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)(?:[ ,/]+([\d.]+%?))?\s*\)$/);if(!m)return '';
var a=m[4]===undefined?1:(m[4].slice(-1)==='%'?parseFloat(m[4])/100:parseFloat(m[4]));if(a<0.9)return '';
return '#'+[m[1],m[2],m[3]].map(function(x){return ('0'+(+x).toString(16)).slice(-2);}).join('');}
return c(document.body)||c(document.documentElement)||'';}catch(e){return '';}})()"""


class SiteBackgrounds:
    def __init__(self):
        self._map = {}
        self._dirty = False
        try:
            with open(os.path.join(paths.data_dir(), FILE), encoding="utf-8") as f:
                data = json.load(f)
            self._map = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and _HEX.match(v)}
        except (OSError, ValueError, AttributeError):
            self._map = {}

    def get(self, host):
        return self._map.get((host or "").lower())

    def put(self, host, color):
        host = (host or "").lower()
        if not host:
            return
        color = (color or "").lower()
        if not _HEX.match(color):
            if host in self._map:
                del self._map[host]
                self._dirty = True
            return
        if self._map.get(host) != color:
            if len(self._map) >= MAX and host not in self._map:
                self._map.pop(next(iter(self._map)))
            self._map[host] = color
            self._dirty = True

    def clear(self):
        self._map.clear()
        self._dirty = True
        self.save()

    def save(self):
        if not self._dirty:
            return
        self._dirty = False
        try:
            with open(os.path.join(paths.data_dir(), FILE), "w", encoding="utf-8") as f:
                json.dump(self._map, f)
        except OSError:
            log.debug("could not save site colours", exc_info=True)
