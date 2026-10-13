"""Instant answers computed locally (no network, no eval): calculator, unit conversion, time, random, color, hashes."""
from __future__ import annotations

import ast
import base64
import colorsys
import datetime as dt
import hashlib
import math
import operator
import random
import re
import secrets
import uuid
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------------------------------------------------------------------------------- calculator
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
          "log": math.log10, "ln": math.log, "log2": math.log2, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
          "exp": math.exp, "fact": math.factorial}
_CONST = {"pi": math.pi, "e": math.e, "tau": math.tau}
_MATH_Q = re.compile(r"^[\d\s+\-*/^%().,a-z]+$")


class _Bad(Exception):
    pass


def _ev(n, depth=0):
    if depth > 40:
        raise _Bad
    if isinstance(n, ast.Expression):
        return _ev(n.body, depth + 1)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _ev(n.left, depth + 1), _ev(n.right, depth + 1)
        if isinstance(n.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e6 and abs(b) > 50):
            raise _Bad
        return _BIN[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
        return _UN[type(n.op)](_ev(n.operand, depth + 1))
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords and len(n.args) <= 2:
        args = [_ev(a, depth + 1) for a in n.args]
        if n.func.id == "fact" and (not isinstance(args[0], int) or args[0] > 500):
            raise _Bad
        return _FUNCS[n.func.id](*args)
    raise _Bad


def fmt_number(x) -> str:
    if isinstance(x, float):
        if x != x or x in (math.inf, -math.inf):
            return str(x)
        if x == int(x) and abs(x) < 1e15:
            return f"{int(x):,}"
        s = f"{x:,.10g}"
        return s
    return f"{x:,}"


def calc(query: str) -> Optional[Dict]:
    q = query.strip().lower()
    q = re.sub(r"^(calc(ulate)?|what is|what's|=)\s*", "", q).rstrip("= ?")
    if not q or not _MATH_Q.match(q) or not re.search(r"\d", q):
        return None
    if re.fullmatch(r"[\d\s.,]+", q) or not re.search(r"[+\-*/^%(]|[a-z]{2,}", q):
        return None                                                  # bare numbers / years
    expr = q.replace("^", "**").replace(",", "")
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"\1*0.01*", expr)
    try:
        val = _ev(ast.parse(expr, mode="eval"))
    except (_Bad, SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError, RecursionError, MemoryError):
        return None
    if isinstance(val, complex):
        return None
    return {"type": "calc", "title": "Calculator", "expr": query.strip().rstrip("=?"), "value": fmt_number(val)}


# ---------------------------------------------------------------------------------- units
_UNITS = {  # name -> (category, factor to base)
    "mm": ("len", 0.001), "cm": ("len", 0.01), "m": ("len", 1), "km": ("len", 1000), "in": ("len", 0.0254), "inch": ("len", 0.0254), "inches": ("len", 0.0254),
    "ft": ("len", 0.3048), "foot": ("len", 0.3048), "feet": ("len", 0.3048), "yd": ("len", 0.9144), "mi": ("len", 1609.344), "mile": ("len", 1609.344), "miles": ("len", 1609.344),
    "meter": ("len", 1), "meters": ("len", 1), "metre": ("len", 1), "metres": ("len", 1), "kilometer": ("len", 1000), "kilometers": ("len", 1000), "km/h": None,
    "mg": ("mass", 1e-6), "g": ("mass", 0.001), "kg": ("mass", 1), "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237), "pound": ("mass", 0.45359237),
    "pounds": ("mass", 0.45359237), "oz": ("mass", 0.028349523125), "ounce": ("mass", 0.028349523125), "ounces": ("mass", 0.028349523125), "t": ("mass", 1000), "gram": ("mass", 0.001), "grams": ("mass", 0.001),
    "ml": ("vol", 0.001), "l": ("vol", 1), "liter": ("vol", 1), "liters": ("vol", 1), "litre": ("vol", 1), "litres": ("vol", 1), "gal": ("vol", 3.785411784), "gallon": ("vol", 3.785411784),
    "gallons": ("vol", 3.785411784), "cup": ("vol", 0.2365882365), "cups": ("vol", 0.2365882365), "tbsp": ("vol", 0.01478676478), "tsp": ("vol", 0.00492892159),
    "s": ("time", 1), "sec": ("time", 1), "min": ("time", 60), "h": ("time", 3600), "hr": ("time", 3600), "hour": ("time", 3600), "hours": ("time", 3600),
    "day": ("time", 86400), "days": ("time", 86400), "week": ("time", 604800), "weeks": ("time", 604800),
    "b": ("data", 1), "kb": ("data", 1e3), "mb": ("data", 1e6), "gb": ("data", 1e9), "tb": ("data", 1e12), "kib": ("data", 1024), "mib": ("data", 1024 ** 2), "gib": ("data", 1024 ** 3),
    "m/s": ("speed", 1), "kph": ("speed", 1 / 3.6), "mph": ("speed", 0.44704), "knot": ("speed", 0.514444), "knots": ("speed", 0.514444),
    "c": ("temp", None), "f": ("temp", None), "k": ("temp", None), "celsius": ("temp", None), "fahrenheit": ("temp", None), "kelvin": ("temp", None),
}
_UNITS = {k: v for k, v in _UNITS.items() if v}
_UNITS["km/h"] = ("speed", 1 / 3.6)
_UNIT_Q = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*°?\s*([a-z/]+)\s+(?:to|in|into|as)\s+°?\s*([a-z/]+)$")


