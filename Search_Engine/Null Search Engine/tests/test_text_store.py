from Engine.text import parse_query, fts_expression, make_snippet, clean_query
from Engine.store import Store, Doc


def test_parse_operators():
    pq = parse_query('"hello world" foo -bar site:www.x.com intitle:baz filetype:PDF')
    assert pq.terms == ["foo"] and pq.phrases == [["hello", "world"]] and pq.exclude == ["bar"]
    assert pq.site == "x.com" and pq.intitle == ["baz"] and pq.filetype == "pdf"
    e = fts_expression(pq)
    assert 'NOT ("bar")' in e and '"hello world"' in e and 'title : "baz"' in e


def test_fts_injection_is_quoted():
    pq = parse_query('foo" OR "x NEAR(a b) AND * ) (')
    e = fts_expression(pq)
    s = Store(":memory:")
    s.upsert(Doc(url="https://a.com/", title="t", body="foo x"))
    s.search(pq)                                  # must not raise


def test_clean_query():
    assert clean_query("  a \n\t b\x00 ") == "a b"
    assert len(clean_query("x" * 1000)) == 300


def test_snippet_prefers_dense_window():
    text = "intro " * 80 + "the quick brown fox jumps over the lazy dog " + "tail " * 80
    segs = make_snippet(text, ["quick", "fox"], 120)
    assert any(b and t.lower() == "quick" for t, b in segs) and any(b and t.lower() == "fox" for t, b in segs)
    assert sum(len(t) for t, _ in segs) < 200


def _store():
    s = Store(":memory:")
    s.upsert(Doc(url="https://python.org/", title="Python Programming Language", description="official", body="Python is a programming language that lets you work quickly."))
    s.upsert(Doc(url="https://docs.python.org/3/tutorial", title="Tutorial", body="This tutorial introduces Python programming basics. Python python python."))
    s.upsert(Doc(url="https://cooking.example/pasta", title="Pasta recipe", body="Boil water, add salt, cook the pasta. No python here, only snakes of spaghetti."))
    s.upsert(Doc(url="https://other.example/report.pdf", title="Annual report", body="Finance numbers"))
    return s


def test_ranking_title_beats_body():
    hits, total = _store().search(parse_query("python programming"))
    assert total >= 2 and hits[0].host == "python.org"


def test_stemming_and_phrase_and_exclude():
    s = _store()
    assert s.search(parse_query("programs"))[1] >= 1                       # porter: programs ~ programming? (program)
    assert s.search(parse_query('"programming language"'))[0][0].host == "python.org"
    hits, _ = s.search(parse_query("python -pasta"))
    assert all(h.host != "cooking.example" for h in hits)


def test_site_filetype_and_browse():
    s = _store()
    hits, total = s.search(parse_query("site:python.org"))
    assert total == 2 and {h.host for h in hits} == {"python.org", "docs.python.org"}
    hits, total = s.search(parse_query("annual filetype:pdf"))
    assert total == 1 and hits[0].url.endswith(".pdf")
    assert s.search(parse_query("annual filetype:docx"))[1] == 0


def test_or_fallback_when_and_is_sparse():
    s = _store()
    hits, _ = s.search(parse_query("pasta quantum"))
    assert hits and hits[0].host == "cooking.example"


def test_upsert_states_delete_and_stats():
    s = _store()
    d = Doc(url="https://python.org/", title="Python Programming Language", description="official", body="Python is a programming language that lets you work quickly.")
    assert s.upsert(d) == "same"
    d.body += " More."
    assert s.upsert(d) == "updated"
    assert s.count() == 4
    assert s.delete_host("python.org") == 2 and s.count() == 2
    assert s.search(parse_query("tutorial"))[1] == 0                        # FTS rows removed with the page
    assert s.stats()["documents"] == 2
    assert s.clear() == 2 and s.count() == 0


def test_titles_like_escapes_wildcards():
    s = _store()
    assert s.titles_like("Pyth") == ["Python Programming Language"]
    assert s.titles_like("%%") == []
