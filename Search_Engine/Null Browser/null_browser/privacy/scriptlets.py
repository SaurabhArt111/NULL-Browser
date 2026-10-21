"""uBlock-style scriptlet injection (`example.com##+js(name, arg, ...)`) for the engines that cannot do it themselves.

Brave's adblock-rust (our `null_adblock` module) assembles scriptlets natively. The older `adblock` PyPI wheel and the built-in
Python engine cannot, and YouTube's ad blocking depends entirely on scriptlets (the ads are part of the player's own JSON, not
separate requests). So this module does the same job in Python and is shared by both:

    sc = Scriptlets()
    sc.add_rule(exception=False, domains="www.youtube.com", args="set, ytInitialPlayerResponse.adPlacements, undefined")
    sc.set_resources(json_text)                  # brave-resources.json
    js = sc.script_for("https://www.youtube.com/watch?v=...")

The output has the same shape as adblock-rust's: helper functions first (each once), then one `try { name(args) } catch {}` per rule.
Nothing here touches the network or the page; it only builds text.
"""
import base64
import json
import re

_FUNC_NAME = re.compile(r"^function\s+([^\(\)\{\}\s]+)\s*\(")
_TEMPLATE_ARG = [re.compile(r"\{\{%d\}\}" % i) for i in range(1, 10)]
_JS_MIME = ("application/javascript", "text/javascript")


# ------------------------------------------------------------------------------------------ argument parsing
def _next_unescaped(s, sep):
    """(index of the next unescaped `sep` or -1, whether escapes must be normalised)."""
    pos, transform = 0, False
    while pos < len(s):
        i = s.find(sep, pos)
        if i < 0:
            return -1, transform
        k = 0
        while k < i - pos and s[i - 1 - k] == "\\":
            k += 1
        if k % 2 == 0:
            return i, transform
        pos, transform = i + 1, True
    return -1, transform


def _normalize(arg, sep):
    out, esc = [], False
    for ch in arg:
        if ch == "\\":
            if esc:
                esc = False
                out.append("\\\\")
            else:
                esc = True
            continue
        if esc:
            if ch != sep:
                out.append("\\")
            esc = False
        out.append(ch)
    return "".join(out)


def parse_args(args):
    """Port of adblock-rust's `parse_scriptlet_args`: split the inside of `+js(...)`; None if malformed."""
    out = []
    s = args
    if not s.strip():
        return out
    while True:
        s = s.lstrip()
        if not s:
            break
        c = s[0]
        if c in "\"'`":
            s = s[1:]
            i, tr = _next_unescaped(s, c)
            if i < 0:
                return None
            arg, s = s[:i], s[i + 1:].lstrip()
            if s.startswith(","):
                s = s[1:]
            elif s:
                return None
        else:
            i, tr = _next_unescaped(s, ",")
            arg = (s if i < 0 else s[:i]).rstrip()
            s = "" if i < 0 else s[i + 1:]
        out.append(_normalize(arg, ",") if tr else arg)
    return out


