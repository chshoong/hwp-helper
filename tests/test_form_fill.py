import pytest

from hwpxkit.form import CellOp, FormError, ReplaceOp, RowsOp, parse_fill


def test_parse_fill_directives():
    ops = parse_fill(
        "<!-- 3월 보고서 -->\n"
        "@바꾸기 ‘26년 2월 => ‘26년 3월\n"
        "@행수 표3 | 5\n"
        "@칸 표2 | 가상 분야 | 금월 추진실적\n"
        "□ 데이터 결합 실험\n- 세부 내용\n\n"
        "@칸 표1 | #2 | #1\n12.5%\n"
        "@칸 표2 | 요청사항 | -\n-\n")
    assert ops[0] == ReplaceOp("‘26년 2월", "‘26년 3월", 2)
    assert ops[1] == RowsOp(3, 5, 3)
    assert ops[2] == CellOp(2, "가상 분야", "금월 추진실적", "□ 데이터 결합 실험\n- 세부 내용", 4)
    assert ops[3] == CellOp(1, 2, 1, "12.5%", 8)
    assert ops[4] == CellOp(2, "요청사항", None, "-", 10)


def test_text_before_first_directive_raises():
    with pytest.raises(FormError, match="1번째 줄"):
        parse_fill("그냥 글\n@칸 표1 | 1 | 1\nx")


@pytest.mark.parametrize("bad, msg", [
    ("@칸 3 | a | b", "표 번호"),
    ("@칸 표2 | a", "행"),
    ("@행수 표2 | 많이", "숫자"),
    ("@바꾸기 옛글자", "=>"),
    ("@없는지시 표1", "알 수 없는"),
])
def test_bad_directives(bad, msg):
    with pytest.raises(FormError, match=msg):
        parse_fill(bad)


from helpers import monthly_form
from hwpxkit.body import all_text, own_text
from hwpxkit.form import find_cell, fill_cell
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.validate import validate


@pytest.fixture
def form(blank):
    pkg = Package.open(blank)
    ids = monthly_form(pkg)
    return pkg, ids


def cell_paras(cell):
    return cell.tc.find(q("hp:subList")).findall(q("hp:p"))


def test_fill_keeps_bullet_styles_and_spacing(form):
    pkg, ids = form
    cell = find_cell(pkg, 2, "가상 분야", "금월")
    fill_cell(pkg, cell, "□ 결합 실험 수행\n- 1차 결과 정리\n- 지표 비교\n□ 품질 평가\n- 평가지표 적용")
    ps = cell_paras(find_cell(pkg, 2, "가상 분야", "금월"))
    texts = [own_text(p) for p in ps]
    assert texts == ["결합 실험 수행", "1차 결과 정리", "지표 비교", "", "품질 평가", "평가지표 적용"]
    assert [p.get("paraPrIDRef") for p in ps] == [ids["box_pp"], ids["dash_pp"], ids["dash_pp"], ids["blank_pp"],
                                                  ids["box_pp"], ids["dash_pp"]]
    assert ps[1].find(q("hp:run")).get("charPrIDRef") == ids["blue"]
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_empty_cell_borrows_styles_from_same_column(form):
    pkg, ids = form
    cell = find_cell(pkg, 2, "활용 서비스", "금월")
    fill_cell(pkg, cell, "□ 서비스 후보 정리\n- 후보 3건 도출")
    ps = cell_paras(find_cell(pkg, 2, "활용 서비스", "금월"))
    assert [p.get("paraPrIDRef") for p in ps] == [ids["box_pp"], ids["dash_pp"]]


def test_plain_value_cell(form):
    pkg, _ = form
    fill_cell(pkg, find_cell(pkg, 1, 2, 2), "25.0%")
    assert find_cell(pkg, 1, 2, 2).text == "25.0%"


def test_memo_moves_to_matching_text(form):
    pkg, _ = form
    cell = find_cell(pkg, 2, "가상 분야", "금월")
    warnings = fill_cell(pkg, cell, "□ 새 항목\n□ 원시 자료 변환\n- 분석 단위 변환 완료")
    ps = cell_paras(find_cell(pkg, 2, "가상 분야", "금월"))
    holder = next(p for p in ps if next(p.iter(q("hp:fieldBegin")), None) is not None)
    assert own_text(holder) == "원시 자료 변환"
    assert next(holder.iter(q("hp:fieldEnd"))).get("beginIDRef") == "2100334526"
    assert warnings == []


