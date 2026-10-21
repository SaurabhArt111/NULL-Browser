"""Scriptlet policy: makes the community filter lists safe and cheap to run on big video / social sites.

Why this exists
---------------
The bundled lists (EasyList, Brave, uBlock ...) overlap, and their `##+js(...)` scriptlet rules were written for uBlock Origin's
own, matching scriptlet code. Run naively they pile up on exactly the sites people watch video on:

* the *same* rule arrives from two lists and is injected twice;
* every `json-prune` rule wraps `JSON.parse` again, so Facebook's eight rules mean eight nested wrappers on every parse
  (measured: ~60x slower `JSON.parse`; see tests/test_privacy_policy.py);
* response wrappers without a URL scope (`json-prune-fetch-response` ...) run on *every* fetch / XHR, media segments included;
* request-rewriting scriptlets change the player's own API calls, `nano-stb` speeds up the page's timers and
  `trusted-prevent-dom-bypass` hooks every DOM insertion method. Any of these can leave a player stuck on "try again".

`sanitize_lists()` runs once, on the list *text*, before any engine is built, so it behaves identically for the Rust, wheel and
pure-Python engines. Network and cosmetic rules are never touched. User rules are never sanitised (they are added afterwards).

"video safe" mode (the default, setting `adblock_video_safe`) applies the strict part of the policy to PLATFORMS only; every
other site keeps the full uBlock behaviour apart from de-duplication and `json-prune` merging.
"""
import re

from .scriptlets import parse_args

POLICY_REV = 3            # bump when the policy changes: part of the compiled-engine cache signature

# Sites where playback / feed code is complex enough that invasive scriptlets are not worth the risk.
PLATFORMS = frozenset((
    "youtube.com", "youtu.be", "youtube-nocookie.com", "googlevideo.com", "ytimg.com",
    "x.com", "twitter.com", "twimg.com", "t.co",
    "reddit.com", "redd.it", "redditmedia.com", "redditstatic.com",
    "facebook.com", "fb.com", "fb.watch", "fbcdn.net", "instagram.com", "cdninstagram.com", "threads.net", "threads.com",
    "twitch.tv", "ttvnw.net", "tiktok.com", "vimeo.com", "dailymotion.com", "netflix.com", "primevideo.com", "hotstar.com",
))

# Where an unscoped response wrapper gets its URL scope from, per platform (regex over the request URL).
DEFAULT_SCOPE = {
    "youtube.com": r"\/youtubei\/v1\/",
    "youtube-nocookie.com": r"\/youtubei\/v1\/",
    "x.com": r"\/i\/api\/graphql\/",
    "twitter.com": r"\/i\/api\/graphql\/",
    "facebook.com": r"\/api\/graphql",
    "instagram.com": r"\/graphql|\/api\/v1\/",
    "reddit.com": r"\/svc\/|graphql",
}

_ALIASES = {
    "set": "set-constant", "trusted-set": "trusted-set-constant", "aopr": "abort-on-property-read", "aopw": "abort-on-property-write",
    "aeld": "addEventListener-defuser", "acis": "abort-current-script", "rpnt": "replace-node-text", "rmnt": "remove-node-text",
    "trusted-rpnt": "trusted-replace-node-text", "nano-stb": "nano-setTimeout-booster", "nano-sib": "nano-setInterval-booster",
    "nosiif": "no-setInterval-if", "nostif": "no-setTimeout-if", "ra": "remove-attr", "rc": "remove-class",
}

# Rewrite what the page sends or how its code runs: removed on PLATFORMS.
_INVASIVE = frozenset((
    "trusted-prevent-dom-bypass", "nano-setTimeout-booster", "nano-setInterval-booster", "replace-node-text", "remove-node-text",
    "trusted-replace-node-text", "trusted-replace-argument", "trusted-json-edit-xhr-request", "json-edit-xhr-request",
    "trusted-json-edit-fetch-request", "json-edit-fetch-request", "trusted-edit-inbound-object", "trusted-edit-outbound-object",
    "trusted-edit-this-object", "trusted-edit-object-on-getter", "trusted-edit-object-on-setter", "trusted-edit-element-object",
    "trusted-prune-inbound-object", "trusted-prune-outbound-object", "trusted-create-html", "trusted-set-attr",
))
_MERGEABLE = frozenset(("json-prune",))
_RESPONSE_RX = re.compile(r"(^|-)(fetch|xhr)-response$|^jsonl?-edit")
_SCOPE_ARG = re.compile(r"(^|,)\s*propsToMatch\s*,", re.I)
_JS_MARK = "##+js("


def _norm(name):
    name = name.strip()
    if name.endswith(".js"):
        name = name[:-3]
    return _ALIASES.get(name, name)


def _platform_of(hosts):
    """The platform domain a rule's host list targets, or None (a rule with no host is never injected anyway)."""
    for h in hosts.split(","):
        h = h.strip().lower().lstrip("~")
        if not h or h.startswith("/"):
            continue
        h = h[:-2] if h.endswith(".*") else h
        parts = h.split(".")
        for i in range(len(parts)):
            cand = ".".join(parts[i:])
            if cand in PLATFORMS:
                return cand
    return None


