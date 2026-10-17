"""Pure-Python Adblock Plus / uBlock Origin filter engine (tier-3 fallback).

Null Browser prefers the Rust engine (Brave's adblock-rust, see `adblockengine.py`). When no native engine can be loaded
(no wheel for this Python, locked-down PC...) this module gives the *same API* with the parts of the filter syntax that
matter in practice:

* network filters: `||domain^`, `|` anchors, `*`, `^`, `/regex/`, exceptions (`@@`), `$` options: third-party, domain=,
  denyallow=, resource types (negatable), important, match-case, badfilter, redirect= / redirect-rule= (with the
  bundled resources), removeparam=, generichide / elemhide / document exceptions;
* cosmetic filters: generic and per-domain hide rules, `#@#` exceptions, entity domains (`google.*`).

Not supported (the rule is *skipped*, never mis-applied): procedural cosmetics (`:has-text`, `:xpath` ...), scriptlet
injection (`##+js`), `$csp`, `$replace`, `$header`, `$method`, `$to`. Use the native engine for those.

Lookup is token-indexed (like adblock-rust): every rule is filed under the rarest-looking alphanumeric token of its
pattern, so a request is only compared with the few rules that share a token with its URL.
"""
import base64
import json
import marshal
import re
from urllib.parse import quote, unquote

# request-type bits ---------------------------------------------------------------------------------------------------
T_DOC, T_SUB, T_CSS, T_SCRIPT, T_IMG, T_FONT, T_MEDIA, T_OBJ, T_XHR, T_PING, T_WS, T_CSP, T_OTHER, T_POPUP = (1 << i for i in range(14))
_TYPE_NAMES = {
    "document": T_DOC, "doc": T_DOC, "subdocument": T_SUB, "frame": T_SUB, "stylesheet": T_CSS, "css": T_CSS, "script": T_SCRIPT,
    "image": T_IMG, "font": T_FONT, "media": T_MEDIA, "object": T_OBJ, "object-subrequest": T_OBJ, "xmlhttprequest": T_XHR,
    "xhr": T_XHR, "ping": T_PING, "beacon": T_PING, "websocket": T_WS, "csp_report": T_CSP, "other": T_OTHER, "popup": T_POPUP,
}
ALL_TYPES = (1 << 14) - 1
DEFAULT_TYPES = ALL_TYPES & ~(T_DOC | T_POPUP)

_TWO_PART_SUFFIX = frozenset((
    "co.uk org.uk ac.uk gov.uk me.uk com.au net.au org.au edu.au gov.au co.nz org.nz co.jp ne.jp or.jp co.in net.in org.in "
    "firm.in gen.in ind.in com.br net.br org.br com.cn net.cn org.cn gov.cn com.hk com.tw com.sg com.my com.mx com.ar com.tr "
    "co.za co.kr co.il com.ua com.ru github.io gitlab.io pages.dev vercel.app netlify.app herokuapp.com blogspot.com "
    "appspot.com web.app firebaseapp.com cloudfront.net azurewebsites.net").split())
_TOKEN = re.compile(r"[a-z0-9]+")
_URL = re.compile(r"^([a-z][a-z0-9+.-]*):(?://([^/?#]*))?", re.I)
_SEP = "[^A-Za-z0-9_.%-]"


def registrable(host):
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in _TWO_PART_SUFFIX:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def split_url(url):
    """-> (scheme, hostname) lower-cased; hostname has no port / userinfo."""
    m = _URL.match(url)
    if not m:
        return "", ""
    auth = m.group(2) or ""
    host = auth.rsplit("@", 1)[-1]
    if host.startswith("["):
        host = host.split("]", 1)[0] + "]"
    else:
        host = host.split(":", 1)[0]
    return m.group(1).lower(), host.lower().rstrip(".")


def _host_match(host, dom):
    return host == dom or (host.endswith(dom) and host[-len(dom) - 1] == ".")


