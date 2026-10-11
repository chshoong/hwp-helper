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


M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def make_xlsx(path, sheets, shared=(), numfmts=(), xfs=(0,)):
    """시험용 최소 xlsx. sheets = {이름: '<row>…</row> 문자열', …} (병합은 이름: (rows, ['A1:B1']))."""
    z = zipfile.ZipFile(path, "w")
    names = list(sheets)
    z.writestr("xl/workbook.xml", f'<workbook xmlns="{M}" xmlns:r="{R}"><sheets>' + "".join(
        f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + "</sheets></workbook>")
    z.writestr("xl/_rels/workbook.xml.rels",
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
                   f'<Relationship Id="rId{i + 1}" Type="x" Target="worksheets/sheet{i + 1}.xml"/>'
                   for i in range(len(names))) + "</Relationships>")
    z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{M}">' + "".join(
        f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
    z.writestr("xl/styles.xml", f'<styleSheet xmlns="{M}"><numFmts>' + "".join(
        f'<numFmt numFmtId="{i}" formatCode="{c}"/>' for i, c in numfmts) + "</numFmts><cellXfs>" + "".join(
        f'<xf numFmtId="{n}"/>' for n in xfs) + "</cellXfs></styleSheet>")
    for i, n in enumerate(names):
        body = sheets[n]
        rows, merges = (body if isinstance(body, tuple) else (body, []))
        mc = (f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges)
              + "</mergeCells>") if merges else ""
        z.writestr(f"xl/worksheets/sheet{i + 1}.xml", f'<worksheet xmlns="{M}"><sheetData>{rows}</sheetData>{mc}</worksheet>')
    z.close()
    return path


def row(r, *cells):
    return f'<row r="{r}">' + "".join(cells) + "</row>"


def s(ref, idx, style=0):
    return f'<c r="{ref}" t="s" s="{style}"><v>{idx}</v></c>'


def n(ref, value, style=0, formula=None):
    f = f"<f>{formula}</f>" if formula else ""
    v = f"<v>{value}</v>" if value is not None else ""
    return f'<c r="{ref}" s="{style}">{f}{v}</c>'


def test_xlsx_numbers_formats_and_align(tmp_path):
    from hwpxkit.sheet import table_from
    # 스타일 0 일반, 1 #,##0, 2 0.00%, 3 날짜(14), 4 사용자 '0.0'
    p = make_xlsx(tmp_path / "a.xlsx", {"실적": row(1, s("A1", 0), s("B1", 1), s("C1", 2), s("D1", 3), s("E1", 4))
                                        + row(2, s("A2", 5), n("B2", 1234567, 1), n("C2", 0.4567, 2), n("D2", 46295, 3), n("E2", 3.14159, 4))
                                        + row(3, s("A3", 6), n("B3", -89, 1), n("C3", 1, 2), n("D3", 46296, 3), n("E3", 12, 4))},
                  shared=["구분", "금액", "비율", "날짜", "값", "가", "나"], numfmts=[(164, "0.0")], xfs=(0, 3, 10, 14, 164))
    md, warnings = table_from(p, caption="실적 요약")
    lines = md.strip().splitlines()
    assert lines[0] == "표: 실적 요약"
    assert lines[1] == "| 구분 | 금액 | 비율 | 날짜 | 값 |"
    assert lines[2] == "|---|---:|---:|---|---:|"
    assert lines[3] == "| 가 | 1,234,567 | 45.67% | 2026. 9. 30. | 3.1 |"
    assert lines[4] == "| 나 | -89 | 100.00% | 2026. 10. 1. | 12.0 |"
    assert warnings == []


def test_general_numbers_use_column_decimals(tmp_path):
    from hwpxkit.sheet import table_from
    p = make_xlsx(tmp_path / "g.xlsx", {"S": row(1, s("A1", 0)) + row(2, n("A2", 1500)) + row(3, n("A3", 2.25))},
                  shared=["값"])
    md, _ = table_from(p)
    assert md.strip().splitlines()[2:] == ["| 1,500.00 |", "| 2.25 |"]


