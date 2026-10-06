import pytest

from helpers import monthly_form
from hwpxkit.form import fill, parse_fill
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.review import review


@pytest.fixture
def form(blank):
    pkg = Package.open(blank)
    monthly_form(pkg)
    return pkg


def codes(findings):
    return [f.code for f in findings]


def test_wrong_weekday_and_year_found(form):
    found = review(form)
    weekday = next(f for f in found if f.code == "weekday")
    assert "수요일" in weekday.message
    report = next(f for f in found if f.code == "report-date")
    assert "2026년 2월" in report.message


def test_correct_dates_are_quiet(form):
    fill(form, parse_fill("@바꾸기 2025.03.12.(목) => 2026.03.12.(목)\n"))
    assert "weekday" not in codes(review(form))
    assert "report-date" not in codes(review(form))


def test_month_headers_checked(form):
    assert "month-header" not in codes(review(form))
    fill(form, parse_fill("@바꾸기 ‘26년 2월 => ‘26년 3월\n@바꾸기 2025.03.12.(목) => 2026.04.06.(월)\n"))
    found = [f for f in review(form) if f.code == "month-header"]
    assert len(found) == 2
    assert any("26. 03." in f.message for f in found) and any("26. 04." in f.message for f in found)


def test_invalid_date(blank):
    from helpers import append_to_body, para
    pkg = Package.open(blank)
    append_to_body(pkg, para("작성일: 2026.02.30.(월)"))
    assert "bad-date" in codes(review(pkg))


def test_real_monthly_date_problems_found(private_dir):
    found = review(Package.open(private_dir / "monthly.hwpx"))
    assert {"weekday", "report-date"} <= set(codes(found))
    assert "month-header" not in codes(found)


from helpers import LONG, append_to_body, para, report_template
from hwpxkit.render import render_into
from hwpxkit.review import renumber
from hwpxkit.samples import infer


@pytest.fixture
def report(blank):
    pkg = Package.open(blank)
    report_template(pkg)
    return pkg, infer(pkg)


TABLES = ("# 제1장 가\n\n표: 하나\n| a | b |\n| c | d |\n\n표: 둘\n| a | b |\n| c | d |\n\n"
          "[표 1-1]과 [표 1-2]를 본다. " + LONG + "\n")


def test_numbering_problems(report):
    pkg, cat = report
    render_into(pkg, cat, TABLES)
    render_into(pkg, cat, "표: 셋\n| a | b |\n| c | d |\n\n[표 1-9]를 본다. " + LONG, mode="append")
    found = review(pkg)
    assert any(f.code == "caption-dup" and "[표 1-1]" in f.message for f in found)
    assert any(f.code == "bad-ref" and "[표 1-9]" in f.message for f in found)


def test_renumber_fixes_captions_and_references(report):
    pkg, cat = report
    render_into(pkg, cat, TABLES)
    render_into(pkg, cat, "표: 셋\n| a | b |\n| c | d |\n\n[표 1-1]을 다시 본다. " + LONG, mode="append")
    changes = renumber(pkg)
    assert any("[표 1-1] → [표 1-3]" in c for c in changes)
    found = review(pkg)
    assert not [f for f in found if f.code in ("caption-dup", "caption-gap")]


def test_placeholder_and_empty_cells(blank):
    pkg = Package.open(blank)
    monthly_form(pkg)
    found = review(pkg)
    assert any(f.code == "placeholder" and "상세 추진 내용" in f.message for f in found)
    assert any(f.code == "empty-cell" and "활용 서비스" in f.message for f in found)


def test_font_mix(blank):
    from hwpxkit.header import Header
    pkg = Package.open(blank)
    h = Header(pkg)
    fonts = h.fonts("HANGUL")
    other = next(fid for fid, face in fonts.items() if face != "함초롬바탕")

    def mutate(e):
        e.find("{http://www.hancom.co.kr/hwpml/2011/head}fontRef").set("hangul", other)
    odd = h.derive("charPr", "0", mutate)
    for _ in range(30):
        append_to_body(pkg, para(LONG))
    append_to_body(pkg, para("이 문장만 다른 글꼴", char_pr=odd))
    found = [f for f in review(pkg) if f.code == "font-mix"]
    assert found and "이 문장만" in found[0].message


