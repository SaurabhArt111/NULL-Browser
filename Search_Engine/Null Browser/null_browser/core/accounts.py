"""Browser-level Google account: who is signed in, and which cookies make up that sign-in.

Signing in happens on Google's own page, inside the browser's normal profile (so Google sites know you too, like Chrome). What
this module adds on top is *persistence that survives "Clear browsing data"*: the identity is kept in account.json, outside
the web profile, and the few cookies that carry the Google login are recognised here so that clearing cookies - by hand,
on exit, or "all time" - can leave exactly those alone. Nothing here talks to the network; no password is ever seen or stored.
"""
import json
import os
import re
import time

GOOGLE_HOST = re.compile(r"(^|\.)(google\.[a-z]{2,3}(\.[a-z]{2})?|youtube\.com|google\.com)$")
# names of the cookies that carry a Google sign-in, after dropping the __Secure- / __Host- and 1P / 3P parts
_AUTH_BASE = {"SID", "HSID", "SSID", "APISID", "SAPISID", "LSID", "OSID", "SIDTS", "SIDCC", "GAPS", "ACCOUNT_CHOOSER", "SMSV"}
SIGN_IN_URL = "https://accounts.google.com/ServiceLogin?hl=en&continue=https%3A%2F%2Fwww.google.com%2F&service=ahsid"
LIST_ACCOUNTS_URL = "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser&json=standard"


def is_auth_cookie(name, domain):
    """True for the cookies a Google sign-in is made of (not for tracking / preference cookies such as NID)."""
    d = (domain or "").lower().lstrip(".")
    if not GOOGLE_HOST.search(d):
        return False
    base = re.sub(r"^(__Secure-|__Host-)", "", name or "")
    base = re.sub(r"^[13]P", "", base)
    return base in _AUTH_BASE


def parse_list_accounts(text):
    """Pull the default signed-in account out of Google's ListAccounts reply. Returns {"email", "name", "picture"} or None.

    The reply is JSON like ["gaia.l.a.r",[["gaia.l.a",1,"Display Name","me@gmail.com","https://lh3.googleusercontent.com/...",1,...]]]
    (older replies wrap it in a script / pre block, so the first balanced array is located first)."""
    text = text or ""
    start = text.find("[")
    if start < 0:
        return None
    for end in range(len(text), start, -1):
        if text[end - 1] != "]":
            continue
        try:
            data = json.loads(text[start:end])
        except ValueError:
            continue
        break
    else:
        return None
    try:
        rows = data[1]
    except (TypeError, IndexError, KeyError):
        return None
    best = None
    for row in rows or []:
        if isinstance(row, list) and len(row) >= 4 and row[0] == "gaia.l.a" and isinstance(row[3], str) and "@" in row[3]:
            rec = {"email": row[3], "name": row[2] if isinstance(row[2], str) else "", "picture": row[4] if len(row) > 4 and isinstance(row[4], str) else ""}
            if len(row) > 5 and row[5] == 1:
                return rec                                  # flagged as the default account
            best = best or rec
    return best


class AccountStore:
    """account.json in the data folder (never part of the web profile, so clearing site data cannot touch it)."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "account.json")
        self.data = None
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("email"):
                self.data = d
        except (OSError, ValueError):
            pass

    def signed_in(self):
        return self.data is not None

    def set(self, email, name="", picture=""):
        self.data = {"email": email, "name": name or email.split("@")[0], "picture": picture, "since": (self.data or {}).get("since") or time.time()}
        self._write()

    def clear(self):
        self.data = None
        try:
            os.remove(self.path)
        except OSError:
            pass

    def public(self):
        d = self.data
        if not d:
            return {"signed_in": False}
        return {"signed_in": True, "email": d["email"], "name": d.get("name", ""), "picture": d.get("picture", ""), "since": d.get("since", 0)}

    def _write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)
