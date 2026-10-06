"""LaTeX ↔ 한글 수식 스크립트 변환.

한글 문법은 한글 2024에서 실제로 렌더링해 확인한 것만 쓴다(계획 3 사전 조사 표).
- 한글 수식은 공백을 무시하므로 토큰 사이를 공백으로 띄운다. 글자를 이어 붙이지 않으니
  LaTeX의 s i n(변수 곱)이 한글 예약어 sin으로 바뀌는 일도 없다.
- 확인되지 않은 LaTeX 명령은 로만체 글자로 남기고 경고한다(문서 전체를 실패시키지 않음).
"""
from __future__ import annotations

import re


class EquationError(ValueError):
    """수식 문법 오류. 메시지는 사용자용 한국어."""


_GREEK = ("alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi "
          "pi rho sigma tau upsilon phi varphi chi psi omega").split()
_UPPER_GREEK = "Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega".split()
SYMBOLS: dict[str, str] = {g: g for g in _GREEK}
SYMBOLS.update({g: g.upper() for g in _UPPER_GREEK})
SYMBOLS.update({
    "times": "times", "cdot": "cdot", "div": "div", "pm": "+-", "mp": "-+", "ast": "ast", "circ": "circ",
    "bullet": "bullet", "star": "star",
    "le": "leq", "leq": "leq", "ge": "geq", "geq": "geq", "ne": "neq", "neq": "neq",
    "approx": "approx", "sim": "sim", "simeq": "simeq", "cong": "cong", "equiv": "equiv", "propto": "propto",
    "ll": "<<", "gg": ">>",
    "in": "in", "notin": "notin", "subset": "subset", "subseteq": "subseteq", "supset": "supset",
    "cup": "cup", "cap": "cap", "emptyset": "emptyset", "varnothing": "emptyset",
    "forall": "FORALL", "exists": "exists",
    "infty": "inf", "partial": "partial", "nabla": "nabla",
    "to": "->", "rightarrow": "->", "leftarrow": "<-", "gets": "<-", "mapsto": "->",
    "Rightarrow": "RARROW", "implies": "RARROW", "Leftarrow": "LARROW",
    "Leftrightarrow": "LRARROW", "iff": "LRARROW", "leftrightarrow": "lrarrow",
    "ldots": "ldots", "dots": "ldots", "cdots": "cdots", "vdots": "vdots", "ddots": "ddots",
    "prime": "prime", "mid": "vert", "vert": "vert", "Vert": "||",
    "angle": "angle", "parallel": "parallel", "perp": "bot",
    "dagger": "dagger", "hbar": "hbar", "ell": "ell", "aleph": "aleph",
    "sum": "sum", "prod": "prod", "int": "int", "oint": "oint",
    "bigcup": "bigcup", "bigcap": "bigcap", "coprod": "coprod",
    "odot": "odot", "otimes": "otimes", "oplus": "oplus", "ominus": "ominus",
    "neg": "neg", "lnot": "neg", "land": "land", "lor": "lor", "wedge": "wedge", "vee": "vee",
    "therefore": "therefore", "because": "because", "top": "top", "intercal": "top",
    "prec": "prec", "succ": "succ", "vdash": "vdash", "ni": "ni", "sqsubset": "sqsubset",
    "triangle": "triangle", "leqslant": "leq", "geqslant": "geq",
    "lVert": "||", "rVert": "||",
    "log": "log", "ln": "ln", "exp": "exp", "sin": "sin", "cos": "cos", "tan": "tan",
    "det": "det", "lim": "lim", "max": "max", "min": "min", "arg": "arg", "Pr": "Pr", "deg": "deg",
    "sup": 'rm "sup" it', "inf": 'rm "inf" it',  # rm 안에서도 inf는 ∞가 되므로 따옴표
    "langle": "langle", "rangle": "rangle", "lbrace": "lbrace", "rbrace": "rbrace",
    ",": "`", ";": "~", ":": "~", "!": "", " ": "~", "quad": "~~", "qquad": "~~~~",
    "{": "lbrace", "}": "rbrace", "|": "||", "%": "%", "#": '"#"', "&": '"&"', "_": '"_"', "$": '"$"',
})
_ACCENTS = {"hat": "hat", "widehat": "hat", "bar": "bar", "overline": "overline", "tilde": "tilde",
            "widetilde": "tilde", "vec": "vec", "dot": "dot", "ddot": "ddot", "underline": "under"}