def test_real_final_report_review_is_quiet(private_dir):
    found = review(Package.open(private_dir / "final.hwpx"))
    assert not [f for f in found if f.level == "오류" and f.code in ("caption-dup", "bad-ref")], found
    # 휴먼명조·-아이리스M은 글자 없는 빈 run에만 쓰여 실제 혼용이 아니다
    assert not any(f.code == "font-mix" for f in found)


def test_blank_line_formats_are_not_reported(private_dir):
    """빈 줄은 서식이 섞여 있어도 눈에 보이지 않으므로 검토 대상이 아니다 (3월 보고서 확인에서 나온 잡음)."""
    found = review(Package.open(private_dir / "monthly.hwpx"))
    assert not [f for f in found if f.code == "mixed-format" and f.message.startswith("빈 줄")]



# --- 계획 4 최종 검토 반영 ---

def test_renumber_keeps_correct_chapter_numbers_without_je_jang(blank):
    from helpers import append_to_body, para, table
    pkg = Package.open(blank)
    for text in ("1. 서론", "[표 1-1] 첫 표", "2. 본론", "[표 2-1] 둘째 표"):
        append_to_body(pkg, para(text))
        if text.startswith("[표"):
            append_to_body(pkg, table(2, 2))
    append_to_body(pkg, para("[표 2-1]을 본다. " + LONG))
    assert renumber(pkg) == []
    assert not [f for f in review(pkg) if f.code in ("caption-dup", "caption-gap", "bad-ref")]


def test_renumber_skips_unbracketed_captions(blank):
    from helpers import append_to_body, para, table
    pkg = Package.open(blank)
    for text in ("표 2. 첫 표", "표 3. 둘째 표"):
        append_to_body(pkg, para(text))
        append_to_body(pkg, table(2, 2))
    changes = renumber(pkg)
    assert any("괄호" in c for c in changes)
    from hwpxkit.body import own_text
    texts = [own_text(p) for p in pkg.xml("Contents/section0.xml") if p.tag == q("hp:p")]
    assert "표 2. 첫 표" in texts


def test_symbol_or_number_columns_are_not_placeholders(blank):
    from helpers import append_to_body, table
    pkg = Package.open(blank)
    append_to_body(pkg, table(4, 3, texts={(0, 1): "해당", (0, 2): "값", (1, 0): "가", (2, 0): "나", (3, 0): "다",
                                           (1, 1): "○", (2, 1): "○", (3, 1): "○", (1, 2): "1.0", (2, 2): "1.0",
                                           (3, 2): "1.0"}))
    assert not [f for f in review(pkg) if f.code == "placeholder"]


@pytest.mark.parametrize("text, code", [
    ("보고일: 26. 3. 5.(수)", "weekday"),
    ("작성일 2026년 3월 5일(수)", "weekday"),
    ("작성일 2026.02.30", "bad-date"),
])
def test_more_date_formats(blank, text, code):
    from helpers import append_to_body, para
    pkg = Package.open(blank)
    append_to_body(pkg, para(text))
    assert code in [f.code for f in review(pkg)]


def test_report_date_in_left_header_cell(blank):
    from helpers import append_to_body, para, table
    pkg = Package.open(blank)
    append_to_body(pkg, para("‘26년 2월 월간업무보고서"))
    append_to_body(pkg, table(1, 2, texts={(0, 0): "보고일", (0, 1): "2025.03.12.(수)"}))
    assert "report-date" in [f.code for f in review(pkg)]


def test_period_ignores_report_date_line(blank):
    from helpers import append_to_body, para
    pkg = Package.open(blank)
    monthly_form(pkg)
    root = pkg.edit("Contents/section0.xml")
    first_title = next(p for p in root if p.tag == q("hp:p") and "월간업무보고서" in "".join(p.itertext()))
    root.insert(list(root).index(first_title), para("보고일: 2026년 3월 5일(목)"))
    assert "month-header" not in [f.code for f in review(pkg)]