def _temp(v: float, a: str, b: str) -> float:
    a, b = a[0], b[0]
    c = v if a == "c" else (v - 32) * 5 / 9 if a == "f" else v - 273.15
    return c if b == "c" else c * 9 / 5 + 32 if b == "f" else c + 273.15


def units(query: str) -> Optional[Dict]:
    m = _UNIT_Q.match(query.strip().lower().replace("convert ", ""))
    if not m:
        return None
    v, a, b = float(m.group(1).replace(",", ".")), m.group(2), m.group(3)
    ua, ub = _UNITS.get(a), _UNITS.get(b)
    if not ua or not ub or ua[0] != ub[0]:
        return None
    out = _temp(v, a, b) if ua[0] == "temp" else v * ua[1] / ub[1]
    return {"type": "units", "title": "Unit conversion", "expr": f"{fmt_number(v)} {a}", "value": f"{fmt_number(round(out, 6))} {b}"}


# ---------------------------------------------------------------------------------- time
_CITIES = {"london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin", "madrid": "Europe/Madrid", "rome": "Europe/Rome", "moscow": "Europe/Moscow",
           "istanbul": "Europe/Istanbul", "dubai": "Asia/Dubai", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "india": "Asia/Kolkata", "kolkata": "Asia/Kolkata",
           "bangalore": "Asia/Kolkata", "karachi": "Asia/Karachi", "dhaka": "Asia/Dhaka", "bangkok": "Asia/Bangkok", "singapore": "Asia/Singapore",
           "hong kong": "Asia/Hong_Kong", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "tokyo": "Asia/Tokyo", "seoul": "Asia/Seoul", "sydney": "Australia/Sydney",
           "melbourne": "Australia/Melbourne", "auckland": "Pacific/Auckland", "new york": "America/New_York", "nyc": "America/New_York", "toronto": "America/Toronto",
           "chicago": "America/Chicago", "denver": "America/Denver", "los angeles": "America/Los_Angeles", "san francisco": "America/Los_Angeles", "la": "America/Los_Angeles",
           "seattle": "America/Los_Angeles", "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
           "cairo": "Africa/Cairo", "lagos": "Africa/Lagos", "nairobi": "Africa/Nairobi", "johannesburg": "Africa/Johannesburg", "utc": "UTC", "gmt": "UTC"}
_TIME_Q = re.compile(r"^(?:what(?:'s| is) the )?(?:current )?(time|date)(?: now| today)?(?: (?:in|at) ([a-z .]+))?\??$")


def time_answer(query: str, now: Optional[dt.datetime] = None) -> Optional[Dict]:
    m = _TIME_Q.match(query.strip().lower().replace("what time is it", "time"))
    if not m:
        return None
    kind, place = m.group(1), (m.group(2) or "").strip()
    tz = None
    if place:
        name = _CITIES.get(place)
        if not name:
            return None
        try:
            tz = ZoneInfo(name)
        except ZoneInfoNotFoundError:
            return None
    n = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz) if tz else (now or dt.datetime.now().astimezone())
    label = place.title() if place else (n.tzname() or "Local time")
    return {"type": "time", "title": f"{'Time' if kind == 'time' else 'Date'} in {label}" if place else ("Current time" if kind == "time" else "Today"),
            "value": n.strftime("%H:%M:%S") if kind == "time" else n.strftime("%A, %d %B %Y"),
            "detail": n.strftime("%A, %d %B %Y") if kind == "time" else n.strftime("%H:%M"), "expr": ""}