_ENVS = {"matrix": "matrix", "pmatrix": "pmatrix", "bmatrix": "bmatrix", "vmatrix": "dmatrix",
         "cases": "cases", "aligned": "eqalign", "align": "eqalign", "align*": "eqalign",
         "split": "eqalign", "gathered": "eqalign", "array": "matrix"}
_DELIMS = {"(": "(", ")": ")", "[": "[", "]": "]", "|": "|", ".": ".", "\\{": "lbrace", "\\}": "rbrace",
           "\\langle": "langle", "\\rangle": "rangle", "\\|": "||", "\\Vert": "||", "\\vert": "|",
           "\\lvert": "|", "\\rvert": "|", "\\lbrace": "lbrace", "\\rbrace": "rbrace",
           "\\lVert": "||", "\\rVert": "||"}
_TEXTS = ("text", "textrm", "mbox", "operatorname", "operatorname*", "textit", "textbf")
# 화면에 아무것도 그리지 않는 LaTeX 명령 (인자가 있으면 인자도 버림)
_DROP = ("displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle", "limits", "nolimits",
         "nonumber", "notag")
_DROP_WITH_ARG = ("label", "tag", "tag*")
_SIZERS = ("bigl", "bigr", "Bigl", "Bigr", "big", "Big", "bigg", "Bigg", "biggl", "biggr")
_TOKEN = re.compile(r"\\[A-Za-z]+\*?|\\.|\s+|.", re.S)


def latex_to_hwp(latex: str) -> tuple[str, list[str]]:
    conv = _ToHwp(latex)
    out = conv.expr(None)
    if conv.lefts != 0:
        raise conv._err("\\left와 \\right의 짝이 맞지 않아요")
    return re.sub(r"\s+", " ", out).strip(), list(dict.fromkeys(conv.warnings))