def test_merges_and_sheet_choice(tmp_path):
    from hwpxkit.sheet import SheetError, table_from
    rows = (row(1, s("A1", 0), s("B1", 1)) + row(2, s("A2", 2), n("B2", 1)) + row(3, n("B3", 2)),
            ["A2:A3"])
    p = make_xlsx(tmp_path / "m.xlsx", {"첫": row(1, s("A1", 0)), "둘": rows}, shared=["항목", "값", "묶음"])
    md, _ = table_from(p, sheet="둘")
    assert md.strip().splitlines()[2:] == ["| 묶음 | 1 |", "| ^^ | 2 |"]
    with pytest.raises(SheetError, match="첫, 둘"):
        table_from(p, sheet="셋")


def test_range_cuts_merge(tmp_path):
    from hwpxkit.sheet import table_from
    rows = (row(1, s("A1", 0), s("B1", 1)) + row(2, s("A2", 2), n("B2", 1)) + row(3, n("B3", 2)), ["A1:A3"])
    p = make_xlsx(tmp_path / "c.xlsx", {"S": rows}, shared=["항목", "값", "x"])
    md, warnings = table_from(p, rng="A2:B3")
    lines = md.strip().splitlines()
    assert "^^" not in lines[0] and lines[0].startswith("| ")
    assert warnings and "병합" in warnings[0]


def test_formula_without_value_warns(tmp_path):
    from hwpxkit.sheet import table_from
    p = make_xlsx(tmp_path / "f.xlsx", {"S": row(1, s("A1", 0)) + row(2, n("A2", None, formula="SUM(1,2)"))},
                  shared=["합"])
    md, warnings = table_from(p)
    assert md.strip().splitlines()[2] == "|  |"
    assert any("수식" in w for w in warnings)


def test_not_xlsx_and_old_xls(tmp_path):
    from hwpxkit.sheet import SheetError, table_from
    bad = tmp_path / "x.xlsx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(SheetError, match=".xlsx로 저장"):
        table_from(bad)
    old = tmp_path / "y.xls"
    old.write_bytes(b"x")
    with pytest.raises(SheetError, match=".xlsx로 저장"):
        table_from(old)


def test_csv_encodings_and_tsv(tmp_path):
    from hwpxkit.sheet import table_from
    (tmp_path / "u.csv").write_text("구분,금액\n가,1200\n나,30.5\n", encoding="utf-8-sig")
    (tmp_path / "k.csv").write_bytes("구분,금액\n가,1200\n".encode("cp949"))
    (tmp_path / "t.tsv").write_text("구분\t금액\n가\t7\n", encoding="utf-8")
    md, _ = table_from(tmp_path / "u.csv")
    assert md.strip().splitlines() == ["| 구분 | 금액 |", "|---|---:|", "| 가 | 1,200.0 |", "| 나 | 30.5 |"]
    assert table_from(tmp_path / "k.csv")[0].strip().splitlines()[2] == "| 가 | 1,200 |"
    assert table_from(tmp_path / "t.tsv")[0].strip().splitlines()[2] == "| 가 | 7 |"


def test_pipe_and_newline_escaped(tmp_path):
    from hwpxkit.mdparse import parse
    from hwpxkit.sheet import table_from
    (tmp_path / "p.csv").write_text('구분,설명\n가,"A|B\n둘째 줄"\n', encoding="utf-8")
    md, _ = table_from(tmp_path / "p.csv")
    t = parse(md)[0]
    assert t.rows[1] == ["가", "A｜B 둘째 줄"]


def test_wide_table_warns(tmp_path):
    from hwpxkit.sheet import table_from
    (tmp_path / "w.csv").write_text(",".join(f"c{i}" for i in range(13)) + "\n" + ",".join("1" * 13) + "\n", encoding="utf-8")
    assert any("열이 13개" in w for w in table_from(tmp_path / "w.csv")[1])
