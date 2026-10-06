import pytest

from helpers import LONG, SECTION, add_equation_samples, report_template
from hwpxkit import bridge
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import RenderError, Renderer, render_into
from hwpxkit.samples import infer
from hwpxkit.validate import validate


@pytest.fixture
def tpl(blank):
    pkg = Package.open(blank)
    report_template(pkg)
    add_equation_samples(pkg)
    return pkg, infer(pkg)


def eqs(pkg):
    return list(pkg.xml(SECTION).iter(q("hp:equation")))


def test_equation_samples_found(tpl):
    _, cat = tpl
    assert cat.equation is not None
    assert cat.eq_table_para is not None
    assert cat.eq_label == "({n})"


def test_inline_math_becomes_equation(tpl):
    pkg, cat = tpl
    render_into(pkg, cat, "가 $\\frac{a}{b}$ 나 " + LONG)
    (eq,) = eqs(pkg)
    assert eq.findtext(q("hp:script")) == "{a} over {b}"
    assert int(eq.find(q("hp:sz")).get("height")) > 1800
    p = next(p for p in pkg.xml(SECTION) if p.tag == q("hp:p") and next(p.iter(q("hp:equation")), None) is not None)
    texts = [t.text for t in p.iter(q("hp:t"))]
    assert texts[0] == "가 " and texts[-1].startswith(" 나")
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_base_unit_follows_char_height(tpl):
    pkg, cat = tpl
    render_into(pkg, cat, "# 제1장 $x$ 제목")
    (eq,) = eqs(pkg)
    from hwpxkit.header import Header
    h1_char = cat.paras["h1"].char_pr
    assert eq.get("baseUnit") == Header(pkg).get("charPr", h1_char).get("height")


def test_conversion_warning_is_reported(tpl):
    pkg, cat = tpl
    warnings = render_into(pkg, cat, "값 $\\foo x$ 입니다")
    assert any("foo" in w for w in warnings)


def test_bad_latex_is_render_error(tpl):
    pkg, cat = tpl
    with pytest.raises(RenderError, match="수식"):
        render_into(pkg, cat, "값 ${a$ 입니다")


def test_equation_count(tpl):
    pkg, cat = tpl
    from hwpxkit.mdparse import parse
    r = Renderer(pkg, cat)
    r.build(parse("$a$ 와 $b$"))
    assert r.equation_count == 2


@pytest.mark.hangul
def test_inline_math_opens_and_refreshes(tpl, tmp_path):
    pkg, cat = tpl
    render_into(pkg, cat, "가 $\\sum_{i=1}^{n} x_i^2$ 나 $\\hat{\\beta}$ 다 " + LONG)
    est = [int(e.find(q("hp:sz")).get("height")) for e in eqs(pkg)]
    out, n = bridge.refresh_equations(pkg.save(tmp_path / "m.hwpx"), tmp_path / "m2.hwpx")
    assert n == 2
    real = [int(e.find(q("hp:sz")).get("height")) for e in Package.open(out).xml(SECTION).iter(q("hp:equation"))]
    for e, r in zip(est, real):
        assert e >= 0.9 * r


def test_display_math_uses_sample_table_and_numbers(tpl):
    pkg, cat = tpl
    render_into(pkg, cat, "# 제1장 서론\n\n$$ \\hat{\\beta} = (X^TX)^{-1}X^Ty $$ {#eq:ols}\n\n"
                          "[@eq:ols]의 추정량.\n\n$$ y = X\\beta $$\n")
    from hwpxkit.body import all_text, own_text
    tables = list(pkg.xml(SECTION).iter(q("hp:tbl")))
    assert len(tables) == 2
    assert [all_text(t).strip() for t in tables] == ["(1)", "(2)"]
    assert next(tables[0].iter(q("hp:equation"))).findtext(q("hp:script")).startswith("{hat {beta}}")
    texts = [own_text(p) for p in pkg.xml(SECTION) if p.tag == q("hp:p")]
    assert "(1)의 추정량." in texts
    ids = [t.get("id") for t in tables] + [e.get("id") for e in eqs(pkg)]
    assert len(ids) == len(set(ids))
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_display_math_fallback_without_sample(tpl):
    pkg, cat = tpl
    cat.eq_table_para = None
    render_into(pkg, cat, "$$ a^2 + b^2 = c^2 $$")
    (tbl,) = pkg.xml(SECTION).iter(q("hp:tbl"))
    assert tbl.get("colCnt") == "2"
    from hwpxkit.body import all_text
    assert all_text(tbl).strip() == "(1)"
    assert [i for i in validate(pkg) if i.level == "error"] == []


def test_chapter_equation_numbers(tpl):
    pkg, cat = tpl
    cat.eq_label = "({c}-{n})"
    render_into(pkg, cat, "# 제1장 가\n\n$$ a $$\n\n# 제2장 나\n\n$$ b $$\n\n$$ c $$")
    from hwpxkit.body import all_text
    assert [all_text(t).strip() for t in pkg.xml(SECTION).iter(q("hp:tbl"))] == ["(1-1)", "(2-1)", "(2-2)"]


@pytest.mark.hangul
def test_display_math_opens_in_hangul(tpl, tmp_path):
    pkg, cat = tpl
    render_into(pkg, cat, "$$ \\sum_{i=1}^{n} w_i (y_i - \\hat{y}_i)^2 $$")
    cat.eq_table_para = None
    render_into(pkg, cat, "$$ \\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix} $$", mode="append")
    out, n = bridge.refresh_equations(pkg.save(tmp_path / "d.hwpx"), tmp_path / "d2.hwpx")
    assert n == 2 and bridge.check(out) >= 1
