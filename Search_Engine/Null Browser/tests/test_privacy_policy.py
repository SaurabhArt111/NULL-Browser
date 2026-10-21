"""Scriptlet policy, media fast path and cookie party logic. Pure Python: no Qt needed.  Run: python -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from null_browser.privacy import cookies, media_hosts, sanitize


def run(text, video_safe=True):
    out, rep = sanitize.sanitize_lists([(text, "standard")], video_safe)
    return out[0][0], out[-1][0], rep


class SanitizeTests(unittest.TestCase):
    def test_duplicates_removed(self):
        a = "example.com##+js(set-constant, foo, true)\nexample.com##+js(set-constant, foo, true)\n"
        text, _, rep = run(a)
        self.assertEqual(text.count("+js("), 1)
        self.assertEqual(rep.duplicates, 1)

    def test_invasive_dropped_on_platform_only(self):
        rule = "{}##+js(nano-setTimeout-booster, .*, 1000)\n"
        text, _, rep = run(rule.format("youtube.com"))
        self.assertNotIn("nano-setTimeout-booster", text)
        self.assertEqual(rep.dropped, 1)
        text, _, rep = run(rule.format("example.org"))
        self.assertIn("nano-setTimeout-booster", text)
        self.assertEqual(rep.dropped, 0)

    def test_video_safe_off_keeps_platform_rules(self):
        text, _, rep = run("youtube.com##+js(nano-stb, .*, 1000)\n", video_safe=False)
        self.assertIn("nano-stb", text)
        self.assertEqual(rep.dropped, 0)

    def test_unscoped_response_wrapper_gets_scope_on_platform(self):
        text, _, rep = run("x.com##+js(json-prune-fetch-response, a.b)\n")
        self.assertIn("propsToMatch", text)
        self.assertIn("graphql", text)
        self.assertEqual(rep.scoped, 1)

    def test_scoped_response_wrapper_is_untouched(self):
        line = "x.com##+js(json-prune-fetch-response, a.b, , propsToMatch, url:/foo/)\n"
        text, _, rep = run(line)
        self.assertEqual(rep.scoped, 0)
        self.assertIn("url:/foo/", text)

    def test_json_prune_rules_are_merged(self):
        src = "example.com##+js(json-prune, a.b)\nexample.com##+js(json-prune, c.d)\nexample.com##+js(json-prune, a.b)\n"
        text, merged, rep = run(src)
        self.assertNotIn("json-prune", text)
        self.assertEqual(merged.count("json-prune"), 1)
        self.assertIn("a.b", merged)
        self.assertIn("c.d", merged)
        self.assertEqual((rep.merged_in, rep.merged_out), (2, 1))

    def test_network_and_cosmetic_rules_untouched(self):
        src = "||ads.example^$script\n##.ad-banner\n@@||ok.example^\n"
        text, _, _ = run(src)
        self.assertEqual(text, src.rstrip("\n") if text.endswith("\n") is False else src)

    def test_global_generichide_exception_is_expanded(self):
        text, _, rep = run("@@*$ghide,domain=a.com|b.com|~www.a.com\n")
        self.assertIn("@@||a.com^$generichide", text)
        self.assertIn("@@||b.com^$generichide", text)
        self.assertNotIn("www.a.com", text)
        self.assertNotIn("@@*$", text)
        self.assertEqual(rep.expanded, 1)

    def test_non_standard_lists_pass_through(self):
        out, _ = sanitize.sanitize_lists([("0.0.0.0 ads.example\n", "hosts")])
        self.assertEqual(out[0], ("0.0.0.0 ads.example\n", "hosts"))

    def test_bundled_lists_shrink(self):
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "null_browser", "data", "filters")
        lists = []
        for n in sorted(os.listdir(root)):
            p = os.path.join(root, n)
            if os.path.isfile(p) and n.endswith(".txt"):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    lists.append((fh.read(), "standard"))
        if not lists:
            self.skipTest("no bundled lists")
        _, rep = sanitize.sanitize_lists(lists)
        self.assertGreater(rep.seen, 0)
        self.assertGreater(rep.dropped + rep.duplicates + rep.merged_in - rep.merged_out, 0)


class MediaHostTests(unittest.TestCase):
    def test_hosts(self):
        for h in ("rr1---sn-abc.googlevideo.com", "video.twimg.com", "v.redd.it", "scontent.xx.fbcdn.net", "x.cdninstagram.com"):
            self.assertTrue(media_hosts.is_media_host(h), h)
        for h in ("notgooglevideo.com", "youtube.com", "twimg.com", "example.com"):
            self.assertFalse(media_hosts.is_media_host(h), h)

    def test_scripts_and_frames_are_not_skipped(self):
        self.assertNotIn("script", media_hosts.SKIP_TYPES)
        self.assertNotIn("sub_frame", media_hosts.SKIP_TYPES)

    def test_paths(self):
        self.assertTrue(media_hosts.is_media_path("/a/b/seg_1.M4S"))
        self.assertTrue(media_hosts.is_media_path("/videoplayback"))
        self.assertFalse(media_hosts.is_media_path("/index.html"))


class CookiePartyTests(unittest.TestCase):
    def test_registrable(self):
        self.assertEqual(cookies.registrable("a.b.example.com"), "example.com")
        self.assertEqual(cookies.registrable("www.bbc.co.uk"), "bbc.co.uk")

    def test_same_party(self):
        self.assertTrue(cookies.same_party("www.example.com", "cdn.example.com"))
        self.assertTrue(cookies.same_party("www.youtube.com", "accounts.google.com"))
        self.assertFalse(cookies.same_party("example.com", "tracker.net"))
        self.assertFalse(cookies.same_party("", "example.com"))

    def test_policy_reads_attributes_and_memoises(self):
        calls = []

        class Perms:
            cache = {}
            def default(self, f): return "block_third"
            def effective(self, origin, f):
                calls.append(origin); return "block_third"

        class URL:
            def __init__(self, h): self.h = h
            def scheme(self): return "https"
            def host(self): return self.h

        class Req:
            def __init__(self, first, origin, third): self.firstPartyUrl, self.origin, self.thirdParty = URL(first), URL(origin), third

        pol = cookies.CookiePolicy(Perms())
        self.assertTrue(pol(Req("example.com", "example.com", False)))
        self.assertFalse(pol(Req("example.com", "tracker.net", True)))
        self.assertTrue(pol(Req("www.youtube.com", "accounts.google.com", True)))
        n = len(calls)
        pol(Req("example.com", "tracker.net", True))
        self.assertEqual(len(calls), n)                 # memoised
        pol.invalidate()
        pol(Req("example.com", "tracker.net", True))
        self.assertEqual(len(calls), n + 1)


if __name__ == "__main__":
    unittest.main()