def test_memo_falls_back_to_first_line_with_warning(form):
    pkg, _ = form
    cell = find_cell(pkg, 2, "가상 분야", "금월")
    warnings = fill_cell(pkg, cell, "□ 완전히 새 내용")
    ps = cell_paras(find_cell(pkg, 2, "가상 분야", "금월"))
    assert next(ps[0].iter(q("hp:fieldBegin")), None) is not None
    assert any("메모" in w and "협력 기관" in w for w in warnings)


def test_empty_content_leaves_one_blank_paragraph(form):
    pkg, _ = form
    fill_cell(pkg, find_cell(pkg, 3, 1, 2), "")
    ps = cell_paras(find_cell(pkg, 3, 1, 2))
    assert len(ps) == 1 and own_text(ps[0]) == ""


def test_cell_rejects_tables_and_display_math(form):
    pkg, _ = form
    from hwpxkit.form import FormError
    with pytest.raises(FormError, match="칸 안"):
        fill_cell(pkg, find_cell(pkg, 1, 2, 4), "| a | b |\n| c | d |")


def test_inline_math_in_cell(form):
    pkg, _ = form
    fill_cell(pkg, find_cell(pkg, 1, 2, 4), "목표 $R^2 \\ge 0.9$")
    assert next(find_cell(pkg, 1, 2, 4).tc.iter(q("hp:equation")), None) is not None


def test_real_monthly_fill(private_dir, expected, tmp_path):
    pkg = Package.open(private_dir / "monthly.hwpx")
    row = expected["monthly_row"]
    cell = find_cell(pkg, 3, row, "금월")
    before = cell_paras(cell)
    box_pp = before[0].get("paraPrIDRef")
    fill_cell(pkg, cell, f"□ 데이터 결합 실험\n- 1차 결과 정리\n□ {expected['monthly_memo_item']}\n- 세부 내용 완료")
    ps = cell_paras(find_cell(pkg, 3, row, "금월"))
    assert ps[0].get("paraPrIDRef") == box_pp and own_text(ps[0]) == "데이터 결합 실험"
    assert next(ps[3].iter(q("hp:fieldBegin")), None) is not None
    assert [i for i in validate(pkg) if i.level == "error"] == []


from hwpxkit.form import fill, list_fields, replace_text, set_rows


def test_set_rows_grows_and_shrinks(form):
    pkg, _ = form
    set_rows(pkg, 3, 5)
    from hwpxkit.form import cells as all_cells
    t3 = [c for c in all_cells(pkg) if c.table == 3]
    assert max(c.row for c in t3) == 4
    assert find_cell(pkg, 3, 5, 2).text == ""
    set_rows(pkg, 3, 2)
    assert max(c.row for c in all_cells(pkg) if c.table == 3) == 1
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_set_rows_refuses_vertical_merge(blank):
    from helpers import append_to_body, table
    from hwpxkit.form import FormError
    pkg = Package.open(blank)
    append_to_body(pkg, table(3, 2, spans={(1, 0): (2, 1)}, skip={(2, 0)}))
    with pytest.raises(FormError, match="병합"):
        set_rows(pkg, 1, 4)


def test_replace_text(form):
    pkg, _ = form
    assert replace_text(pkg, "2025.03.12.(목)", "2026.04.06.(월)") == 1
    with pytest.raises(Exception, match="찾지 못했어요"):
        replace_text(pkg, "없는 글자", "x")


def test_fill_applies_ops_in_order_with_line_numbers(form):
    pkg, _ = form
    from hwpxkit.form import FormError, parse_fill
    ops = parse_fill("@바꾸기 (26. 03.) => (26. 04.)\n@바꾸기 (26. 02.) => (26. 03.)\n"
                     "@칸 표2 | 가상 분야 | 금월\n□ 3월 실적\n")
    fill(pkg, ops)
    assert find_cell(pkg, 2, 1, 2).text == "금월 추진실적(26. 03.)"
    assert find_cell(pkg, 2, 1, 3).text == "향후 계획사항(26. 04.)"
    with pytest.raises(FormError, match="1번째 줄"):
        fill(pkg, parse_fill("@칸 표2 | 없는 행 | 금월\nx"))


def test_list_fields(form):
    pkg, _ = form
    fields = list_fields(pkg)
    f = next(x for x in fields if x["label"].startswith("[표2] 가상 분야") and "금월" in x["label"])
    assert f["filled"] and f["address"].startswith("@칸 표2 | 가상 분야")



# --- 계획 4 최종 검토 반영 ---

def numbered_table(pkg):
    from helpers import append_to_body, table
    return append_to_body(pkg, table(4, 2, texts={(0, 0): "번호", (0, 1): "실적", (1, 0): "1", (2, 0): "2",
                                                  (3, 0): "3", (1, 1): "a", (2, 1): "b", (3, 1): "c"}))


