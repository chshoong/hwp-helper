import pytest

from helpers import SECTION, report_template
from hwpxkit import bridge
from hwpxkit.body import own_text
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import RenderError, _merge_marks, render_into
from hwpxkit.samples import infer
from hwpxkit.validate import validate

TABLE = """# 제1장 서론

표: 활용 사례 {#tbl:cases widths=1,2,2}
| 기관 | 대상 | 단계 |
|---|---|---|
| 가상 기관 | 항목 가·나 | 실험 |
| ^^ | 항목 **다** | << |

[@tbl:cases]에 정리했다.
"""


@pytest.fixture
def tpl(blank):
    pkg = Package.open(blank)
    ids = report_template(pkg)
    return pkg, infer(pkg), ids


def tables(pkg):
    return list(pkg.xml(SECTION).iter(q("hp:tbl")))


def cells(tbl):
    return {(int(tc.find(q("hp:cellAddr")).get("rowAddr")), int(tc.find(q("hp:cellAddr")).get("colAddr"))): tc
            for tc in tbl.iter(q("hp:tc"))}


def test_merge_marks():
    spans, covered = _merge_marks([["a", "b", "c"], ["^^", "d", "<<"]])
    assert spans[(0, 0)] == (2, 1) and spans[(1, 1)] == (1, 2)
    assert covered == {(1, 0), (1, 2)}


def test_merge_mark_in_first_row_raises():
    with pytest.raises(RenderError, match="맨 윗줄"):
        _merge_marks([["^^", "a"]])
    with pytest.raises(RenderError, match="맨 왼쪽"):
        _merge_marks([["a"], ["<<"]])


def test_non_rectangular_merge_raises():
    with pytest.raises(RenderError, match="직사각형"):
        _merge_marks([["a", "<<"], ["^^", "b"]])


def test_table_built_from_sample(tpl):
    pkg, cat, ids = tpl
    render_into(pkg, cat, TABLE)
    (tbl,) = tables(pkg)
    assert (tbl.get("rowCnt"), tbl.get("colCnt")) == ("3", "3")
    sample = next(cat.table_para.iter(q("hp:tbl")))
    widths = [int(tc.find(q("hp:cellSz")).get("width")) for (r, c), tc in sorted(cells(tbl).items()) if r == 0]
    assert sum(widths) == int(sample.find(q("hp:sz")).get("width"))
    assert widths[1] > widths[0]
    c = cells(tbl)
    assert c[(1, 0)].find(q("hp:cellSpan")).get("rowSpan") == "2"
    assert c[(2, 1)].find(q("hp:cellSpan")).get("colSpan") == "2"
    assert c[(0, 0)].get("borderFillIDRef") == ids["border"]
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_caption_number_and_reference(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, TABLE)
    texts = [own_text(p) for p in pkg.xml(SECTION) if p.tag == q("hp:p")]
    assert "[표 1-1] 활용 사례" in texts
    assert "[표 1-1]에 정리했다." in texts


def test_numbers_restart_each_chapter(tpl):
    pkg, cat, _ = tpl
    md = "# 제1장 가\n\n표: 하나\n| a | b |\n| c | d |\n\n# 제2장 나\n\n표: 둘\n| a | b |\n| c | d |\n\n표: 셋\n| a | b |\n| c | d |\n"
    render_into(pkg, cat, md)
    texts = [own_text(p) for p in pkg.xml(SECTION) if p.tag == q("hp:p")]
    assert {"[표 1-1] 하나", "[표 2-1] 둘", "[표 2-2] 셋"} <= set(texts)


def test_cloned_tables_get_unique_ids(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, "| a | b |\n| c | d |\n\n| e | f |\n| g | h |\n")
    ids = [t.get("id") for t in tables(pkg)]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_widths_count_mismatch_raises(tpl):
    pkg, cat, _ = tpl
    with pytest.raises(RenderError, match="열"):
        render_into(pkg, cat, "표: x {widths=1,2}\n| a | b | c |\n| d | e | f |\n")


def test_cell_line_breaks(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, "| 머리 | 둘 |\n| 첫 줄<br>둘째 줄 | x |\n")
    tc = cells(tables(pkg)[0])[(1, 0)]
    assert [own_text(p) for p in tc.iter(q("hp:p"))] == ["첫 줄", "둘째 줄"]


def test_fallback_table_without_sample(blank):
    pkg = Package.open(blank)
    report_template(pkg)
    cat = infer(pkg)
    cat.table_para = None
    render_into(pkg, cat, "| a | b |\n| c | d |\n")
    (tbl,) = tables(pkg)
    assert tbl.get("colCnt") == "2"
    assert [i for i in validate(pkg) if i.level == "error"] == []


@pytest.mark.hangul
def test_tables_open_in_hangul(tpl, tmp_path):
    pkg, cat, _ = tpl
    render_into(pkg, cat, TABLE + "\n| x | y |\n| z | w |\n")
    cat.table_para = None
    render_into(pkg, cat, "| 기본 | 표 |\n| 실선 | 확인 |\n", mode="append")
    out = pkg.save(tmp_path / "tables.hwpx")
    assert bridge.check(out) >= 1
    bridge.page_images(out, tmp_path / "pages")


def test_body_cell_sample_skips_hyperlink_cells(blank):
    # 실제 최종보고서: 견본 표 둘째 행 첫 칸에 하이퍼링크(컨트롤 + 파란 밑줄 글자모양)가 있었음
    from lxml import etree
    from hwpxkit.header import Header
    pkg = Package.open(blank)
    report_template(pkg)
    link = Header(pkg).derive_charpr("0", color="#0000FF")
    cat = infer(pkg)
    tbl = next(cat.table_para.iter(q("hp:tbl")))
    first_body = tbl.findall(q("hp:tr"))[1].find(q("hp:tc"))
    p = first_body.find(f"{q('hp:subList')}/{q('hp:p')}")
    for r in list(p):
        p.remove(r)
    ctrl_run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": "0"})
    etree.SubElement(ctrl_run, q("hp:ctrl"))
    link_run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": link})
    etree.SubElement(link_run, q("hp:t")).text = "링크"
    render_into(pkg, cat, "| 머리 | 둘 |\n| 본문 | 칸 |\n")
    body_runs = [r for (row, _), tc in cells(tables(pkg)[0]).items() if row == 1 for r in tc.iter(q("hp:run"))]
    assert body_runs and all(r.get("charPrIDRef") != link for r in body_runs)


def test_inner_caption_sample_is_replaced_not_duplicated(blank):
    from helpers import add_inner_caption
    pkg = Package.open(blank)
    report_template(pkg)
    cat = infer(pkg)
    add_inner_caption(cat.table_para, "[표 9-9] 옛 표 제목")
    render_into(pkg, cat, "표: 새 제목\n| a | b |\n| c | d |\n\n| e | f |\n| g | h |\n")
    first, second = tables(pkg)
    from hwpxkit.body import all_text
    assert all_text(first.find(q("hp:caption"))) == "[표 1-1] 새 제목"
    assert second.find(q("hp:caption")) is None
    texts = [own_text(p) for p in pkg.xml(SECTION) if p.tag == q("hp:p")]
    assert "[표 1-1] 새 제목" not in texts
    assert "옛 표 제목" not in "".join(all_text(t) for t in tables(pkg))


def test_table_errors_name_the_line(tpl):
    pkg, cat, _ = tpl
    with pytest.raises(RenderError, match="3번째 줄"):
        render_into(pkg, cat, "본문 문장\n\n| ^^ | a |\n| b | c |\n")