def _dom_list_match(host, doms):
    for d in doms:
        if d.endswith(".*"):                            # entity: google.*  ->  google.com, google.co.uk, www.google.de
            base = d[:-2]
            labels = host.split(".")
            for i in range(len(labels) - 1):
                if ".".join(labels[i:i + 1 + base.count(".")]) == base and i + base.count(".") + 1 < len(labels):
                    return True
        elif _host_match(host, d):
            return True
    return False


# ---------------------------------------------------------------------------------------------------------------------
class Rule:
    """One compiled network filter."""
    __slots__ = ("pat", "kind", "anchor_end", "types", "third", "inc", "exc", "deny", "important", "redirect", "match_case",
                 "param", "special", "_rx", "raw")

    # kind: 0 regex-from-pattern, 1 plain substring, 2 host rule (||host^), 3 user regex, 4 match-everything
    def __init__(self, t):
        (self.pat, self.kind, self.anchor_end, self.types, self.third, self.inc, self.exc, self.deny, self.important,
         self.redirect, self.match_case, self.param, self.special, self.raw) = t
        self._rx = None

    def pack(self):
        return (self.pat, self.kind, self.anchor_end, self.types, self.third, self.inc, self.exc, self.deny, self.important,
                self.redirect, self.match_case, self.param, self.special, self.raw)

    def _regex(self):
        if self._rx is None:
            self._rx = _compile(self.pat, self.kind, self.anchor_end, self.match_case)
        return self._rx

    def applies(self, tmask, third, host, shost):
        """The option checks (everything except the URL pattern itself)."""
        if not (self.types & tmask):
            return False
        if self.third is not None and self.third != third:
            return False
        if self.inc and not (shost and _dom_list_match(shost, self.inc)):
            return False
        if self.exc and shost and _dom_list_match(shost, self.exc):
            return False
        if self.deny and _dom_list_match(host, self.deny):
            return False
        return True

    def matches_url(self, url, url_l, host):
        k = self.kind
        s = url if self.match_case else url_l
        if k == 4:
            return True
        if k == 1:
            return self.pat in s if not self.anchor_end else s.endswith(self.pat)
        if k == 2:
            return _host_match(host, self.pat)
        rx = self._rx or self._regex()
        return bool(rx and rx.search(s))


def _compile(pat, kind, anchor_end, match_case):
    flags = 0 if match_case else re.I
    try:
        if kind == 3:
            return re.compile(pat, flags)
        out = []
        i, n = 0, len(pat)
        # leading anchors are encoded in the pattern prefix by the parser: "\x01" = ||, "\x02" = |
        if pat.startswith("\x01"):
            out.append(r"^[a-z][a-z0-9+.-]*://(?:[^/?#]*[.@])?")
            i = 1
        elif pat.startswith("\x02"):
            out.append("^")
            i = 1
        while i < n:
            c = pat[i]
            if c == "*":
                out.append(".*")
            elif c == "^":
                out.append("(?:" + _SEP + "|$)")
            else:
                out.append(re.escape(c))
            i += 1
        if anchor_end:
            out.append("$")
        return re.compile("".join(out), flags)
    except re.error:
        return None


def _pattern_tokens(pat, anchored_left, anchor_end):
    """Alphanumeric runs of `pat` that are delimited on both sides (so each must be a whole token of any URL it matches)."""
    out = []
    body = pat.lstrip("\x01\x02")
    for m in _TOKEN.finditer(body.lower()):
        s, e = m.span()
        if (s == 0 and not anchored_left) or (s > 0 and body[s - 1] == "*"):
            continue
        if (e == len(body) and not anchor_end) or (e < len(body) and body[e] == "*"):
            continue
        out.append(m.group())
    return out


def _plain_tokens(p, anchor_end):
    return [m.group() for m in _TOKEN.finditer(p) if m.start() > 0 and (m.end() < len(p) or anchor_end)]


_OPTS_TAIL = re.compile(r"~?[a-z0-9_-]+(?:=[^,]*)?(?:,~?[a-z0-9_-]+(?:=[^,]*)?)*", re.I)
_HOST_PAT = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\^")


