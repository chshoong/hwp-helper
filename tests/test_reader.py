import re

from helpers import SECTION, LONG, append_to_body, para, report_template, table
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.reader import to_markdown


def read_template(blank, **kw):
    pkg = Package.open(blank)
    report_template(pkg)
    return to_markdown(pkg, **kw)


def test_headings_bullets_body(blank):
    md = read_template(blank)
    assert "# 제1장 서론" in md
    assert "## 1.1. 연구 배경" in md
    assert "#### 1) 필요성" in md
    assert "□ 주요 내용" in md and "- 더 세부 내용" in md
    assert LONG in md


def test_table_caption_and_pipe_table(blank):
    md = read_template(blank)
    assert "표: 견본 표" in md
    assert "| 구분 | 계획 | 실적 |" in md
    assert "|---|---|---|" in md


def test_figure_line(blank):
    md = read_template(blank)
    assert re.search(r"!\[견본 그림\]\(BinData/image\d+\.png\)", md)


def test_merged_cells_marks(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 3, spans={(0, 0): (1, 2), (0, 2): (2, 1)}, skip={(0, 1), (1, 2)},
                              texts={(0, 0): "머리", (0, 2): "세로", (1, 0): "가", (1, 1): ["나", "다"]}))
    md = to_markdown(pkg)
    assert "| 머리 | << | 세로 |" in md
    assert "| 가 | 나<br>다 | ^^ |" in md


def test_anchors_are_top_paragraph_indexes(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para("첫째 " + LONG))
    append_to_body(pkg, para("둘째 " + LONG))
    md = to_markdown(pkg, anchors=True)
    n = len(pkg.xml("Contents/section0.xml"))
    assert f"<!-- @{n - 2} -->\n첫째" in md
    assert f"<!-- @{n - 1} -->\n둘째" in md


def test_real_reports(private_dir, expected):
    final = to_markdown(Package.open(private_dir / "final.hwpx"))
    assert "# 제1장 서론" in final
    assert expected["final_h4_line"] in final
    assert expected["final_table_caption_line"] in final
    assert "$$" in final
    monthly = to_markdown(Package.open(private_dir / "monthly.hwpx"))
    assert expected["monthly_box_line"] in monthly
    assert expected["monthly_dash_line_prefix"] in monthly
    assert "| 구분 |" in monthly


def test_cell_text_is_not_turned_into_heading(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, table(1, 2, texts={(0, 0): "1. 항목", (0, 1): "제1장 요약"}))
    md = to_markdown(pkg)
    assert "| 1. 항목 | 제1장 요약 |" in md


def test_inner_table_caption_is_read(blank):
    from helpers import add_inner_caption
    pkg = Package.open(blank)
    append_to_body(pkg, add_inner_caption(table(2, 2, texts={(0, 0): "a"}), "[표 2-1] 견본 구조"))
    md = to_markdown(pkg)
    assert "표: 견본 구조\n| a |" in md


def test_fallback_figure_caption_paragraph_is_absorbed(blank, tmp_path):
    from helpers import tiny_png
    from hwpxkit.render import render_into
    from hwpxkit.samples import infer
    pkg = Package.open(blank)
    report_template(pkg)
    cat = infer(pkg)
    cat.figure_para = None
    (tmp_path / "a.png").write_bytes(tiny_png())
    render_into(pkg, cat, "![흐름도](a.png)", base_dir=tmp_path)
    md = to_markdown(pkg)
    assert re.search(r"!\[흐름도\]\(BinData/image\d+\.png\)", md)
    assert "[그림 1-1]" not in md


def test_equations_read_as_latex(blank):
    from helpers import add_equation_samples
    from hwpxkit.render import render_into
    from hwpxkit.samples import infer
    pkg = Package.open(blank)
    report_template(pkg)
    add_equation_samples(pkg)
    render_into(pkg, infer(pkg), "가 $\\frac{a}{b}$ 나 " + LONG + "\n\n$$ \\hat{\\beta}_j $$")
    md = to_markdown(pkg)
    assert "$\\frac{a}{b}$" in md
    assert "$$\\hat{\\beta}_{j}$$" in md


def test_read_then_render_keeps_equations(blank):
    from helpers import add_equation_samples
    from hwpxkit.render import render_into
    from hwpxkit.samples import infer
    pkg = Package.open(blank)
    report_template(pkg)
    add_equation_samples(pkg)
    cat = infer(pkg)
    render_into(pkg, cat, "가 $\\sum_{i=1}^{n} x_i^2$ 나 " + LONG)
    first = [e.findtext(q("hp:script")) for e in pkg.xml(SECTION).iter(q("hp:equation"))]
    render_into(pkg, cat, to_markdown(pkg))
    again = [e.findtext(q("hp:script")) for e in pkg.xml(SECTION).iter(q("hp:equation"))]
    assert [s.replace(" ", "") for s in again] == [s.replace(" ", "") for s in first]