class _ToHwp:
    def __init__(self, s: str):
        self.s = s.strip()
        self.toks = _TOKEN.findall(self.s)
        self.i = 0
        self.lefts = 0
        self.warnings: list[str] = []

    def _err(self, msg: str) -> EquationError:
        return EquationError(f"{msg}: {self.s}")

    def _peek(self):
        while self.i < len(self.toks) and self.toks[self.i].isspace():
            self.i += 1
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self):
        t = self._peek()
        self.i += 1
        return t

    def expr(self, closing: str | None) -> str:
        parts = []
        while True:
            t = self._peek()
            if t is None:
                if closing == "}":
                    raise self._err("수식에서 '{'가 닫히지 않았어요")
                if closing == "\\end":
                    raise self._err("\\begin에 맞는 \\end가 없어요")
                break
            if t == closing:
                break
            if t == "}":
                raise self._err("수식에 짝이 없는 '}'가 있어요")
            parts.append(self.item())
        return " ".join(p for p in parts if p)

    def arg(self) -> str:
        t = self._peek()
        if t is None or t in ("}", "&", "\\end", "\\\\"):
            raise self._err("명령 뒤에 들어갈 내용이 없어요")
        if t == "{":
            self._next()
            lefts = self.lefts
            inner = self.expr("}")
            self._next()
            if self.lefts != lefts:
                raise self._err("\\left와 \\right가 같은 중괄호 안에서 짝을 이루지 않아요")
            return inner
        return self.item()

    def raw(self) -> str:
        """{…} 안의 글자를 그대로 (\\text, \\begin, \\hwp 용)."""
        if self._peek() != "{":
            raise self._err("'{'가 와야 해요")
        self._next()
        depth, buf = 1, []
        while self.i < len(self.toks):
            t = self.toks[self.i]
            self.i += 1
            if t == "{":
                depth += 1
            elif t == "}":
                depth -= 1
                if depth == 0:
                    return "".join(buf)
            buf.append(t)
        raise self._err("수식에서 '{'가 닫히지 않았어요")

    def item(self) -> str:
        t = self._next()
        if t == "{":
            lefts = self.lefts
            inner = self.expr("}")
            self._next()
            if self.lefts != lefts:
                raise self._err("\\left와 \\right가 같은 중괄호 안에서 짝을 이루지 않아요")
            return "{" + inner + "}"
        if t in ("^", "_"):
            return f"{t}{{{self.arg()}}}"
        if t == "'":
            return "prime"
        if t.startswith("\\"):
            return self.command(t[1:])
        return t

    def command(self, name: str) -> str:
        if name == "\\":
            return "#"
        if name == "hwp":
            return self.raw()
        if name in _DROP:
            return ""
        if name in _DROP_WITH_ARG:
            self.raw()
            return ""
        if name in ("frac", "dfrac", "tfrac"):
            a = self.arg()
            b = self.arg()
            return f"{{{a}}} over {{{b}}}"
        if name == "binom":
            a = self.arg()
            b = self.arg()
            return f"{{{a}}} choose {{{b}}}"
        if name == "sqrt":
            if self._peek() == "[":
                self._next()
                idx = []
                while self._peek() not in ("]", None):
                    idx.append(self.item())
                if self._next() != "]":
                    raise self._err("\\sqrt[ 의 ']'가 없어요")
                return f"root {{{' '.join(idx)}}} of {{{self.arg()}}}"
            return f"sqrt {{{self.arg()}}}"
        if name in _ACCENTS:
            return f"{{{_ACCENTS[name]} {{{self.arg()}}}}}"
        if name in _TEXTS:  # rm은 뒤 전체를 바꾸는 스위치라 it로 되돌린다
            text = re.sub(r"\\[,;:! ]|~", " ", self.raw()).replace('"', "'")
            return 'rm "' + text + '" it'
        if name in ("mathrm", "mathsf"):
            return f"rm {{{self.arg()}}} it"
        if name in ("mathbf", "boldsymbol", "bm"):
            return f"bold {{{self.arg()}}}"
        if name == "mathit":
            return f"it {{{self.arg()}}}"
        if name in ("mathbb", "mathcal", "mathscr", "mathfrak"):
            self.warnings.append(f"\\{name}(특수 글꼴)는 한글 수식에 없어 굵은 로만체로 바꿨어요.")
            return f"rm {{bold {{{self.arg()}}}}} it"
        if name in ("left", "right") or name in _SIZERS:
            d = self._next()
            if d is None:
                raise self._err(f"\\{name} 뒤에 괄호가 없어요")
            sym = _DELIMS.get(d)
            if sym is None:
                self.warnings.append(f"괄호 {d}는 한글 수식에서 확인되지 않아 그대로 넣었어요.")
                sym = d.lstrip("\\")
            if name == "left":
                self.lefts += 1
                return f"LEFT {sym}"
            if name == "right":
                self.lefts -= 1
                return f"RIGHT {sym}"
            return sym
        if name == "begin":
            env = self.raw().strip()
            if env == "array":
                self.raw()  # 열 정렬 지정은 버림
            body = self.expr("\\end")
            self._next()
            end_env = self.raw().strip()
            if end_env != env:
                raise self._err(f"\\begin{{{env}}}와 \\end{{{end_env}}}가 짝이 맞지 않아요")
            hw = _ENVS.get(env)
            if hw is None:
                self.warnings.append(f"{env} 환경은 한글 수식에 없어 행렬(matrix)로 바꿨어요.")
                hw = "matrix"
            return f"{hw}{{{body}}}"
        if name == "end":
            raise self._err("짝이 없는 \\end가 있어요")
        if name in SYMBOLS:
            return SYMBOLS[name]
        if self._peek() == "{":  # 모르는 명령이 인자를 가지면 이름은 버리고 인자만 남긴다
            self.warnings.append(f"\\{name}는 한글 수식에서 지원하지 않아 내용만 남겼어요.")
            return "{" + self.arg() + "}"
        self.warnings.append(f"\\{name}는 한글 수식에서 지원하지 않아 글자로 남겼어요.")
        return f'rm "{name}" it'


HWP_TOKEN = re.compile(r'"[^"]*"|[A-Za-z]+|\d+(?:\.\d+)?|->|<-|<<|>>|<=|>=|!=|\+-|-\+|\|\||\s+|.', re.S)

_INV: dict[str, str] = {}
for _k, _v in SYMBOLS.items():
    if re.fullmatch(r"[A-Za-z]+|->|<-|<<|>>|\+-|-\+|\|\|", _v) and _v not in _INV:
        _INV[_v] = "\\" + _k
_INV.update({g: "\\" + g for g in _UPPER_GREEK})
_INV.update({"lbrace": "\\{", "rbrace": "\\}", "<=": "\\le", ">=": "\\ge", "!=": "\\neq", "inf": "\\infty",
             "->": "\\to", "||": "\\|", "vert": "|"})
_LOWER_SKIP = set(_GREEK)
_PREFIX = {"sqrt": "\\sqrt", "hat": "\\hat", "bar": "\\bar", "overline": "\\overline", "tilde": "\\tilde",
           "vec": "\\vec", "dot": "\\dot", "ddot": "\\ddot", "under": "\\underline", "rm": "\\mathrm",
           "it": "\\mathit", "bold": "\\mathbf"}