def parse_network(line):
    """-> (is_exception, rule_tuple) or None when the line is not a (supported) network filter."""
    exception = False
    if line.startswith("@@"):
        exception, line = True, line[2:]
    pat, opts = line, ""
    i = line.rfind("$")
    if i >= 0 and _OPTS_TAIL.fullmatch(line[i + 1:]):
        pat, opts = line[:i], line[i + 1:]
    types = neg_types = 0
    third = None
    inc, exc, deny = [], [], []
    important = match_case = False
    redirect = param = special = None
    for o in (opts.split(",") if opts else ()):
        neg = o.startswith("~")
        name, _, val = (o[1:] if neg else o).partition("=")
        name = name.lower()
        if name in ("third-party", "3p"):
            third = not neg
        elif name in ("first-party", "1p"):
            third = neg
        elif name in ("domain", "from"):
            for d in val.lower().split("|"):
                if d.startswith("~"):
                    exc.append(d[1:])
                elif d:
                    inc.append(d)
        elif name == "denyallow":
            deny.extend(d for d in val.lower().split("|") if d)
        elif name == "important":
            important = True
        elif name == "match-case":
            match_case = True
        elif name == "badfilter":
            special = "badfilter"
        elif name in ("redirect", "redirect-rule"):
            redirect = (name == "redirect-rule", val or "noopjs")
        elif name == "empty":
            redirect = (False, "empty")
        elif name == "removeparam":
            if not val or val.startswith(("/", "~")) or neg:
                return None                               # regex / inverted removeparam: not supported
            param = val
        elif name in ("generichide", "ghide"):
            special = "generichide"
        elif name in ("elemhide", "ehide"):
            special = "elemhide"
        elif name in ("specifichide", "shide"):
            special = "specifichide"
        elif name == "all":
            types = ALL_TYPES
        elif name in _TYPE_NAMES:
            if neg:
                neg_types |= _TYPE_NAMES[name]
            else:
                types |= _TYPE_NAMES[name]
        else:
            return None                                   # csp / replace / header / method / to ... : skip rather than guess
    if special in ("generichide", "elemhide", "specifichide"):
        types = T_DOC
    elif types == 0:
        types = (ALL_TYPES if neg_types else DEFAULT_TYPES) & ~neg_types
    else:
        types &= ~neg_types
    anchor_end = False
    p = pat
    if len(p) > 2 and p.startswith("/") and p.endswith("/"):
        kind, p = 3, p[1:-1]
        try:
            re.compile(p)
        except re.error:
            return None
    else:
        if p.endswith("|"):
            anchor_end, p = True, p[:-1]
        left = ""
        if p.startswith("||"):
            left, p = "\x01", p[2:]
        elif p.startswith("|"):
            left, p = "\x02", p[1:]
        if not match_case:
            p = p.lower()
        while p.startswith("*") and not left:
            p = p[1:]
        if left == "\x01" and not anchor_end and _HOST_PAT.fullmatch(p):
            kind, p, left = 2, p[:-1], ""                 # ||example.com^  : answered by a host lookup
        elif not left and "*" not in p and "^" not in p:
            kind = 1 if p else 4                          # plain substring (or "match everything" for option-only rules)
        else:
            kind = 0
        p = left + p
        if kind == 0 and p in ("\x01", "\x02") and not anchor_end:
            kind, p = 4, ""
    return exception, (p, kind, anchor_end, types, third, tuple(inc), tuple(exc), tuple(deny), important, redirect,
                       match_case, param, special, line)


