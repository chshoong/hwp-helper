import pytest
from lxml import etree

from helpers import LONG, append_to_body, para, report_template
from hwpxkit.header import Header
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.samples import Catalog, ParaStyle, SampleError, bullet_chars, classify, infer


@pytest.fixture
def template(blank):
    pkg = Package.open(blank)
    ids = report_template(pkg)
    return pkg, ids


def test_roles_found(template):
    pkg, ids = template
    cat = infer(pkg)
    assert cat.paras["h1"].char_pr == ids["h1"]
    assert cat.paras["h2"].char_pr == ids["h2"]
    assert cat.paras["h4"].char_pr == ids["h4"]
    assert cat.paras["caption_tbl"].para_pr == ids["center"]
    assert {"bullet1", "bullet2", "bullet3", "body", "blank"} <= set(cat.paras)
    assert cat.paras["bullet1"].example.startswith("□")
    assert not cat.paras["bullet1"].auto_bullet


def test_spacer_learned_before_h1(template):
    cat = infer(template[0])
    assert cat.paras["h1"].spacer is not None
    assert cat.paras["body"].spacer is None


def test_table_and_figure_samples_and_labels(template):
    cat = infer(template[0])
    assert cat.table_para is not None and next(cat.table_para.iter(q("hp:tbl"))).get("rowCnt") == "2"
    assert cat.figure_para is not None and next(cat.figure_para.iter(q("hp:caption"))) is not None
    assert cat.tbl_label == "[표 {c}-{n}]"
    assert cat.fig_label == "[그림 {c}-{n}]"


def test_toc_line_is_not_a_heading(blank):
    pkg = Package.open(blank)
    p = para("제1장 서론")
    t = p.find(f"{q('hp:run')}/{q('hp:t')}")
    etree.SubElement(t, q("hp:tab")).tail = "3"
    h = Header(pkg)
    assert classify(p, h, bullet_chars(h)) == (None, None)


def test_long_sentence_starting_like_heading_is_body(blank):
    h = Header(Package.open(blank))
    role, _ = classify(para("제2장에서 살펴본 " + LONG), h, {})
    assert role == "body"


def test_require_falls_back():
    body = ParaStyle("1", "0", "2")
    b2 = ParaStyle("3", "0", "4")
    cat = Catalog({"body": body, "bullet2": b2})
    assert cat.require("bullet4") is b2
    assert cat.require("h3") is body
    with pytest.raises(SampleError, match="본문"):
        Catalog({}).require("h1")


def test_mixed_formats_noted(blank):
    pkg = Package.open(blank)
    h = Header(pkg)
    a, b = h.derive_charpr("0", bold=True), h.derive_charpr("0", italic=True)
    for cid in (a, b, a, b):
        append_to_body(pkg, para("1.1. 제목", char_pr=cid))
    cat = infer(pkg)
    assert any("절 제목" in n and "섞여" in n for n in cat.notes)


def test_describe_mentions_roles(template):
    lines = infer(template[0]).describe()
    assert any(line.startswith("장 제목") for line in lines)
    assert any("번호 형식" in line for line in lines)


def test_real_final_report_roles(private_dir):
    cat = infer(Package.open(private_dir / "final.hwpx"))
    assert (cat.paras["h1"].para_pr, cat.paras["h1"].char_pr) == ("13", "20")
    # 최종보고서 본문은 '•' 자동 글머리 문단(문단모양 17)이고, 글머리 없는 본문은 수식 뒤 이어지는 문단(36)이다
    assert (cat.paras["bullet4"].para_pr, cat.paras["bullet4"].char_pr) == ("17", "11")
    assert cat.paras["bullet4"].auto_bullet
    assert (cat.paras["body"].para_pr, cat.paras["body"].char_pr) == ("36", "11")
    assert (cat.paras["h4"].para_pr, cat.paras["h4"].char_pr) == ("12", "14")
    assert (cat.paras["bullet1"].para_pr, cat.paras["bullet1"].char_pr) == ("12", "13")
    assert cat.paras["h2"].para_pr == "12"
    assert cat.tbl_label == "[표 {c}-{n}]"
    assert cat.table_para is not None and cat.figure_para is not None


def test_inner_table_caption_counts_as_table_caption_and_is_preferred(blank):
    from helpers import add_inner_caption, table
    pkg = Package.open(blank)
    append_to_body(pkg, table(2, 2, texts={(0, 0): "캡션 없는 표"}))
    append_to_body(pkg, add_inner_caption(table(2, 2, texts={(0, 0): "캡션 있는 표"}), "[표 2-1] 안쪽 캡션"))
    cat = infer(pkg)
    tbl = next(cat.table_para.iter(q("hp:tbl")))
    assert tbl.find(q("hp:caption")) is not None
    assert cat.tbl_label == "[표 {c}-{n}]"
    assert cat.fig_label == "[그림 {n}]"


def test_dotted_toc_line_is_not_a_heading(blank):
    h = Header(Package.open(blank))
    assert classify(para("제1장 서론 ········ 1"), h, {}) == (None, None)
    assert classify(para("제2장 방법 ...... 12"), h, {}) == (None, None)


def test_tie_prefers_later_format(blank):
    pkg = Package.open(blank)
    h = Header(pkg)
    toc, real = h.derive_charpr("0", italic=True), h.derive_charpr("0", bold=True)
    for cid in (toc, toc, real, real):
        append_to_body(pkg, para("제1장 서론", char_pr=cid))
    assert infer(pkg).paras["h1"].char_pr == real


def test_sentence_starting_with_label_is_body(blank):
    h = Header(Package.open(blank))
    assert classify(para("[표 1-1]과 같이 " + LONG), h, {})[0] == "body"
    assert classify(para("[표 1-1] 활용 사례"), h, {})[0] == "caption_tbl"


@pytest.mark.parametrize("text", ["Ⅰ. 개요", "Ⅳ. 추진 계획", "II. 추진 배경"])
def test_roman_numeral_heading_is_h1(blank, text):
    h = Header(Package.open(blank))
    assert classify(para(text), h, {})[0] == "h1"


def test_heading_levels_follow_numbering_used_in_document(blank):
    """'제N장' 없이 1. → 1.1. 로 가는 문서(논문)는 1.이 1단계, 1.1.이 2단계 (프리셋 제작 중 발견)."""
    pkg = Package.open(blank)
    h = Header(pkg)
    big, small = h.derive_charpr("0", height=1200, bold=True), h.derive_charpr("0", height=1000, bold=True)
    for text, cid in (("1. 서론", big), ("1.1. 배경", small), ("2. 방법", big), ("2.1. 자료", small)):
        append_to_body(pkg, para(text, char_pr=cid))
    cat = infer(pkg)
    assert cat.paras["h1"].char_pr == big and cat.paras["h2"].char_pr == small
    from hwpxkit.reader import to_markdown
    md = to_markdown(pkg)
    assert "# 1. 서론" in md and "## 1.1. 배경" in md


def test_heading_levels_with_chapters_unchanged(template):
    cat = infer(template[0])
    assert cat.paras["h1"].char_pr == template[1]["h1"]
    assert cat.paras["h2"].char_pr == template[1]["h2"]


@pytest.mark.parametrize("text", ["X. Wang, Deep nets (2020).", "I. Goodfellow, GANs.", "V. Vapnik, Statistical learning"])
def test_english_initial_is_not_roman_heading(text):
    """영문 이니셜(X. Wang)을 로마 숫자 장 제목으로 잡지 않는다 (최종 리뷰)."""
    from hwpxkit.samples import heading_key
    assert heading_key(text) is None
