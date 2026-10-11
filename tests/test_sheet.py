"""엑셀·CSV를 보고서 마크다운 표로 (table-from), 표 열 정렬."""
import zipfile
from pathlib import Path

import pytest

from helpers import LONG, SECTION, append_to_body, para
from hwpxkit.header import Header
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import render_into
from hwpxkit.samples import infer


def test_parse_aligns():
    from hwpxkit.mdparse import parse
    t = parse("| 가 | 나 | 다 |\n|:---|:---:|---:|\n| 1 | 2 | 3 |\n")[0]
    assert t.aligns == ["left", "center", "right"]
    assert parse("| 가 |\n|---|\n| 1 |\n")[0].aligns == []  # 콜론이 없으면 전과 같음


def _align_of(pkg, p):
    return Header(pkg).get("paraPr", p.get("paraPrIDRef")).find(q("hh:align")).get("horizontal")


def test_render_right_aligned_column(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), "| 구분 | 금액 |\n|---|---:|\n| 가 | 1,200 |\n| 나 | 30 |\n")
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    rows = tbl.findall(q("hp:tr"))
    body = [tc for tr in rows[1:] for tc in tr.findall(q("hp:tc"))]
    amount = [tc for tc in body if tc.find(q("hp:cellAddr")).get("colAddr") == "1"]
    label = [tc for tc in body if tc.find(q("hp:cellAddr")).get("colAddr") == "0"]
    assert all(_align_of(pkg, tc.find(q("hp:subList")).find(q("hp:p"))) == "RIGHT" for tc in amount)
    assert all(_align_of(pkg, tc.find(q("hp:subList")).find(q("hp:p"))) != "RIGHT" for tc in label)
    head = rows[0].findall(q("hp:tc"))[1].find(q("hp:subList")).find(q("hp:p"))
    assert _align_of(pkg, head) != "RIGHT"


def test_no_colon_table_unchanged(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), "| 구분 | 금액 |\n|---|---|\n| 가 | 1 |\n")
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    assert all(_align_of(pkg, p) != "RIGHT" for p in tbl.iter(q("hp:p")))
