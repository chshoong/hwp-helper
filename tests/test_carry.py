"""매달 이어받기 (carry): 지난달 보고서 → 이번 달 fill 지시문 초안 + 확인할 것."""
import pytest

from helpers import SECTION, append_to_body, para, table
from hwpxkit.form import fill, parse_fill
from hwpxkit.package import Package


def monthly(blank, period="‘26년 9월", report="2026. 10. 5.(월)", months=("9월", "10월")):
    pkg = Package.open(blank)
    append_to_body(pkg, para(f"{period} 월간 보고"))
    append_to_body(pkg, para(f"보고일: {report}"))
    append_to_body(pkg, para("보고 기간: 2026. 9. 1. ~ 9. 30. (26. 09.)"))
    append_to_body(pkg, table(3, 3, texts={(0, 0): "과제", (0, 1): f"금월({months[0]}) 실적", (0, 2): f"차월({months[1]}) 계획",
                                            (1, 0): "과제 1", (1, 1): "자료 수집", (1, 2): ["모형 시험", "- 시범 자료 검증"],
                                            (2, 0): "과제 2", (2, 1): "보고서 초안", (2, 2): ""}))
    append_to_body(pkg, table(3, 2, texts={(0, 0): "구분", (0, 1): "값", (1, 0): "진행률", (1, 1): "45%",
                                            (2, 0): "누적 집행액", (2, 1): "1,200"}))
    append_to_body(pkg, para("9월 중 협의를 마쳤고 10월 초에 시험한다. 19월이라는 글이나 2025년 9월은 그대로."))
    return pkg


def replaces(spec):
    return [tuple(line[len("@바꾸기 "):].split(" => ")) for line in spec.splitlines() if line.startswith("@바꾸기 ")]


