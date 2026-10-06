"""한글 수식 크기 추정 (한글이 없는 환경용). 길이 단위는 baseUnit(글자 크기)의 배수.

상자 모델: 각 요소를 (너비 w, 기준선 위 a, 기준선 아래 d) 상자로 보고 첨자·분수·큰 연산자·행렬을 쌓는다.
상수 K는 scripts/calibrate_equations.py가 한글 2024의 실제 계산값(tests/fixtures/eq_sizes.json)에 맞춘 것이다.
높이를 작게 잡으면 수식이 위아래 글자와 겹치므로(스파이크 E2) 보정 손실에서 작게 잡는 쪽을 더 벌한다.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .equation import HWP_TOKEN

K = dict(
    upper=0.825,
    lower=0.569,
    digit=0.550,
    greek=0.607,
    op=1.154,
    punct=0.291,
    paren=0.485,
    bar=0.148,
    word=0.630,
    hangul=1.050,
    thin=0.262,
    space=0.330,
    asc=0.860,
    desc=0.139,
    script=0.707,
    sub_shift=0.236,
    sup_shift=0.584,
    frac_gap=0.261,
    frac_axis=0.360,
    frac_pad=0.477,
    bigop_w=1.213,
    bigop_a=0.966,
    bigop_d=0.231,
    int_w=0.985,
    limit_gap=0.120,
    sqrt_w=0.868,
    sqrt_pad=0.127,
    accent=0.214,
    delim_w=0.532,
    delim_pad=0.001,
    row_gap=0.112,
    col_gap=0.340,
    int_a=1.611,
    int_d=0.985,
    eq_pad=0.018,
)

_BIG = {"sum", "prod", "smallsum", "bigcup", "bigcap", "coprod"}
_LIMIT_FUNCS = {"lim"}  # 한글은 max·min 첨자를 옆에 붙이고 lim만 아래로 내린다
_FUNCS = {"log", "ln", "exp", "sin", "cos", "tan", "det", "arg", "Pr", "deg"}
_GREEKS = {"alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta", "iota",
           "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi",
           "psi", "omega"}
_OPS = {"times", "cdot", "div", "ast", "circ", "bullet", "star", "leq", "geq", "neq", "approx", "sim", "simeq",
        "cong", "equiv", "propto", "in", "notin", "subset", "subseteq", "supset", "cup", "cap", "rarrow",
        "larrow", "lrarrow", "vert", "parallel", "bot", "odot", "otimes", "oplus", "ominus", "land", "lor",
        "wedge", "vee", "prec", "succ", "vdash", "ni", "sqsubset",
        "forall", "exists"}  # 한글은 ∀·∃ 앞뒤에 연산자처럼 간격을 둔다
_GLYPHS = {"inf", "partial", "nabla", "emptyset", "prime", "angle", "dagger", "hbar", "ell",
           "aleph", "ldots", "cdots", "vdots", "ddots", "lbrace", "rbrace", "langle", "rangle", "neg",
           "therefore", "because", "top", "triangle"}
_ACCENTS = {"hat", "bar", "overline", "tilde", "vec", "dot", "ddot", "under"}
_FONTS = {"rm", "it", "bold"}
_ENVS = {"matrix": 0, "pmatrix": 2, "bmatrix": 2, "dmatrix": 2, "cases": 1, "eqalign": 0}


@dataclass
class Box:
    w: float
    a: float
    d: float
    big: bool = False

    @property
    def h(self) -> float:
        return self.a + self.d


def _line() -> Box:
    return Box(0.0, K["asc"], K["desc"])


def _hbox(boxes: list[Box]) -> Box:
    if not boxes:
        return Box(0.0, K["asc"], K["desc"])
    return Box(sum(b.w for b in boxes), max(b.a for b in boxes), max(b.d for b in boxes))


def estimate(script: str, base_unit: int) -> tuple[int, int, int]:
    """(너비, 높이 HWPUNIT, baseLine %)."""
    lines = _Layout(script).seq(None, cells=True)  # 맨 위 단계의 '#'은 한글에서 줄바꿈
    boxes = [_hbox(r) for r in lines if r]
    if len(boxes) > 1:
        total = sum(b.h for b in boxes) + K["row_gap"] * (len(boxes) - 1)
        box = Box(max(b.w for b in boxes), boxes[0].a, total - boxes[0].a)
    else:
        box = boxes[0] if boxes else _line()
    a, d = max(box.a, K["asc"]), max(box.d, K["desc"])
    w = box.w + K["eq_pad"]
    return round(w * base_unit), round((a + d) * base_unit), round(100 * a / (a + d))


class _Layout:
    def __init__(self, s: str):
        self.toks = [t for t in HWP_TOKEN.findall(s) if not t.isspace()]
        self.i = 0

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self):
        t = self._peek()
        self.i += 1
        return t

    def seq(self, closing, cells: bool = False):
        """closing까지 가로로 쌓는다. cells=True면 '&'/'#'로 나눈 칸 목록(행 목록)을 돌려준다."""
        rows: list[list[Box]] = [[]]
        cur: list[dict] = []

        def flush():
            rows[-1].append(_hbox([self._attach(x) for x in cur]))
            cur.clear()

        while True:
            t = self._peek()
            if t is None or t == closing:
                break
            if t == "}":
                self._next()
                continue
            if t in ("_", "^"):
                self._next()
                arg = self.atom()
                if not cur:
                    cur.append({"base": Box(0, K["asc"], K["desc"]), "sub": None, "sup": None})
                cur[-1]["sub" if t == "_" else "sup"] = arg
                continue
            if self._mode_switch(t):
                self._next()
                continue
            if t.lower() in ("over", "atop", "choose"):
                self._next()
                num = self._attach(cur.pop()) if cur else _line()
                den = self.atom()
                cur.append({"base": self._frac(num, den, t.lower() == "choose"), "sub": None, "sup": None})
                continue
            if cells and t in ("&", "#"):
                self._next()
                flush()
                if t == "#":
                    rows.append([])
                continue
            if t in ("LEFT", "left"):
                self._next()
                cur.append({"base": self._delimited(), "sub": None, "sup": None})
                continue
            cur.append({"base": self.atom(), "sub": None, "sup": None})
        if cells:
            flush()
            return rows
        return _hbox([self._attach(x) for x in cur])

    def _mode_switch(self, t: str) -> bool:
        """중괄호 없이 쓴 rm/it는 글꼴 모드 전환일 뿐 크기가 없다."""
        if t.lower() not in ("rm", "it"):
            return False
        nxt = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else ""
        return nxt != "{" and not nxt.startswith('"')

    def _attach(self, x: dict) -> Box:
        base, sub, sup = x["base"], x["sub"], x["sup"]
        if sub is None and sup is None:
            return base
        s = K["script"]
        if base.big:
            w = max(base.w, sub.w * s if sub else 0, sup.w * s if sup else 0)
            a = base.a + (sup.h * s + K["limit_gap"] if sup else 0)
            d = base.d + (sub.h * s + K["limit_gap"] if sub else 0)
            return Box(w, a, d)
        w = base.w + max(sub.w * s if sub else 0, sup.w * s if sup else 0)
        a = max(base.a, K["sup_shift"] + sup.a * s + max(0.0, sup.d - K["desc"]) * s) if sup else base.a
        d = max(base.d, K["sub_shift"] + sub.d * s + max(0.0, sub.a - K["asc"]) * s) if sub else base.d
        return Box(w, a, d)

    def _frac(self, num: Box, den: Box, paren: bool) -> Box:
        g, axis = K["frac_gap"], K["frac_axis"]
        w = max(num.w, den.w) + K["frac_pad"] + (2 * K["delim_w"] if paren else 0)
        return Box(w, num.h + g / 2 + axis, den.h + g / 2 - axis)

    def _delimited(self) -> Box:
        opening = self._next()
        inner = []
        while self._peek() not in (None, "RIGHT", "right"):
            inner.append(self.seq_until_right())
        closing = None
        if self._peek() is not None:
            self._next()
            closing = self._next()
        body = _hbox(inner)
        widths = sum(K["delim_w"] for d in (opening, closing) if d not in (None, "."))
        return Box(body.w + widths, body.a + K["delim_pad"], body.d + K["delim_pad"])

    def seq_until_right(self) -> Box:
        cur = []
        while self._peek() not in (None, "RIGHT", "right"):
            t = self._peek()
            if t in ("_", "^"):
                self._next()
                arg = self.atom()
                if not cur:
                    cur.append({"base": _line(), "sub": None, "sup": None})
                cur[-1]["sub" if t == "_" else "sup"] = arg
                continue
            if self._mode_switch(t):
                self._next()
                continue
            if t.lower() in ("over", "atop", "choose"):
                self._next()
                num = self._attach(cur.pop()) if cur else _line()
                cur.append({"base": self._frac(num, self.atom(), t.lower() == "choose"), "sub": None, "sup": None})
                continue
            if t in ("LEFT", "left"):
                self._next()
                cur.append({"base": self._delimited(), "sub": None, "sup": None})
                continue
            cur.append({"base": self.atom(), "sub": None, "sup": None})
        return _hbox([self._attach(x) for x in cur])

    def atom(self) -> Box:
        t = self._next()
        if t is None:
            return Box(0.0, K["asc"], K["desc"])
        if t == "{":
            inner = self.seq("}")
            self._next()
            return inner
        if t.startswith('"'):
            text = t[1:-1]
            w = sum(K["hangul"] if unicodedata.east_asian_width(c) in "WF" else K["word"] for c in text)
            return Box(w, K["asc"], K["desc"])
        low = t.lower()
        if t == "root":
            idx = self.atom()
            if self._peek() == "of":
                self._next()
            x = self.atom()
            return Box(x.w + K["sqrt_w"] + idx.w * K["script"], x.a + K["sqrt_pad"], x.d)
        if low == "sqrt":
            x = self.atom()
            return Box(x.w + K["sqrt_w"], x.a + K["sqrt_pad"], x.d)
        if low in _ACCENTS and t.isalpha():
            x = self.atom()
            if low == "under":
                return Box(x.w, x.a, x.d + K["accent"])
            return Box(x.w, x.a + K["accent"], x.d)
        if low in _FONTS:
            return self.atom()
        if low in _ENVS and self._peek() == "{":
            self._next()
            rows = self.seq("}", cells=True)
            self._next()
            return self._grid(rows, _ENVS[low])
        if low in _BIG:
            return Box(K["bigop_w"], K["bigop_a"], K["bigop_d"], big=True)
        if low in ("int", "oint"):
            return Box(K["int_w"], K["int_a"], K["int_d"])
        if low in _LIMIT_FUNCS:
            return Box(len(t) * K["word"], K["asc"], K["desc"], big=True)
        if t in _FUNCS or low in _FUNCS or low in ("max", "min"):
            return Box(len(t) * K["word"] + K["thin"], K["asc"], K["desc"])
        if low in _GREEKS:
            return Box(K["greek"] if t.islower() else K["upper"], K["asc"], K["desc"])
        if low in _OPS:
            return Box(K["op"], K["asc"], K["desc"])
        if low in _GLYPHS:
            return Box(K["greek"], K["asc"], K["desc"])
        if t in ("->", "<-", "<<", ">>", "<=", ">=", "!=", "+-", "-+", "=", "+", "-", "<", ">"):
            return Box(K["op"], K["asc"], K["desc"])
        if t in ("(", ")", "[", "]"):
            return Box(K["paren"], K["asc"], K["desc"])
        if t in ("|", "||"):
            return Box(K["bar"] * len(t), K["asc"], K["desc"])
        if t in (",", ".", ";", ":", "'"):
            return Box(K["punct"], K["asc"], K["desc"])
        if t == "`":
            return Box(K["thin"], K["asc"], K["desc"])
        if t == "~":
            return Box(K["space"], K["asc"], K["desc"])
        if t[0].isdigit():
            return Box(sum(K["digit"] if c.isdigit() else K["punct"] for c in t), K["asc"], K["desc"])
        if t.isalpha():
            return Box(sum(K["upper"] if c.isupper() else K["lower"] for c in t), K["asc"], K["desc"])
        w = K["hangul"] if unicodedata.east_asian_width(t[0]) in "WF" else K["lower"]
        return Box(w, K["asc"], K["desc"])

    def _grid(self, rows: list[list[Box]], delims: int) -> Box:
        rows = [r for r in rows if r]
        n_cols = max(len(r) for r in rows) if rows else 0
        col_w = [max((r[c].w for r in rows if c < len(r)), default=0) for c in range(n_cols)]
        height = sum(max(b.h for b in r) for r in rows) + K["row_gap"] * max(len(rows) - 1, 0)
        w = sum(col_w) + K["col_gap"] * max(n_cols - 1, 0) + delims * K["delim_w"]
        axis = K["frac_axis"]
        return Box(w, height / 2 + axis, height / 2 - axis)