_ENV_INV = {"matrix": "matrix", "pmatrix": "pmatrix", "bmatrix": "bmatrix", "dmatrix": "vmatrix",
            "cases": "cases", "eqalign": "aligned", "pile": "matrix"}
# 한글은 장식 단어 뒤에 글자를 붙여 써도(barU) 장식으로 그린다
_GLUED_ACCENTS = ("ddot", "tilde", "hat", "bar", "vec", "dot")
_DELIM_INV = {"lbrace": "\\{", "rbrace": "\\}", "langle": "\\langle", "rangle": "\\rangle", "||": "\\|"}


def hwp_to_latex(script: str) -> str:
    return _ToLatex(script).seq(None)


class _ToLatex:
    def __init__(self, s: str):
        self.toks = [t for t in HWP_TOKEN.findall(s) if not t.isspace()]
        self.i = 0

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self):
        t = self._peek()
        self.i += 1
        return t

    def seq(self, closing: str | None) -> str:
        atoms: list[str] = []
        while True:
            t = self._peek()
            if t is None or t == closing:
                break
            if t == "}":  # 짝 없는 } — 한글은 관대하게 넘김
                self._next()
                continue
            if t in ("_", "^") or t.lower() in ("from", "to"):
                self._next()
                arg = self.atom()
                t = {"from": "_", "to": "^"}.get(t.lower(), t)
                if atoms:
                    atoms[-1] += f"{t}{{{arg}}}"
                else:
                    atoms.append(f"{{}}{t}{{{arg}}}")
                continue
            if t.lower() in ("over", "atop", "choose", "smallover"):
                self._next()
                left = atoms.pop() if atoms else ""
                right = self.atom()
                kind = t.lower()
                atoms.append(f"\\frac{{{left}}}{{{right}}}" if kind == "over"
                             else f"\\tfrac{{{left}}}{{{right}}}" if kind == "smallover"
                             else f"\\binom{{{left}}}{{{right}}}" if kind == "choose"
                             else f"\\genfrac{{}}{{}}{{0pt}}{{}}{{{left}}}{{{right}}}")
                continue
            a = self.atom()
            if a:  # 글꼴 모드 전환(it 등)은 빈 글자 → 첨자가 그 앞 요소에 붙도록 넣지 않음
                atoms.append(a)
        return " ".join(a for a in atoms if a)

    def atom(self) -> str:
        t = self._next()
        if t is None:
            return ""
        if t == "{":
            inner = self.seq("}")
            self._next()
            return inner
        if t.startswith('"'):
            return f"\\text{{{t[1:-1]}}}"
        if t in ("LEFT", "left", "RIGHT", "right"):
            d = self._next() or "."
            return ("\\left" if t.lower() == "left" else "\\right") + _DELIM_INV.get(d, d)
        if t == "root":
            n = self.atom()
            if self._peek() == "of":
                self._next()
            return f"\\sqrt[{n}]{{{self.atom()}}}"
        low = t.lower()
        nxt = self._peek() or ""
        if low == "rm" and nxt.isalnum() and nxt.lower() != "it":  # rm SSE it
            words = []
            while (self._peek() or "").isalnum() and self._peek().lower() != "it":
                words.append(self._next())
            return "\\mathrm{" + "".join(words) + "}"
        if low == "rm" and nxt.startswith('"'):
            return f"\\text{{{self._next()[1:-1]}}}"
        if low in ("rm", "it") and nxt != "{":
            return ""  # 글꼴 모드 전환만 하는 단어
        if low == "rm" and self._peek() == "{":  # 로만체 안 글자는 예약어로 바꾸지 않음 (rm {max} → \mathrm{max})
            self._next()
            raw = []
            while self._peek() not in (None, "}"):
                raw.append(self._next())
            self._next()
            return "\\mathrm{" + "".join(raw) + "}"
        if low in _PREFIX and t.isalpha():
            return f"{_PREFIX[low]}{{{self.atom()}}}"
        if low in _ENV_INV and self._peek() == "{":
            self._next()
            body = self.seq("}")
            self._next()
            env = _ENV_INV[low]
            return f"\\begin{{{env}}}{body}\\end{{{env}}}"
        if t == "`":
            return "\\,"
        if t == "~":
            return "\\;"
        if t == "#":
            return "\\\\"
        if t in _INV:
            return _INV[t]
        if t.isalpha() and low in _INV and low not in _LOWER_SKIP:
            return _INV[low]
        for kw in _GLUED_ACCENTS:
            if t.isalpha() and low.startswith(kw) and len(t) > len(kw):
                return f"{_PREFIX[kw]}{{{t[len(kw):]}}}"
        return t
