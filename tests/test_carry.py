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
    assert "@칸 표1 | 과제 1 | 금월(9월) 실적\n모형 시험\n- 시범 자료 검증\n" in spec
    assert "@칸 표1 | 과제 1 | 차월(10월) 계획\n\n" in spec
    assert "과제 2 | 금월" not in spec  # 계획이 빈 행은 건너뜀
    plans = [a for a in r["ask"] if a["kind"] == "next-plan"]
    assert len(plans) == 1 and "과제 1" in plans[0]["where"]


def test_numbers_asked_not_invented(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    nums = {a["current"]: a for a in r["ask"] if a["kind"] == "number"}
    assert set(nums) == {"45%", "1,200"}
    assert nums["45%"]["address"].startswith("@칸 표2 | 진행률")
    assert "45%" not in r["spec"]


def test_ambiguous_plan_columns(blank):
    from hwpxkit.carry import carry
    pkg = Package.open(blank)
    append_to_body(pkg, para("‘26년 9월 월간 보고"))
    append_to_body(pkg, table(2, 4, texts={(0, 0): "과제", (0, 1): "금월 실적", (0, 2): "차월 계획", (0, 3): "연간 계획",
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