def _is_scoped(name, parts):
    """Does this response wrapper only act on some URLs? (propsToMatch given, or the positional URL pattern of `trusted-replace-*`)."""
    tail = ",".join(parts[1:])
    if _SCOPE_ARG.search("," + tail) or "propsToMatch" in tail:
        return True
    if name.startswith(("trusted-replace-", "replace-")) and len(parts) >= 4 and parts[3].strip():
        return True
    return False


def _scoped_line(hosts, parts, platform):
    scope = DEFAULT_SCOPE.get(platform)
    if not scope:
        return None
    args = list(parts)
    while len(args) < 3:            # name, prunePaths, needlePaths
        args.append("")
    return f"{hosts}{_JS_MARK}{', '.join(args)}, propsToMatch, url:/{scope}/)"


_GHIDE_OPTS = frozenset(("ghide", "generichide", "ehide", "elemhide"))


def _expand_global_hide_exception(line):
    """`@@*$ghide,domain=a.com|b.com|~www.a.com` -> per-domain exceptions, or None if the line is not of that shape.

    The PyPI `adblock` wheel (an older adblock-rust) mis-reads this form and treats it as "generic hiding is off on every site",
    which silently disabled all class / id based ad hiding. Per-domain `@@||a.com^$generichide` is understood by every engine."""
    if not line.startswith(("@@*$", "@@$")):
        return None
    opts = line[line.index("$") + 1:].split(",")
    if not any(o in _GHIDE_OPTS for o in opts):
        return None
    doms = []
    for o in opts:
        if o.startswith("domain="):
            doms = [d for d in o[7:].split("|") if d and not d.startswith("~")]
    if not doms:
        return None
    return [f"@@||{d}^$generichide" for d in doms]


class Report:
    """What the policy did (shown in Settings and tested)."""

    def __init__(self):
        self.seen = self.duplicates = self.dropped = self.scoped = self.merged_in = self.merged_out = self.expanded = 0

    def as_dict(self):
        return dict(self.__dict__)

    def __repr__(self):
        return f"<Policy {self.as_dict()}>"


def sanitize_lists(lists, video_safe=True):
    """lists: [(text, fmt)] -> ([(text, fmt)], Report). Only "standard" lists are examined."""
    rep = Report()
    seen = set()
    merge = {}                       # hosts -> [prune paths]
    out = []
    for text, fmt in lists:
        if fmt == "standard" and ("@@*$" in text or "@@$" in text):
            fixed = []
            for ln in text.split("\n"):
                ex = _expand_global_hide_exception(ln.rstrip("\r")) if ln[:3] in ("@@*", "@@$") else None
                if ex is not None:
                    fixed.extend(ex)
                    rep.expanded += 1
                else:
                    fixed.append(ln)
            text = "\n".join(fixed)
        if fmt != "standard" or "+js(" not in text:
            out.append((text, fmt))
            continue
        keep = []
        for line in text.split("\n"):
            i = line.find(_JS_MARK)
            if i < 0 or line[:1] == "!":
                keep.append(line)
                continue
            line = line.rstrip("\r")
            if not line.endswith(")") or "#@#" in line[:i + 3]:
                keep.append(line)
                continue
            rep.seen += 1
            hosts, inner = line[:i], line[i + len(_JS_MARK):-1]
            parts = parse_args(inner)
            if not parts:
                keep.append(line)
                continue
            name = _norm(parts[0])
            platform = _platform_of(hosts)
            strict = video_safe and platform is not None
            if strict and name in _INVASIVE:
                rep.dropped += 1
                continue
            if strict and _RESPONSE_RX.search(name) and not _is_scoped(name, parts):
                fixed = _scoped_line(hosts, parts, platform) if name.startswith(("json-prune-", "json-edit-")) else None
                if fixed is None:
                    rep.dropped += 1
                    continue
                rep.scoped += 1
                line = fixed
                parts = parse_args(line[line.find(_JS_MARK) + len(_JS_MARK):-1])
            key = (hosts.strip().lower(), ", ".join(p.strip() for p in parts))
            if key in seen:
                rep.duplicates += 1
                continue
            seen.add(key)
            if name in _MERGEABLE and len(parts) == 2 and parts[1].strip():
                merge.setdefault(hosts.strip(), []).append(parts[1].strip())
                rep.merged_in += 1
                continue
            keep.append(line)
        out.append(("\n".join(keep), fmt))
    if merge:
        lines = []
        for hosts, paths in merge.items():
            uniq = []
            for p in paths:
                for tok in p.split():
                    if tok not in uniq:
                        uniq.append(tok)
            lines.append(f"{hosts}{_JS_MARK}json-prune, {' '.join(uniq)})")
            rep.merged_out += 1
        out.append(("\n".join(lines) + "\n", "standard"))
    return out, rep