class _Index:
    """Token-bucketed rules + a host dictionary for the very common `||host^` form + a by-page-domain dictionary for
    `$domain=` rules (so none of those is even looked at unless the page is on one of its domains)."""

    def __init__(self):
        self.hosts = {}                  # request host -> [Rule]
        self.tokens = {}                 # token -> [Rule]
        self.by_domain = {}              # page domain -> [Rule]
        self.misc = []                   # rules without a usable token
        self.count = 0
        self._pending = []               # (rule, [candidate tokens]) until build()

    def add(self, rule):
        self.count += 1
        if rule.kind == 2 and not rule.inc:
            self.hosts.setdefault(rule.pat, []).append(rule)
        elif rule.inc and not any(d.endswith(".*") for d in rule.inc):
            for d in rule.inc:
                self.by_domain.setdefault(d, []).append(rule)
        elif rule.kind in (2, 3, 4):
            self.misc.append(rule)
        else:
            left = rule.pat[:1] in ("\x01", "\x02")
            toks = _pattern_tokens(rule.pat, left, rule.anchor_end) if rule.kind == 0 else _plain_tokens(rule.pat, rule.anchor_end)
            self._pending.append((rule, toks))

    def build(self):
        """File each rule under its *rarest* token so buckets stay small."""
        freq = {}
        for _, toks in self._pending:
            for t in toks:
                freq[t] = freq.get(t, 0) + 1
        for rule, toks in self._pending:
            if toks:
                self.tokens.setdefault(min(toks, key=lambda t: (freq[t], -len(t))), []).append(rule)
            else:
                self.misc.append(rule)
        self._pending = []

    def candidates(self, url_l, host, shost):
        h = host
        while h:
            r = self.hosts.get(h)
            if r:
                yield from r
            i = h.find(".")
            if i < 0:
                break
            h = h[i + 1:]
        if self.by_domain and shost:
            h = shost
            while h:
                r = self.by_domain.get(h)
                if r:
                    yield from r
                i = h.find(".")
                if i < 0:
                    break
                h = h[i + 1:]
        tokens = self.tokens
        for tok in set(_TOKEN.findall(url_l)):
            b = tokens.get(tok)
            if b:
                yield from b
        yield from self.misc

    def first_match(self, url, url_l, host, shost, third, tmask, want_important=False):
        found = None
        for r in self.candidates(url_l, host, shost):
            if r.applies(tmask, third, host, shost) and r.matches_url(url, url_l, host):
                if not want_important or r.important:
                    return r
                if found is None:
                    found = r
        return found


# ---------------------------------------------------------------------------------------------------------------------
_COSMETIC = re.compile(r"^([^/*|@\"!]*?)(#[@?$%]*#)(.+)$")
_PROCEDURAL = re.compile(r":(?:has-text|-abp-[a-z-]+|contains|xpath|matches-[a-z-]+|min-text-length|upward|nth-ancestor|remove|style|watch-attr|"
                         r"others|if|if-not|not\(\s*:)\b|\+js\(|^\^|\{", re.I)
_CLASS_ID = re.compile(r"^([.#])(-?[_a-zA-Z][\w-]*)(?![\w-])")


