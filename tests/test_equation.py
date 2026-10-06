from pathlib import Path

import pytest

from hwpxkit.equation import EquationError, latex_to_hwp


@pytest.mark.parametrize("latex, hwp", [
    (r"\frac{a+b}{c}", "{a + b} over {c}"),
    (r"x_i^2", "x _{i} ^{2}"),
    (r"\sum_{i=1}^{n} x_i", "sum _{i = 1} ^{n} x _{i}"),
    (r"\hat{\beta}_{MLE}", "{hat {beta}} _{M L E}"),
    (r"\sqrt[3]{x} + \sqrt{y}", "root {3} of {x} + sqrt {y}"),
    (r"\left( \frac{a}{b} \right)", "LEFT ( {a} over {b} RIGHT )"),
    (r"\left\langle x \right\rangle", "LEFT langle x RIGHT rangle"),
    (r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", "pmatrix{a & b # c & d}"),
    (r"f(x)=\begin{cases} x & x\ge 0 \\ -x & x<0 \end{cases}", "f ( x ) = cases{x & x geq 0 # - x & x < 0}"),
    (r"\begin{aligned} a &= b \\ c &= d \end{aligned}", "eqalign{a & = b # c & = d}"),
    (r"\text{if } x", 'rm "if " it x'),
    (r"\operatorname{argmin}_\theta", 'rm "argmin" it _{theta}'),
    (r"\mathrm{max}_i", "rm {m a x} it _{i}"),
    (r"\alpha \Gamma \varphi", "alpha GAMMA varphi"),
    (r"a \le b \neq c \to \infty", "a leq b neq c -> inf"),
    (r"A \Rightarrow B \iff C", "A RARROW B LRARROW C"),
    (r"\forall x \in A, x \perp y", "FORALL x in A , x bot y"),
    (r"a \ll b \gg c", "a << b >> c"),
    (r"\{1,2\}", "lbrace 1 , 2 rbrace"),
    (r"\inf_x f \le \sup_x f", 'rm "inf" it _{x} f leq rm "sup" it _{x} f'),
    (r"\binom{n}{k}", "{n} choose {k}"),
    (r"a\,b\;c\quad d", "a ` b ~ c ~~ d"),
    (r"x'", "x prime"),
    (r"\widehat{xy}", "{hat {x y}}"),
    (r"\hwp{sum _{i} x}", "sum _{i} x"),
    (r"\mathbf{X}\boldsymbol{\beta}", "bold {X} bold {beta}"),
])
def test_conversions(latex, hwp):
    script, warnings = latex_to_hwp(latex)
    assert script == hwp
    assert warnings == []


def test_unknown_command_kept_as_roman_text_with_warning():
    script, warnings = latex_to_hwp(r"a \foo b")
    assert script == 'a rm "foo" it b'
    assert any("foo" in w for w in warnings)


def test_blackboard_font_warns():
    script, warnings = latex_to_hwp(r"\mathbb{R}")
    assert script == "rm {bold {R}} it"
    assert warnings


@pytest.mark.parametrize("bad", ["{a", "a}", r"\frac{a}", r"\left(", r"\sqrt[3"])
def test_unbalanced_braces_raise(bad):
    with pytest.raises(EquationError):
        latex_to_hwp(bad)


def test_mismatched_env_raises():
    with pytest.raises(EquationError, match="짝"):
        latex_to_hwp(r"\begin{pmatrix} a \end{bmatrix}")


@pytest.mark.hangul
def test_every_symbol_renders_as_one_glyph(tmp_path):
    """SYMBOLS의 한 글자 기호가 한글에서 실제로 기호 하나로 그려지는지 (모르는 단어면 글자 여러 개 폭이 됨)."""
    import copy
    from helpers import append_to_body, para
    from hwpxkit import bridge, shapes
    from hwpxkit.equation import SYMBOLS
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    single = {k: v for k, v in SYMBOLS.items()
              if v and v.isalpha() and len(v) > 2 and k not in
              ("log", "ln", "exp", "sin", "cos", "tan", "det", "lim", "max", "min", "arg", "Pr", "deg",
               "sum", "prod", "int", "oint", "quad", "qquad", "langle", "rangle", "lbrace", "rbrace")}
    pkg = Package.open(Path(__file__).parent / "fixtures" / "blank.hwpx")
    names = ["M"] + list(single)
    for name in names:
        script = "M" if name == "M" else single[name]
        p = append_to_body(pkg, para(""))
        p.find(q("hp:run")).append(shapes.new_equation(script, 1000, 1000, 86, 1000))
    out = bridge.refresh_equations(pkg.save(tmp_path / "s.hwpx"), tmp_path / "s2.hwpx")[0]
    widths = [int(e.find(q("hp:sz")).get("width")) for e in Package.open(out).xml("Contents/section0.xml").iter(q("hp:equation"))]
    m = widths[0]
    too_wide = [n for n, w in zip(names[1:], widths[1:]) if w > 1.8 * m]
    assert too_wide == []


from hwpxkit.equation import hwp_to_latex


@pytest.mark.parametrize("hwp, latex", [
    ("{a+b} over {c}", r"\frac{a + b}{c}"),
    ("x_i ^2", "x_{i}^{2}"),
    ("sum _{i=1} ^{n} x_i", r"\sum_{i = 1}^{n} x_{i}"),
    ("hat{z}_j", r"\hat{z}_{j}"),
    ("LEFT ( x RIGHT )", r"\left( x \right)"),
    ("left lbrace x right rbrace", r"\left\{ x \right\}"),
    ("pmatrix{1 & 0 # 0 & 1}", r"\begin{pmatrix}1 & 0 \\ 0 & 1\end{pmatrix}"),
    ("rm {max} _{i}", r"\mathrm{max}_{i}"),
    ('rm "SSE" it = w', r"\text{SSE} = w"),
    ("rm {m a x} it _{i}", r"\mathrm{max}_{i}"),
    ('"if " x', r"\text{if } x"),
    ("theta GAMMA Gamma", r"\theta \Gamma \Gamma"),
    ("a LEQ b IN C TIMES d", r"a \le b \in C \times d"),
    ("root {3} of {x}", r"\sqrt[3]{x}"),
    ("x `` y ~ z", r"x \, \, y \; z"),
    ("{n} choose {k}", r"\binom{n}{k}"),
    ("income _{final}", r"income_{final}"),
])
def test_hwp_to_latex(hwp, latex):
    assert hwp_to_latex(hwp) == latex


@pytest.mark.parametrize("latex", [
    r"\frac{a+b}{c}", r"\sum_{i=1}^{n} x_i^2", r"\hat{\beta}_{j}", r"\left( \frac{1}{2} \right)",
    r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", r"\sqrt[3]{x}", r"\text{if } x \le 0",
    r"f(y,z|x)=f(y|x)f(z|x)", r"\alpha \Gamma \to \infty",
])
def test_round_trip_examples(latex):
    once, _ = latex_to_hwp(latex)
    twice, _ = latex_to_hwp(hwp_to_latex(once))
    assert twice.replace(" ", "") == once.replace(" ", "")


def test_real_report_scripts_convert(private_dir):
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    scripts = [e.findtext(q("hp:script")) or "" for e in
               Package.open(private_dir / "final.hwpx").xml("Contents/section0.xml").iter(q("hp:equation"))]
    assert len(scripts) == 269
    for s in scripts:
        latex_to_hwp(hwp_to_latex(s))  # 예외 없이 왕복


# --- 계획 3 최종 검토 반영 ---

@pytest.mark.parametrize("latex, hwp", [
    (r"\displaystyle\frac12", "{1} over {2}"),
    (r"\sum\limits_{i=1}^n x_i", "sum _{i = 1} ^{n} x _{i}"),
    (r"x \label{eq:a} \tag{3} \nonumber", "x"),
    (r"\operatorname*{arg\,max}_x f", 'rm "arg max" it _{x} f'),
    (r"A^\top B^\intercal", "A ^{top} B ^{top}"),
    (r"\mathsf{T}", "rm {T} it"),
    (r"a \odot b \otimes c \oplus d", "a odot b otimes c oplus d"),
    (r"\neg p \land q \lor r", "neg p land q lor r"),
    (r"a \leqslant b \geqslant c", "a leq b geq c"),
    (r"\left\lVert x \right\rVert", "LEFT || x RIGHT ||"),
    (r"\therefore a \ni b", "therefore a ni b"),
])
def test_common_research_commands(latex, hwp):
    script, warnings = latex_to_hwp(latex)
    assert script == hwp
    assert warnings == []


def test_unknown_command_with_argument_keeps_argument():
    script, warnings = latex_to_hwp(r"\overset{def}{=}")
    assert script == "{d e f} {=}"
    assert any("overset" in w for w in warnings)


@pytest.mark.parametrize("bad", ["x^}", r"\frac{a}}", r"{\left( a} \right)"])
def test_brace_where_argument_expected_raises(bad):
    with pytest.raises(EquationError):
        latex_to_hwp(bad)


@pytest.mark.parametrize("hwp, latex", [
    ("sum from{i=1} to{n} x_i", r"\sum_{i = 1}^{n} x_{i}"),
    ("int from a to b f", r"\int_{a}^{b} f"),
    ("barU + hatx", r"\bar{U} + \hat{x}"),
    ("rm SSE it = w", r"\mathrm{SSE} = w"),
    ("pile{a # b}", r"\begin{matrix}a \\ b\end{matrix}"),
    ("therefore", r"\therefore"),
    ("{1} SMALLOVER {2}", r"\tfrac{1}{2}"),
])
def test_hand_written_hangul_scripts(hwp, latex):
    assert hwp_to_latex(hwp) == latex
