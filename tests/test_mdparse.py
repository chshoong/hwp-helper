import pytest

from hwpxkit.mdparse import (Bullet, Figure, Heading, MarkdownError, Math, PageBreak, Para, Span, Table,
                             parse, parse_inline)


def test_headings_bullets_paragraphs():
    blocks = parse("# 제1장 서론\n\n## 1.1. 배경\n\n□ 주요 내용\n○ 세부\n- 더 세부\n· 끝\n\n본문 문장입니다.\n")
    assert blocks[0] == Heading(1, [Span("text", "제1장 서론")])
    assert blocks[1] == Heading(2, [Span("text", "1.1. 배경")])
    assert [b.level for b in blocks[2:6]] == [1, 2, 3, 4]
    assert all(isinstance(b, Bullet) for b in blocks[2:6])
    assert blocks[2].spans == [Span("text", "주요 내용")]
    assert blocks[6] == Para([Span("text", "본문 문장입니다.")])


def test_inline_spans():
    spans = parse_inline("가 **굵게** 나 *기울임* [[색:파랑]]파란 **굵은**[[/색]] $x^2$ [@fig:flow] 끝")
    assert Span("text", "굵게", bold=True) in spans
    assert Span("text", "기울임", italic=True) in spans
    assert Span("text", "파란 ", color="#0000FF") in spans
    assert Span("text", "굵은", bold=True, color="#0000FF") in spans
    assert Span("math", "x^2") in spans
    assert Span("ref", "fig:flow") in spans
    assert spans[-1] == Span("text", " 끝")


def test_hex_color_and_unknown_color():
    assert parse_inline("[[색:#123456]]a[[/색]]") == [Span("text", "a", color="#123456")]
    with pytest.raises(MarkdownError, match="색"):
        parse_inline("[[색:보라색]]a[[/색]]")


def test_table_with_caption_and_attrs():
    md = "표: 활용 사례 {#tbl:cases widths=1,2,2}\n| 기관 | 대상 | 단계 |\n|---|:--:|---|\n| A | B |\n| ^^ | << | C |\n"
    (t,) = parse(md)
    assert t == Table([["기관", "대상", "단계"], ["A", "B", ""], ["^^", "<<", "C"]],
                      caption="활용 사례", label="tbl:cases", widths=[1.0, 2.0, 2.0])


def test_table_without_caption():
    (t,) = parse("| a | b |\n| c | d |")
    assert t.caption == "" and t.rows == [["a", "b"], ["c", "d"]]


def test_caption_without_table_raises():
    with pytest.raises(MarkdownError, match="2번째 줄"):
        parse("표: 제목\n그냥 문장")


def test_figure():
    (f,) = parse("![매칭 흐름](figs/flow.png){#fig:flow width=80%}")
    assert f == Figure("figs/flow.png", "매칭 흐름", label="fig:flow", width=0.8)
    (g,) = parse("![캡션](a.png)")
    assert g.width == 1.0 and g.label is None


def test_math_blocks():
    blocks = parse("$$ \\hat\\beta = (X^TX)^{-1}X^Ty $$ {#eq:ols}\n\n$$\na + b\n= c\n$$ {#eq:two}\n")
    assert blocks[0] == Math("\\hat\\beta = (X^TX)^{-1}X^Ty", label="eq:ols")
    assert blocks[1] == Math("a + b\n= c", label="eq:two")


def test_unclosed_math_raises():
    with pytest.raises(MarkdownError, match="닫히지"):
        parse("$$\na + b\n")


def test_page_break_and_comments():
    blocks = parse("<!-- 메모 -->\n첫 문단\n---쪽---\n둘째 문단\n")
    assert blocks == [Para([Span("text", "첫 문단")]), PageBreak(), Para([Span("text", "둘째 문단")])]


def test_bullet_needs_space():
    (b,) = parse("-5%는 감소")
    assert isinstance(b, Para)


def test_bad_attribute_value_names_the_line():
    with pytest.raises(MarkdownError, match="2번째 줄"):
        parse("문장\n![a](b.png){width=큼}")
    with pytest.raises(MarkdownError, match="1번째 줄"):
        parse("표: x {widths=1;2}\n| a | b |")


def test_asterisks_inside_words_are_kept():
    assert parse_inline("2*3*4 = 24") == [Span("text", "2*3*4 = 24")]
    assert Span("text", "기울임", italic=True) in parse_inline("가 *기울임* 나")


def test_currency_dollars_are_text():
    assert parse_inline("US$5에서 US$10으로") == [Span("text", "US$5에서 US$10으로")]
    assert parse_inline("가격 5$ 와 7$") == [Span("text", "가격 5$ 와 7$")]


def test_math_followed_by_korean_particle():
    assert parse_inline("변수 $A$와 $B$가") == [Span("text", "변수 "), Span("math", "A"), Span("text", "와 "),
                                               Span("math", "B"), Span("text", "가")]


def test_display_math_with_trailing_text_raises():
    with pytest.raises(MarkdownError, match="한 줄"):
        parse("$$x+y$$ 식 설명")
