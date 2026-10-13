import pytest
from Engine.answers import instant_answer, calc
from Engine.ranking import fuse
from Engine.providers.base import Result


@pytest.mark.parametrize("q,val", [("2+2", "4"), ("(3+4)*5", "35"), ("2^10", "1,024"), ("15% of 80", "12"), ("sqrt(16)", "4"), ("10/4", "2.5"), ("1,000*3", "3,000")])
def test_calc(q, val):
    assert instant_answer(q)["value"] == val


@pytest.mark.parametrize("q", ["2024", "hello", "__import__('os').system('id')", "2**99999999", "9**9**9", "1/0", "open('x')", "a+b", "(((((", "5 5"])
def test_calc_rejects(q):
    assert instant_answer(q) is None


def test_units_and_misc():
    assert instant_answer("10 km to miles")["value"].startswith("6.2137")
    assert instant_answer("100 c to f")["value"].startswith("212")
    assert instant_answer("5 kg in lb")["value"].startswith("11.02")
    assert instant_answer("1 kg to km") is None
    assert instant_answer("sha256 hello")["value"].startswith("2cf24dba")
    assert instant_answer("base64 encode hi")["value"] == "aGk="
    assert instant_answer("#fff")["value"] == "#FFFFFF"
    assert len(instant_answer("uuid")["value"]) == 36
    assert instant_answer("time in tokyo")["title"] == "Time in Tokyo"
    assert 1 <= int(instant_answer("roll d6")["value"]) <= 6


def R(url, rank, sn="", title="t"):
    return Result(title=title, url=url, snippet=sn, rank=rank)


def test_fusion_rewards_agreement_and_dedupes():
    lists = {"a": [R("https://x.com/1", 1), R("https://y.com/", 2)], "b": [R("http://www.y.com", 1, sn="longer snippet"), R("https://z.com/", 2)], "c": [R("https://y.com/#frag", 3)]}
    out = fuse(lists, {}, [], max_per_host=0)
    assert out[0].url.rstrip("/").endswith("y.com") and sorted(out[0].sources) == ["a", "b", "c"]
    assert out[0].snippet == "longer snippet" and len(out) == 3


def test_host_diversity_demotes_not_drops():
    lists = {"a": [R(f"https://big.com/{i}", i + 1) for i in range(5)] + [R("https://small.com/", 6)]}
    out = fuse(lists, {}, [], max_per_host=2, limit=0)
    hosts = [r.url.split("/")[2] for r in out]
    assert hosts[:3] == ["big.com", "big.com", "small.com"] and len(out) == 6


def test_local_boost():
    lists = {"local": [R("https://mine.com/", 1)], "a": [R("https://web.com/", 1)]}
    assert fuse(lists, {}, [], local_boost=1.6)[0].url == "https://mine.com/"