def test_period_and_replacements_order(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    assert r["from"] == (2026, 9) and r["to"] == (2026, 10)
    pairs = replaces(r["spec"])
    assert ("‘26년 9월", "‘26년 10월") in pairs
    assert ("2026. 9. 1. ~ 9. 30.", "2026. 10. 1. ~ 10. 31.") in pairs
    assert ("(26. 09.)", "(26. 10.)") in pairs
    assert ("10월) 계획", "11월) 계획") not in pairs  # 괄호 안 달은 달 머리 꼴이 아님
    olds = [o for o, _ in pairs]
    assert olds.index("10월 초") < olds.index("9월 중")  # 뒤 달 먼저


def test_isolated_month_not_replaced(blank):
    from hwpxkit.carry import carry
    olds = [o for o, _ in replaces(carry(monthly(blank))["spec"])]
    assert "9월" not in olds and not any("19월" in o or "2025년" in o for o in olds)


def test_report_date_suggestion(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    ask = next(a for a in r["ask"] if a["kind"] == "report-date")
    assert ask["current"] == "2026. 10. 5.(월)" and ask["suggest"] == "2026. 11. 5.(목)"
    assert not any("10. 5." in o for o, _ in replaces(r["spec"]))


def test_december_rolls_year(blank):
    from hwpxkit.carry import carry
    pkg = monthly(blank, period="‘26년 12월", report="2027. 1. 6.(수)")
    append_to_body(pkg, para("12월 실적과 1월 계획을 정리한다."))
    r = carry(pkg)
    assert r["to"] == (2027, 1)
    pairs = replaces(r["spec"])
    assert ("‘26년 12월", "‘27년 1월") in pairs
    olds = [o for o, _ in pairs]
    assert olds.index("1월 계획") < olds.index("12월 실적")
    assert ("1월 계획", "2월 계획") in pairs and ("12월 실적", "1월 실적") in pairs


def test_period_missing_needs_to(blank):
    from hwpxkit.carry import CarryError, carry
    pkg = Package.open(blank)
    append_to_body(pkg, para("기간 표시가 없는 문서"))
    with pytest.raises(CarryError, match="--to"):
        carry(pkg)
    assert carry(pkg, to=(2026, 10))["from"] == (2026, 9)


def test_plan_moves_to_actual(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    spec = r["spec"]
    assert "@칸 표1 | #2 | #2\n모형 시험\n- 시범 자료 검증\n" in spec
    assert "@칸 표1 | #2 | #3\n\n" in spec
    assert "@칸 표1 | #3 |" not in spec  # 계획이 빈 행은 건너뜀
    plans = [a for a in r["ask"] if a["kind"] == "next-plan"]
    assert len(plans) == 1 and "과제 1" in plans[0]["where"]


def test_numbers_asked_not_invented(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    nums = {a["current"]: a for a in r["ask"] if a["kind"] == "number"}
    assert set(nums) == {"45%", "1,200"}
    assert nums["45%"]["address"] == "@칸 표2 | #2 | #2"
    assert "45%" not in r["spec"]


def test_ambiguous_plan_columns(blank):
    from hwpxkit.carry import carry
    pkg = Package.open(blank)
    append_to_body(pkg, para("‘26년 9월 월간 보고"))
    append_to_body(pkg, table(2, 4, texts={(0, 0): "과제", (0, 1): "금월 실적", (0, 2): "차월 계획", (0, 3): "익월 추진 계획",
                                            (1, 0): "가", (1, 1): "a", (1, 2): "b", (1, 3): "c"}))
    r = carry(pkg)
    assert "@칸" not in r["spec"] and any(a["kind"] == "plan-columns" for a in r["ask"])


def test_merged_or_object_cells_skipped(blank):
    from hwpxkit.carry import carry
    pkg = Package.open(blank)
    append_to_body(pkg, para("‘26년 9월 월간 보고"))
    append_to_body(pkg, table(3, 3, texts={(0, 0): "과제", (0, 1): "금월 실적", (0, 2): "차월 계획",
                                            (1, 0): "가", (1, 1): "a", (1, 2): "b"}, spans={(1, 2): (2, 1)}, skip={(2, 2)}))
    r = carry(pkg)
    assert "@칸" not in r["spec"]


def test_spec_applies_with_fill(blank, tmp_path):
    from hwpxkit.carry import carry
    from hwpxkit.form import cells
    pkg = monthly(blank)
    spec = carry(pkg)["spec"]
    fill(pkg, parse_fill(spec), base_dir=tmp_path)
    by = {(c.table, c.row_header, c.col_header): c.text for c in cells(pkg)}
    assert by[(1, "과제 1", "금월(9월) 실적")] == "모형 시험\n- 시범 자료 검증"
    assert by[(1, "과제 1", "차월(10월) 계획")] == ""
    assert by[(1, "과제 2", "금월(9월) 실적")] == "보고서 초안"
    texts = [t for t in (p.text or "" for p in pkg.xml(SECTION).iter()) if t]
    assert any("‘26년 10월" in t for t in texts) and any("2026. 10. 1. ~ 10. 31." in t for t in texts)


def test_cli_carry(blank, tmp_path, capsys):
    from hwpxkit.cli import main
    src = monthly(blank).save(tmp_path / "9월.hwpx")
    out = tmp_path / "초안.md"
    assert main(["carry", str(src), str(out)]) == 0
    text = capsys.readouterr().out
    assert "2026년 9월 → 2026년 10월" in text and "확인할 것" in text and "2026. 11. 5.(목)" in text
    assert "@바꾸기 ‘26년 9월 => ‘26년 10월" in out.read_text(encoding="utf-8")
    assert main(["carry", str(src), str(out), "--json"]) == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["to"] == "2026-10" and data["ask"]


def test_cli_carry_to_option(blank, tmp_path, capsys):
    from hwpxkit.cli import main
    pkg = Package.open(blank)
    append_to_body(pkg, para("기간 없음"))
    src = pkg.save(tmp_path / "x.hwpx")
    assert main(["carry", str(src), str(tmp_path / "o.md")]) == 2
    assert "--to" in capsys.readouterr().err
    assert main(["carry", str(src), str(tmp_path / "o.md"), "--to", "2026-10"]) == 0


def test_skill_documents_monthly():
    from pathlib import Path
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "carry.md").read_text(encoding="utf-8")
    for word in ('hwpx.py" carry', "table-from", "--to", "확인할 것", "지어내지"):
        assert word in text, word
    assert "reference/carry.md" in (root / "SKILL.md").read_text(encoding="utf-8")
    assert "---:" in (root / "reference" / "markdown.md").read_text(encoding="utf-8")


# ---- 최종 리뷰 반영 ----

def _doc(blank, paras, tables=()):
    pkg = Package.open(blank)
    for p in paras:
        append_to_body(pkg, para(p))
    for t in tables:
        append_to_body(pkg, t)
    return pkg


def _apply(pkg, tmp_path):
    from hwpxkit.carry import carry
    r = carry(pkg)
    fill(pkg, parse_fill(r["spec"]), base_dir=tmp_path)
    texts = [t.text for t in pkg.xml(SECTION).iter() if t.tag.endswith("}t") and t.text]
    return r, texts


def test_dot_month_not_inside_full_date(blank, tmp_path):
    """C1: '2026. 9.'를 바꾸는 줄이 '2026. 9. 15.' 같은 다른 날짜까지 바꾸면 앞뒤 글을 붙여 그 자리만 바꾼다."""
    r, texts = _apply(_doc(blank, ["‘26년 9월 월간 보고", "기간 2026. 9.", "2026. 9. 15. 회의 개최"]), tmp_path)
    assert "2026. 9. 15. 회의 개최" in texts and "기간 2026. 10." in texts


def test_report_date_not_touched_by_replacements(blank, tmp_path):
    """C1: 보고일 줄은 바꾸기 줄이 건드리지 않는다."""
    r, texts = _apply(_doc(blank, ["‘26년 9월 월간 보고", "보고일: 2026. 10. 5.(월)", "차월 계획 기간 2026. 10."]), tmp_path)
    assert "보고일: 2026. 10. 5.(월)" in texts


def test_other_year_head_untouched(blank, tmp_path):
    """C2: '2025년 9월 말'처럼 다른 해의 같은 달은 바꾸지 않는다."""
    r, texts = _apply(_doc(blank, ["‘26년 9월 월간 보고", "2025년 9월 말 기준 누적, 9월 말 현재"]), tmp_path)
    assert any("2025년 9월 말" in t and "10월 말 현재" in t for t in texts)


def test_bare_plan_actual_not_moved(blank):
    """C3: 달 표시 없는 '계획 | 실적'(목표 대비 실적 표)은 옮기지 않고 확인할 것으로."""
    from hwpxkit.carry import carry
    pkg = _doc(blank, ["‘26년 9월 월간 보고"], [table(2, 4, texts={
        (0, 0): "지표", (0, 1): "계획", (0, 2): "실적", (0, 3): "달성률",
        (1, 0): "논문", (1, 1): "3편", (1, 2): "2편", (1, 3): "67%"})])
    r = carry(pkg)
    assert "@칸" not in r["spec"] and any(a["kind"] == "plan-columns" for a in r["ask"])


def test_headers_renamed_by_replacements_still_fill(blank, tmp_path):
    """I1: 머리에 '(26. 09.)'·'9월 실적'이 있어 바꾸기로 머리가 바뀌어도 옮기기가 맞는 칸을 찾는다."""
    for heads in (("금월 실적 (26. 09.)", "차월 계획 (26. 10.)"), ("9월 실적", "10월 계획")):
        pkg = _doc(blank, ["‘26년 9월 월간 보고"], [table(2, 3, texts={
            (0, 0): "과제", (0, 1): heads[0], (0, 2): heads[1], (1, 0): "가", (1, 1): "a", (1, 2): "b"})])
        r, texts = _apply(pkg, tmp_path)
        from hwpxkit.form import cells
        row = {c.col: c.text for c in cells(pkg) if c.table == 1 and c.row == 1}
        assert row == {0: "가", 1: "b", 2: ""}, heads


def test_overlapping_olds_fill_ok(blank, tmp_path):
    """I2: '2026년 9월 실적'처럼 겹치는 글이어도 채우기가 멈추지 않는다."""
    r, texts = _apply(_doc(blank, ["‘26년 9월 월간 보고", "2026년 9월 실적 요약"]), tmp_path)
    assert "2026년 10월 실적 요약" in texts


def test_cross_month_range(blank, tmp_path):
    """I3: 달을 넘는 기간은 끝 날짜도 따로 한 달 넘긴다."""
    r, texts = _apply(_doc(blank, ["‘26년 9월 월간 보고", "시험 기간: 2026. 9. 15. ~ 10. 14."]), tmp_path)
    assert "시험 기간: 2026. 10. 15. ~ 11. 14." in texts


def test_korean_full_dates_asked(blank, tmp_path):
    """I4: '2026년 8월 31일'처럼 일까지 쓴 날짜는 바꾸지 않고 확인할 것으로 (9월 31일 같은 없는 날짜 방지)."""
    r, texts = _apply(_doc(blank, ["‘26년 8월 월간 보고", "2026년 8월 31일 완료"]), tmp_path)
    assert "2026년 8월 31일 완료" in texts
    assert any(a["kind"] == "date" and "8월 31일" in a["current"] for a in r["ask"])
