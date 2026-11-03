import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from null_browser.core import accounts as A  # noqa: E402


class CookieRules(unittest.TestCase):
    def test_google_login_cookies_are_recognised(self):
        for name in ("SID", "HSID", "SSID", "APISID", "SAPISID", "LSID", "OSID", "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID",
                     "__Secure-3PAPISID", "__Secure-1PSIDTS", "__Secure-3PSIDCC", "__Host-GAPS", "__Host-1PLSID", "__Host-3PLSID", "ACCOUNT_CHOOSER"):
            self.assertTrue(A.is_auth_cookie(name, ".google.com"), name)
        self.assertTrue(A.is_auth_cookie("SID", "accounts.google.com"))
        self.assertTrue(A.is_auth_cookie("SAPISID", ".youtube.com"))
        self.assertTrue(A.is_auth_cookie("SID", ".google.co.in"))
        self.assertTrue(A.is_auth_cookie("SID", ".google.co.uk"))

    def test_tracking_and_foreign_cookies_are_not(self):
        for name, dom in (("NID", ".google.com"), ("1P_JAR", ".google.com"), ("AEC", ".google.com"), ("CONSENT", ".google.com"),
                          ("SID", ".example.com"), ("SID", ".notgoogle.com"), ("SID", "google.com.evil.example"), ("session", ".github.com"),
                          ("_ga", ".google.com"), ("SIDEBAR", ".google.com")):
            self.assertFalse(A.is_auth_cookie(name, dom), f"{name} {dom}")


class ListAccounts(unittest.TestCase):
    SAMPLE = json.dumps(["gaia.l.a.r", [["gaia.l.a", 1, "Dev User", "dev.user@gmail.com", "https://lh3.googleusercontent.com/a/abc=s48", 1, 1, 0, None, 1, "1234"]]])

    def test_default_account(self):
        r = A.parse_list_accounts(self.SAMPLE)
        self.assertEqual(r, {"email": "dev.user@gmail.com", "name": "Dev User", "picture": "https://lh3.googleusercontent.com/a/abc=s48"})

    def test_wrapped_in_html_and_picks_the_default_of_several(self):
        data = json.dumps(["gaia.l.a.r", [["gaia.l.a", 1, "Second", "b@x.com", "", 0, 1], ["gaia.l.a", 1, "First", "a@x.com", "", 1, 1]]])
        r = A.parse_list_accounts("<html><body><pre>" + data + "</pre></body></html>")
        self.assertEqual(r["email"], "a@x.com")

    def test_signed_out_and_garbage(self):
        self.assertIsNone(A.parse_list_accounts(json.dumps(["gaia.l.a.r", []])))
        for bad in ("", "<html>no json</html>", "[1,2", "null", '["gaia.l.a.r"]', '["gaia.l.a.r",[["other",1,"n","e@x.com"]]]'):
            self.assertIsNone(A.parse_list_accounts(bad), bad)


class Store(unittest.TestCase):
    def test_roundtrip_and_clear(self):
        d = tempfile.mkdtemp()
        s = A.AccountStore(d)
        self.assertFalse(s.signed_in())
        s.set("me@gmail.com", "Me", "https://x/y")
        s2 = A.AccountStore(d)
        self.assertTrue(s2.signed_in())
        self.assertEqual(s2.public()["email"], "me@gmail.com")
        s2.clear()
        self.assertFalse(A.AccountStore(d).signed_in())


if __name__ == "__main__":
    unittest.main()
