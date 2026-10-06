import pytest

from helpers import LONG, SECTION, report_template
from hwpxkit import bridge
from hwpxkit.body import own_text
from hwpxkit.header import Header
from hwpxkit.mdparse import parse
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import RenderError, Renderer, render_into
from hwpxkit.samples import Catalog, ParaStyle, infer
from hwpxkit.validate import validate

MD = f"""# 제1장 서론

## 1.1. 배경

□ 첫 글머리
- 세부 **굵게** 끝

{LONG}

# 제2장 방법

본문 [[색:파랑]]파란 글[[/색]] 입니다.
"""


def same_but_keep(pkg, got, sample):
    """제목 문단 모양은 견본과 같고 '다음 문단과 함께'만 켜져 있어야 한다."""
    import copy
    from lxml import etree
    from hwpxkit.header import Header
    h = Header(pkg)
    a, b = copy.deepcopy(h.get("paraPr", got)), copy.deepcopy(h.get("paraPr", sample))
    if a.find(q("hh:breakSetting")).get("keepWithNext") != "1":
        return False
    for e in (a, b):
        e.set("id", "0")
        e.find(q("hh:breakSetting")).set("keepWithNext", "1")
    return etree.tostring(a) == etree.tostring(b)


@pytest.fixture
def tpl(blank):
    pkg = Package.open(blank)
    ids = report_template(pkg)
    return pkg, infer(pkg), ids


def tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def test_new_mode_keeps_section_controls_and_merges_first_block(tpl):
    pkg, cat, ids = tpl
    render_into(pkg, cat, MD)
    ps = tops(pkg)
    first = ps[0]
    assert first.find(f".//{q('hp:secPr')}") is not None
    assert own_text(first) == "제1장 서론"
    assert same_but_keep(pkg, first.get("paraPrIDRef"), cat.paras["h1"].para_pr)
    assert "견본 표" not in "".join(own_text(p) for p in ps)


def test_styles_come_from_catalog(tpl):
    pkg, cat, ids = tpl
    render_into(pkg, cat, MD)
    by_text = {own_text(p): p for p in tops(pkg)}
    h2 = by_text["1.1. 배경"]
    assert same_but_keep(pkg, h2.get("paraPrIDRef"), cat.paras["h2"].para_pr)
    assert h2.find(q("hp:run")).get("charPrIDRef") == ids["h2"]
    assert "□ 첫 글머리" in by_text
    assert by_text[LONG].get("paraPrIDRef") == cat.paras["body"].para_pr


def test_spacer_before_second_heading_only(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, MD)
    texts = [own_text(p) for p in tops(pkg)]
    i = texts.index("제2장 방법")
    assert texts[i - 1] == ""
    assert texts[0] == "제1장 서론"


def test_inline_bold_and_color_derive_char_shapes(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, MD)
    h = Header(pkg)
    p = next(p for p in tops(pkg) if own_text(p).startswith("- 세부"))
    runs = p.findall(q("hp:run"))
    bold = next(r for r in runs if r.findtext(q("hp:t")) == "굵게")
    assert h.get("charPr", bold.get("charPrIDRef")).find(q("hh:bold")) is not None
    p2 = next(p for p in tops(pkg) if own_text(p).startswith("본문"))
    blue = next(r for r in p2.findall(q("hp:run")) if r.findtext(q("hp:t")) == "파란 글")
    assert h.get("charPr", blue.get("charPrIDRef")).get("textColor") == "#0000FF"


def test_auto_bullet_style_has_no_symbol_text(blank):
    pkg = Package.open(blank)
    auto = ParaStyle("0", "0", "0", auto_bullet=True)
    cat = Catalog({"body": ParaStyle("0", "0", "0"), "bullet1": auto})
    els = Renderer(pkg, cat).build(parse("□ 자동 글머리"))
    assert own_text(els[0]) == "자동 글머리"


def test_append_and_replace(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, MD)
    n = len(tops(pkg))
    render_into(pkg, cat, "덧붙인 " + LONG, mode="append")
    assert own_text(tops(pkg)[-1]).startswith("덧붙인")
    render_into(pkg, cat, "## 2.1. 새 절\n\n바꾼 " + LONG, replace=(1, 3))
    texts = [own_text(p) for p in tops(pkg)]
    assert texts[1] == "2.1. 새 절" and texts[2].startswith("바꾼")
    assert len(texts) == n + 1


def test_replace_rejects_first_paragraph_and_bad_range(tpl):
    pkg, cat, _ = tpl
    with pytest.raises(RenderError, match="첫 문단"):
        render_into(pkg, cat, "x", replace=(0, 2))
    with pytest.raises(RenderError, match="범위"):
        render_into(pkg, cat, "x", replace=(3, 999))


def test_page_break_marks_next_paragraph(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, f"{LONG}\n---쪽---\n다음 쪽 {LONG}")
    p = next(p for p in tops(pkg) if own_text(p).startswith("다음 쪽"))
    assert p.get("pageBreak") == "1"


def test_unknown_ref_and_math_warn(tpl):
    pkg, cat, _ = tpl
    warnings = render_into(pkg, cat, "참조 [@fig:none] 와 $x^2$ 그리고 $y$")
    assert any("fig:none" in w for w in warnings)


def test_output_has_no_lineseg_and_validates(tpl):
    pkg, cat, _ = tpl
    render_into(pkg, cat, MD)
    assert next(pkg.xml(SECTION).iter(q("hp:linesegarray")), None) is None
    assert [i for i in validate(pkg) if i.level == "error"] == []


@pytest.mark.hangul
def test_rendered_paragraphs_open_in_hangul(tpl, tmp_path):
    pkg, cat, _ = tpl
    render_into(pkg, cat, MD)
    assert bridge.check(pkg.save(tmp_path / "out.hwpx")) >= 1