# ---------------------------------------------------------------------------------- random / generators
def generators(query: str) -> Optional[Dict]:
    q = query.strip().lower()
    if q in ("uuid", "guid", "generate uuid", "random uuid", "uuid generator"):
        return {"type": "gen", "title": "Random UUID (v4)", "value": str(uuid.uuid4()), "expr": ""}
    if q in ("password", "random password", "generate password", "password generator"):
        alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&*-_"
        return {"type": "gen", "title": "Random password (20 chars)", "value": "".join(secrets.choice(alphabet) for _ in range(20)), "expr": "",
                "detail": "Generated on your device and never sent anywhere."}
    if q in ("flip a coin", "coin flip", "toss a coin", "heads or tails"):
        return {"type": "gen", "title": "Coin flip", "value": secrets.choice(["Heads", "Tails"]), "expr": ""}
    m = re.fullmatch(r"(?:roll (?:a )?)?(\d*)d(\d{1,3})", q)
    if m and (q.startswith("roll") or m.group(1)):
        n, s = int(m.group(1) or 1), int(m.group(2))
        if 1 <= n <= 20 and 2 <= s <= 1000:
            rolls = [secrets.randbelow(s) + 1 for _ in range(n)]
            return {"type": "gen", "title": f"Roll {n}d{s}", "value": str(sum(rolls)), "detail": ", ".join(map(str, rolls)) if n > 1 else "", "expr": ""}
    m = re.fullmatch(r"random number(?: (?:between )?(-?\d+)\s*(?:-|to|and)\s*(-?\d+))?", q)
    if m:
        lo, hi = (int(m.group(1)), int(m.group(2))) if m.group(1) else (1, 100)
        if lo > hi:
            lo, hi = hi, lo
        return {"type": "gen", "title": f"Random number {lo}–{hi}", "value": str(random.SystemRandom().randint(lo, hi)), "expr": ""}
    return None


# ---------------------------------------------------------------------------------- color
def color(query: str) -> Optional[Dict]:
    q = query.strip().lower()
    m = None
    m = m or re.fullmatch(r"(?:colou?r\s+)?#([0-9a-f]{6}|[0-9a-f]{3})", q) or re.fullmatch(r"colou?r\s+([0-9a-f]{6}|[0-9a-f]{3})", q)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    else:
        m = re.fullmatch(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", q)
        if not m:
            return None
        r, g, b = (min(255, int(x)) for x in m.groups())
    hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {"type": "color", "title": "Color", "value": f"#{r:02x}{g:02x}{b:02x}".upper(), "swatch": f"#{r:02x}{g:02x}{b:02x}", "expr": "",
            "detail": f"rgb({r}, {g}, {b})  ·  hsl({round(hh * 360)}, {round(ss * 100)}%, {round(ll * 100)}%)"}


# ---------------------------------------------------------------------------------- hashes / base64
def encoders(query: str) -> Optional[Dict]:
    m = re.fullmatch(r"(md5|sha1|sha256|sha512)(?: hash)?(?: of)?\s+(.{1,500})", query.strip(), re.I | re.S)
    if m:
        algo, text = m.group(1).lower(), m.group(2)
        return {"type": "hash", "title": algo.upper(), "value": hashlib.new(algo, text.encode()).hexdigest(), "expr": text[:60], "mono": True}
    m = re.fullmatch(r"base64\s+(encode|decode)\s+(.{1,500})", query.strip(), re.I | re.S)
    if m:
        try:
            if m.group(1).lower() == "encode":
                val = base64.b64encode(m.group(2).encode()).decode()
            else:
                val = base64.b64decode(m.group(2).encode(), validate=True).decode("utf-8")
        except Exception:
            return None
        return {"type": "hash", "title": f"Base64 {m.group(1).lower()}", "value": val, "expr": "", "mono": True}
    return None


def instant_answer(query: str) -> Optional[Dict]:
    """First matching local answer, or None. Cheap enough to run on every search."""
    q = (query or "").strip()
    if not q or len(q) > 200:
        return None
    for fn in (generators, time_answer, units, color, encoders, calc):
        try:
            a = fn(q)
        except (ValueError, OverflowError, ZeroDivisionError):
            a = None
        if a:
            return a
    return None