class Engine:
    """Same API as the native `null_adblock.Engine`."""

    def __init__(self):
        self.block, self.allow, self.rredirect, self.removeparams = _Index(), _Index(), [], []
        self.hide_rules = []            # (selector, include-domains, exclude-domains)
        self.generic_always = set()
        self.generic_ci = {}            # ".class" / "#id" -> [selector]
        self.host_hide, self.host_unhide, self.entity_hide, self.entity_unhide = {}, {}, [], []
        self.generic_unhide = set()
        self.hide_flags = _Index()      # generichide / elemhide exceptions (matched against the page url)
        self.doc_allow = _Index()       # @@...$document : disables everything on matching pages
        self.resources = {}             # redirect name -> data: url
        self._bad = []
        self._raw = []                  # parsed filters, used by serialize()

    # ------------------------------------------------------------------ building
    @staticmethod
    def from_lists(lists, debug=False):
        e = Engine()
        for text, fmt in lists:
            e._add_list(text, fmt)
        e._finish()
        return e

    def _add_list(self, text, fmt="standard"):
        lines = text.splitlines()
        if fmt == "hosts":
            for ln in lines:
                ln = ln.split("#", 1)[0].strip()
                if not ln:
                    continue
                parts = ln.split()
                host = parts[-1].lower()
                if host in ("localhost", "localhost.localdomain", "local", "broadcasthost", "0.0.0.0") or "." not in host:
                    continue
                self._raw.append(("n", False, (host, 2, False, DEFAULT_TYPES | T_DOC, None, (), (), (), False, None, False, None, None, "||" + host + "^")))
            return
        for ln in lines:
            ln = ln.strip()
            if not ln or ln[0] == "!" or ln.startswith("[Adblock") or ln.startswith("# "):
                continue
            m = _COSMETIC.match(ln) if "#" in ln else None
            if m:
                domains, op, sel = m.groups()
                if op in ("##", "#@#", "#?#") and not _PROCEDURAL.search(sel):
                    self._raw.append(("c", op == "#@#", domains, sel))
                continue
            r = parse_network(ln)
            if r is not None:
                self._raw.append(("n", r[0], r[1]))

    def _finish(self):
        bad = set()
        for item in self._raw:                              # `X$badfilter` switches off the rule `X` (compared option-by-option, so 3p == third-party)
            if item[0] == "n" and item[2][12] == "badfilter":
                bad.add((item[1], item[2][:12]))
        for item in self._raw:
            if item[0] == "c":
                self._add_cosmetic(item[1], item[2], item[3])
                continue
            _, exception, t = item
            if t[12] == "badfilter" or (exception, t[:12]) in bad:
                continue
            rule = Rule(t)
            if rule.special in ("generichide", "elemhide", "specifichide"):
                if exception:
                    self.hide_flags.add(rule)
            elif exception and (rule.types & T_DOC):
                self.doc_allow.add(rule)                    # @@||site^$document  /  $all : nothing is filtered on that page
            elif rule.param is not None:
                if not exception:
                    self.removeparams.append(rule)
            elif exception:
                self.allow.add(rule)
            elif rule.redirect and rule.redirect[0]:
                self.rredirect.append(rule)
            else:
                self.block.add(rule)
        for idx in (self.block, self.allow, self.hide_flags, self.doc_allow):
            idx.build()

    def _add_cosmetic(self, exception, domains, sel):
        inc, exc = [], []
        for d in domains.lower().split(","):
            d = d.strip()
            if not d:
                continue
            (exc if d.startswith("~") else inc).append(d.lstrip("~"))
        if exception:
            if not inc:
                self.generic_unhide.add(sel)
            for d in inc:
                if d.endswith(".*"):
                    self.entity_unhide.append((d, sel))
                else:
                    self.host_unhide.setdefault(d, set()).add(sel)
            return
        if not inc:
            if exc:
                self.hide_rules.append((sel, (), tuple(exc)))
                return
            m = _CLASS_ID.match(sel)
            if m:
                self.generic_ci.setdefault(m.group(1) + m.group(2), []).append(sel)
            else:
                self.generic_always.add(sel)
            return
        for d in inc:
            if d.endswith(".*"):
                self.entity_hide.append((d, sel, tuple(exc)))
            else:
                self.host_hide.setdefault(d, []).append((sel, tuple(exc)))

    # ------------------------------------------------------------------ resources
    def add_resources_json(self, text):
        n = 0
        for r in json.loads(text):
            kind = r.get("kind")
            mime = kind.get("mime") if isinstance(kind, dict) else None
            if not mime or mime.startswith("fn/") or not r.get("content"):
                continue
            url = f"data:{mime};base64,{r['content']}"
            for name in [r["name"]] + list(r.get("aliases") or []):
                self.resources[name] = url
            n += 1
        return n

    # ------------------------------------------------------------------ serialisation (marshal: primitives only)
    def serialize(self):
        payload = {"v": 1, "raw": self._raw}
        return marshal.dumps(payload)

    @staticmethod
    def from_serialized(data):
        d = marshal.loads(bytes(data))
        if d.get("v") != 1:
            raise ValueError("unknown cache format")
        e = Engine()
        e._raw = d["raw"]
        e._finish()
        return e

    # ------------------------------------------------------------------ network
    def check(self, url, source_url="", request_type="other"):
        """-> (blocked, redirect_data_url_or_None, rewritten_url_or_None)"""
        scheme, host = split_url(url)
        if not host:
            return (False, None, None)
        url_l = url.lower()
        sscheme, shost = split_url(source_url) if source_url else ("", "")
        third = (registrable(host) != registrable(shost)) if shost else True
        tmask = _TYPE_NAMES.get(request_type, T_OTHER)
        if scheme in ("ws", "wss"):
            tmask = T_WS
        if self.doc_allow.count and shost and self.doc_allow.first_match(source_url, source_url.lower(), shost, shost, False, T_DOC):
            return (False, None, None)
        block = self.block.first_match(url, url_l, host, shost, third, tmask, want_important=True)
        if block is not None and (block.important or self.allow.first_match(url, url_l, host, shost, third, tmask) is None):
            return (True, self._redirect_for(block, url, url_l, host, shost, third, tmask), None)
        if block is not None:
            return (False, None, None)
        rewritten = self._strip_params(url, url_l, host, shost, third, tmask) if self.removeparams and "?" in url else None
        return (False, None, rewritten)

    def _redirect_for(self, block, url, url_l, host, shost, third, tmask):
        if block.redirect and not block.redirect[0]:
            return self.resources.get(block.redirect[1])
        for r in self.rredirect:
            if r.applies(tmask, third, host, shost) and r.matches_url(url, url_l, host):
                res = self.resources.get(r.redirect[1])
                if res:
                    return res
        return None

    def _strip_params(self, url, url_l, host, shost, third, tmask):
        names = set()
        for r in self.removeparams:
            if r.applies(tmask, third, host, shost) and r.matches_url(url, url_l, host):
                names.add(r.param)
        if not names:
            return None
        base, _, rest = url.partition("?")
        frag = ""
        if "#" in rest:
            rest, _, frag = rest.partition("#")
            frag = "#" + frag
        keep = [p for p in rest.split("&") if unquote(p.split("=", 1)[0]) not in names]
        if len(keep) == len(rest.split("&")):
            return None
        return base + ("?" + "&".join(keep) if keep else "") + frag

    def csp(self, url, source_url, request_type):
        return None

    # ------------------------------------------------------------------ cosmetic
    def cosmetic(self, url):
        scheme, host = split_url(url)
        res = {"hide_selectors": [], "procedural_actions": [], "exceptions": [], "injected_script": "", "generichide": False}
        if not host or scheme not in ("http", "https"):
            return res
        url_l = url.lower()
        flag = self.hide_flags.first_match(url, url_l, host, host, False, T_DOC)
        if flag is not None and flag.special == "elemhide":
            res["generichide"] = True
            return res
        res["generichide"] = flag is not None and flag.special == "generichide"
        hide, unhide = set(), set(self.generic_unhide)
        h = host
        while h:
            for sel, exc in self.host_hide.get(h, ()):
                if not (exc and _dom_list_match(host, exc)):
                    hide.add(sel)
            unhide |= self.host_unhide.get(h, set())
            i = h.find(".")
            if i < 0:
                break
            h = h[i + 1:]
        for d, sel, exc in self.entity_hide:
            if _dom_list_match(host, (d,)) and not (exc and _dom_list_match(host, exc)):
                hide.add(sel)
        for d, sel in self.entity_unhide:
            if _dom_list_match(host, (d,)):
                unhide.add(sel)
        if not res["generichide"]:
            hide |= self.generic_always
            for sel, inc, exc in self.hide_rules:
                if not _dom_list_match(host, exc):
                    hide.add(sel)
        res["hide_selectors"] = sorted(hide - unhide)
        res["exceptions"] = sorted(unhide)
        return res

    def hidden_class_id_selectors(self, classes, ids, exceptions):
        exc = set(exceptions)
        out = []
        for c in classes:
            out.extend(s for s in self.generic_ci.get("." + c, ()) if s not in exc)
        for i in ids:
            out.extend(s for s in self.generic_ci.get("#" + i, ()) if s not in exc)
        return out

    def stats(self):
        return {"network_block": self.block.count, "network_allow": self.allow.count,
                "cosmetic_generic": len(self.generic_always) + sum(len(v) for v in self.generic_ci.values()),
                "cosmetic_specific": sum(len(v) for v in self.host_hide.values()) + len(self.entity_hide)}