def _quoted(arg):
    return json.dumps(arg, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


# ---------------------------------------------------------------------------------------------------- host matching
def _host_suffixes(host):
    while host:
        yield host
        i = host.find(".")
        if i < 0:
            return
        host = host[i + 1:]


def _entity_match(host, entities):
    """`example.*` matches example.com, www.example.co.uk ... (at most two labels after the name)."""
    if not entities:
        return False
    parts = host.split(".")
    for i in range(len(parts) - 1):
        for j in range(i + 1, len(parts)):
            if ".".join(parts[i:j]) in entities and len(parts) - j <= 2:
                return True
    return False


class Scriptlets:
    def __init__(self):
        self.raw = []                 # (exception, domains, args): primitives only, so engines can cache it with marshal
        self._by_host = {}            # host -> [rule]; rule = (args, excludes)
        self._entities = {}           # "example" -> [rule]
        self._exc = {}                # host -> set(args) ; "" in set = remove every scriptlet for that host
        self._exc_entities = {}
        self._res = {}                # name / alias -> resource dict (content already decoded)
        self._memo = {}

    # ---- building ------------------------------------------------------------------------------------
    @staticmethod
    def split_rule(line):
        """`hosts##+js(args)` / `hosts#@#+js(args)` -> (exception, hosts, args) or None."""
        for marker, exc in (("##+js(", False), ("#@#+js(", True)):
            i = line.find(marker)
            if i >= 0 and line.endswith(")"):
                return exc, line[:i], line[i + len(marker):-1]
        return None

    def add_lines(self, text):
        """Scan a filter list's text for scriptlet rules (cheap pre-filter first)."""
        if "+js(" not in text:
            return
        for ln in text.splitlines():
            if "+js(" in ln and ln[:1] != "!":
                r = self.split_rule(ln.strip())
                if r is not None:
                    self.raw.append(r)

    def add_rule(self, exception, domains, args):
        self.raw.append((bool(exception), domains, args))

    def finish(self):
        self._by_host, self._entities, self._exc, self._exc_entities, self._memo = {}, {}, {}, {}, {}
        for exception, domains, args in self.raw:
            inc, exc = [], []
            for d in (x.strip().lower() for x in domains.split(",")):
                if not d or d == "*" or d.startswith("/") or ">>" in d:
                    continue
                (exc if d[0] == "~" else inc).append(d.lstrip("~"))
            if exception:
                a = args.strip()
                for d in inc:
                    if d.endswith(".*"):
                        self._exc_entities.setdefault(d[:-2], set()).add(a)
                    else:
                        self._exc.setdefault(d, set()).add(a)
                continue
            if not inc:
                continue                                    # a scriptlet with no specific site is refused (as adblock-rust does)
            rule = (args, tuple(e for e in exc if not e.endswith(".*")))
            for d in inc:
                if d.endswith(".*"):
                    self._entities.setdefault(d[:-2], []).append(rule)
                else:
                    self._by_host.setdefault(d, []).append(rule)

    def set_resources(self, text):
        n = 0
        for r in json.loads(text):
            kind = r.get("kind")
            mime = kind.get("mime") if isinstance(kind, dict) else None
            if mime not in _JS_MIME or not r.get("content"):
                continue
            try:
                body = base64.b64decode(r["content"]).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                continue
            res = {"name": r["name"], "body": body, "deps": list(r.get("dependencies") or [])}
            for name in [r["name"]] + list(r.get("aliases") or []):
                self._res[name] = res
            n += 1
        self._memo = {}
        return n

    # ---- lookup --------------------------------------------------------------------------------------
    def script_for(self, url):
        host = _host_of(url)
        if not host or not self._by_host and not self._entities:
            return ""
        hit = self._memo.get(host)
        if hit is not None:
            return hit
        rules, seen = [], set()
        for h in _host_suffixes(host):
            for rule in self._by_host.get(h, ()):
                if rule[0] not in seen:
                    seen.add(rule[0])
                    rules.append(rule)
        parts = host.split(".")
        for i in range(len(parts) - 1):
            for j in range(i + 1, len(parts)):
                if len(parts) - j <= 2:
                    for rule in self._entities.get(".".join(parts[i:j]), ()):
                        if rule[0] not in seen:
                            seen.add(rule[0])
                            rules.append(rule)
        blocked_all, blocked = False, set()
        for h in _host_suffixes(host):
            e = self._exc.get(h)
            if e:
                blocked |= e
                blocked_all = blocked_all or "" in e
        for i in range(len(parts) - 1):
            for j in range(i + 1, len(parts)):
                if len(parts) - j <= 2:
                    e = self._exc_entities.get(".".join(parts[i:j]))
                    if e:
                        blocked |= e
                        blocked_all = blocked_all or "" in e
        out = ""
        if rules and not blocked_all:
            use = [a for a, excl in rules if a.strip() not in blocked and not any(host == x or host.endswith("." + x) for x in excl)]
            out = self._assemble(use)
        if len(self._memo) > 2000:
            self._memo.clear()
        self._memo[host] = out
        return out

    # ---- assembling ----------------------------------------------------------------------------------
    def _assemble(self, invocations):
        deps, calls = [], []
        for inv in invocations:
            try:
                call = self._one(inv, deps)
            except Exception:                              # noqa: BLE001 - a bad rule must never break the others
                call = None
            if call:
                calls.append("try {\n" + call + "\n} catch ( e ) { }\n")
        if not calls:
            return ""
        return "".join(d["body"] + "\n" for d in deps) + "".join(calls)

    def _add_dep(self, name, deps, depth=0):
        if depth > 20 or any(d["name"] == name for d in deps):
            return
        res = self._res.get(name)
        if res is None:
            return                                         # a missing helper only breaks the scriptlets that need it
        deps.append(res)
        for sub in res["deps"]:
            self._add_dep(sub, deps, depth + 1)

    def _one(self, inv, deps):
        parts = parse_args(inv)
        if not parts:
            return None
        name = parts[0] if parts[0].endswith(".js") else parts[0] + ".js"
        args = parts[1:]
        if len(args) == 1 and args[0].startswith("{") and args[0].endswith("}"):
            return None                                    # object-argument syntax is not supported (same as adblock-rust)
        res = self._res.get(name)
        if res is None:
            return None
        trial = list(deps)
        for d in res["deps"]:
            self._add_dep(d, trial)
        m = _FUNC_NAME.match(res["body"])
        if m:
            if not any(d["name"] == res["name"] for d in trial):
                trial.append(res)
            deps[:] = trial
            return "%s(%s)" % (m.group(1), ", ".join(_quoted(a) for a in args))
        body = res["body"]
        for i, a in enumerate(args[:len(_TEMPLATE_ARG)]):
            body = _TEMPLATE_ARG[i].sub(lambda _m, v=_quoted(a)[1:-1]: v, body, count=1)
        deps[:] = trial
        return body


def _host_of(url):
    i = url.find("://")
    if i < 0:
        return ""
    rest = url[i + 3:]
    for ch in "/?#":
        j = rest.find(ch)
        if j >= 0:
            rest = rest[:j]
    rest = rest.rsplit("@", 1)[-1]
    if rest.startswith("["):
        return ""
    return rest.split(":", 1)[0].lower().rstrip(".")