def test_numeric_header_is_text_not_row_number(blank):
    from hwpxkit.form import find_cell
    pkg = Package.open(blank)
    numbered_table(pkg)
    assert find_cell(pkg, 1, "2", "실적").text == "b"
    assert parse_fill("@칸 표1 | 2 | 실적\nx")[0].row == "2"
    op = parse_fill("@칸 표1 | #2 | #1\nx")[0]
    assert (op.row, op.col) == (2, 1)
    assert find_cell(pkg, 1, 2, 1).text == "1"


def test_exact_header_wins_over_partial(blank):
    from helpers import append_to_body, table
    from hwpxkit.form import find_cell
    pkg = Package.open(blank)
    append_to_body(pkg, table(3, 2, texts={(0, 1): "금액", (1, 0): "연구", (2, 0): "연구비", (1, 1): "x", (2, 1): "y"}))
    assert find_cell(pkg, 1, "연구", "금액").text == "x"
    assert find_cell(pkg, 1, "연구비", "금액").text == "y"


def test_every_listed_address_round_trips(form, blank):
    from hwpxkit.form import find_cell
    pkg, _ = form
    numbered_table(pkg)
    for f in list_fields(pkg):
        op = parse_fill(f["address"] + "\nx")[0]
        cell = find_cell(pkg, op.table, op.row, op.col)
        assert (cell.table, cell.row + 1, cell.col + 1) == (f["table"], f["row"], f["col"]), f["address"]


def test_cell_with_nested_table_is_refused(blank):
    from helpers import append_to_body, table
    from hwpxkit.form import FormError, find_cell
    pkg = Package.open(blank)
    outer = append_to_body(pkg, table(2, 2, texts={(0, 1): "내용", (1, 0): "가"}))
    inner = table(1, 1, texts={(0, 0): "안쪽 표"})
    target = [tc for tc in outer.iter(q("hp:tc"))][3]
    target.find(q("hp:subList")).append(inner)
    with pytest.raises(FormError, match="표나 그림"):
        fill_cell(pkg, find_cell(pkg, 1, "가", "내용"), "새 글")


def test_set_rows_inserts_before_trailing_different_row(form):
    pkg, _ = form
    set_rows(pkg, 2, 6)
    from hwpxkit.form import cells as all_cells
    req = find_cell(pkg, 2, "요청사항", None)
    assert req.row == 5 and req.colspan == 2
    new = [c for c in all_cells(pkg) if c.table == 2 and c.row in (3, 4)]
    assert len(new) == 6 and all(c.text == "" for c in new if c.col > 0)
    set_rows(pkg, 2, 6)  # 그대로면 아무 일도 없음
    set_rows(pkg, 2, 4)
    assert find_cell(pkg, 2, "요청사항", None).row == 3
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_same_row_count_with_merged_last_row_is_noop(blank):
    from helpers import append_to_body, table
    pkg = Package.open(blank)
    append_to_body(pkg, table(3, 2, spans={(1, 0): (2, 1)}, skip={(2, 0)}))
    set_rows(pkg, 1, 3)


def test_replace_respects_number_boundaries_and_reports_count(blank):
    from helpers import append_to_body, para
    pkg = Package.open(blank)
    append_to_body(pkg, para("2월 실적과 12월 계획, 다시 2월"))
    warnings = fill(pkg, parse_fill("@바꾸기 2월 => 3월\n"))
    from hwpxkit.body import own_text
    texts = [own_text(p) for p in pkg.xml("Contents/section0.xml") if p.tag == q("hp:p")]
    assert "3월 실적과 12월 계획, 다시 3월" in texts
    assert any("2곳" in w for w in warnings)


def test_bom_in_directive_file(blank, tmp_path):
    pkg = Package.open(blank)
    monthly_form(pkg)
    assert parse_fill("\ufeff@바꾸기 2025 => 2026\n")[0].old == "2025"


def test_multi_section_tables_are_found(blank):
    from helpers import add_section, table
    from hwpxkit.form import cells as all_cells, find_cell
    pkg = Package.open(blank)
    monthly_form(pkg)
    add_section(pkg, table(2, 2, texts={(0, 1): "둘째 구역", (1, 0): "행", (1, 1): "값"}))
    assert max(c.table for c in all_cells(pkg)) == 4
    fill_cell(pkg, find_cell(pkg, 4, "행", "둘째"), "새 값")
    assert find_cell(pkg, 4, "행", "둘째").text == "새 값"
