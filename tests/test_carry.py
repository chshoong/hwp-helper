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
