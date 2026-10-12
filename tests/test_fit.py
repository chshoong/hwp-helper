"""분량(쪽수·제한·배점)과 작성 요령 항목 (pages, guide)."""
import json

import pytest

from helpers import LONG, SECTION, append_to_body, para, table
from hwpxkit.package import Package


def test_find_limits():
    from hwpxkit.fit import find_limits
    found = find_limits(["분량: 본문 10쪽 이내 (표지 제외)", "A4 5매 내외로 작성", "제3장 이내 작성",
                         "15페이지 이하", "본문 10쪽 이내 (표지 제외)"])
    assert [(f["pages"], f["kind"]) for f in found] == [(10, "이내"), (5, "내외"), (15, "이하")]
    assert found[0]["text"] == "10쪽 이내"


def test_heading_score():
    from hwpxkit.fit import heading_score
    assert heading_score("제2장 데이터 분석〔30점〕") == 30
    assert heading_score("1. 개요 (15점)") == 15
    assert heading_score("결론 [5점]") == 5
    assert heading_score("배점 30점을 받는다") is None


def test_sections_from_pages():
    from hwpxkit.fit import sections_from_pages
    heads = [(1, "제1장 서론〔10점〕", 1), (3, "1.1 배경", 2), (5, "제2장 방법", 1)]
    out = sections_from_pages(heads, [1, 1, 1, 2, 2, 3, 3], 4)
    assert [(s["title"], s["start"], s["end"], s["count"]) for s in out] == [
        ("제1장 서론〔10점〕", 1, 2, 2), ("1.1 배경", 2, 2, 1), ("제2장 방법", 3, 4, 2)]
    assert out[0]["score"] == 10 and out[1]["score"] is None and out[1]["level"] == 2


def test_sections_same_page():
    from hwpxkit.fit import sections_from_pages
    out = sections_from_pages([(0, "제1장", 1), (2, "제2장", 1)], [3, 3, 3], 3)
    assert [(s["start"], s["end"]) for s in out] == [(3, 3), (3, 3)]


def _doc(blank, paras):
    pkg = Package.open(blank)
    for p in paras:
        append_to_body(pkg, para(p))
    return pkg


def test_measure_with_limit(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["※ 본문은 2쪽 이내로 작성", "제1장 서론〔10점〕", LONG, "제2장 방법〔30점〕", LONG])
    r = measure(pkg, [1, 1, 1, 1, 2, 3], 3)
    assert r["pages"] == 3 and r["limit"]["pages"] == 2 and len(r["limits"]) == 1
    assert [(s["title"], s["start"], s["end"]) for s in r["sections"]] == [("제1장 서론〔10점〕", 1, 1),
                                                                            ("제2장 방법〔30점〕", 2, 3)]
    assert measure(pkg, [1, 1, 1, 1, 2, 3], 3, limit=5)["limit"] == {"pages": 5, "kind": "이내", "text": "--limit"}


def test_measure_many_limits_none(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["본문 10쪽 이내", "요약 2쪽 이내", "제1장 서론", LONG])
    r = measure(pkg, [1, 1, 1, 1, 1], 1)
    assert r["limit"] is None and len(r["limits"]) == 2


def test_measure_mismatch_warns(blank):
    from hwpxkit.fit import measure
    pkg = _doc(blank, ["제1장 서론", LONG, "제2장 방법", LONG])
    r = measure(pkg, [1, 1, 1], 2)  # 한글이 문단 하나를 덜 셈
    assert r["warnings"] and r["sections"][0]["start"] == 1
