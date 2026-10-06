"""보고서 마크다운 파서 (Claude ↔ 엔진 인터페이스, 설계 5장).

Claude는 XML 대신 이 형식으로 쓴다. 한 줄이 한 문단이고, 빈 줄은 무시한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

BULLETS = {"□": 1, "○": 2, "◦": 2, "❍": 2, "-": 3, "–": 3, "·": 4, "∙": 4, "•": 4}
COLORS = {"파랑": "#0000FF", "빨강": "#FF0000", "검정": "#000000", "초록": "#008000", "회색": "#808080"}


class MarkdownError(ValueError):
    """보고서 마크다운 형식 오류. 메시지는 사용자용 한국어."""


@dataclass(frozen=True)
class Span:
    kind: str  # "text" | "math" | "ref"
    text: str
    bold: bool = False
    italic: bool = False
    color: str | None = None


@dataclass
class Heading:
    level: int
    spans: list[Span]


@dataclass
class Bullet:
    level: int
    spans: list[Span]


@dataclass
class Para:
    spans: list[Span]


@dataclass
class Table:
    rows: list[list[str]]
    caption: str = ""
    label: str | None = None
    widths: list[float] | None = None
    lineno: int = field(default=0, compare=False)


@dataclass
class Figure:
    path: str
    caption: str
    label: str | None = None
    width: float = 1.0


@dataclass
class Math:
    latex: str
    label: str | None = None


@dataclass
class PageBreak:
    pass


@dataclass
class Note:
    """'* 출처…', '※ 참고…' 주석 줄. spans에 기호까지 들어 있다."""
    spans: list[Span]


Block = Heading | Bullet | Para | Table | Figure | Math | PageBreak | Note

_HEADING = re.compile(r"^(#{1,5})\s+(.*)$")
_BULLET = re.compile(r"^([□○◦❍\-–·∙•])\s+(.*)$")
_NOTE = re.compile(r"^([*※])\s+(.*)$")
_FIGURE = re.compile(r"^!\[(.*?)\]\((.+?)\)\s*(\{.*\})?\s*$")
_TABLE_CAPTION = re.compile(r"^표\s*[:：]\s*(.*?)\s*(\{.*\})?\s*$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_MATH_LINE = re.compile(r"^\$\$(.+?)\$\$\s*(\{.*\})?\s*$")
_INLINE = re.compile(
    r"(?<![A-Za-z0-9$\\])\$(?=\S)(?P<math>[^$]*?\S)\$(?!\d)"
    r"|\[@(?P<ref>[\w:-]+)\]"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|(?<![\w*])\*(?P<ital>[^*\s](?:[^*]*[^*\s])?)\*(?![\w*])"
    r"|\[\[색:(?P<color>[^\]]+)\]\](?P<ctext>.*?)\[\[/색\]\]"
)


def parse_inline(s: str) -> list[Span]:
    out: list[Span] = []
    pos = 0
    for m in _INLINE.finditer(s):
        if m.start() > pos:
            out.append(Span("text", s[pos:m.start()]))
        if m.group("math") is not None:
            out.append(Span("math", m.group("math").strip()))
        elif m.group("ref") is not None:
            out.append(Span("ref", m.group("ref")))
        elif m.group("bold") is not None:
            out += [replace(sp, bold=True) for sp in parse_inline(m.group("bold"))]
        elif m.group("ital") is not None:
            out += [replace(sp, italic=True) for sp in parse_inline(m.group("ital"))]
        else:
            color = _color(m.group("color"))
            out += [replace(sp, color=color) for sp in parse_inline(m.group("ctext"))]
        pos = m.end()
    if pos < len(s):
        out.append(Span("text", s[pos:]))
    return [sp for sp in out if sp.text]


def _color(name: str) -> str:
    name = name.strip()
    if name in COLORS:
        return COLORS[name]
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", name):
        return name.upper()
    raise MarkdownError(f"알 수 없는 색 이름이에요: {name} (가능: {', '.join(COLORS)}, #RRGGBB)")


def _attrs(raw: str | None, lineno: int) -> dict:
    """'{#fig:flow width=80% widths=1,2}' → {'label': 'fig:flow', 'width': 0.8, 'widths': [1.0, 2.0]}"""
    out: dict = {}
    if not raw:
        return out
    for tok in raw.strip("{} ").split():
        try:
            if tok.startswith("#"):
                out["label"] = tok[1:]
            elif tok.startswith("width="):
                v = tok[6:]
                out["width"] = float(v[:-1]) / 100 if v.endswith("%") else float(v)
            elif tok.startswith("widths="):
                out["widths"] = [float(x) for x in tok[7:].split(",") if x]
        except ValueError:
            raise MarkdownError(f"{lineno}번째 줄: '{tok}' 값을 숫자로 읽지 못했어요 (예: width=80%, widths=1,2,2).") from None
    return out


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def parse(md: str) -> list[Block]:
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    caption: tuple[str, dict, int] | None = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        lineno = i + 1
        if not line or (line.startswith("<!--") and line.endswith("-->")):
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                if not _TABLE_SEP.match(row):
                    rows.append(_cells(row))
                i += 1
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            text, attrs, _ = caption or ("", {}, 0)
            caption = None
            blocks.append(Table(rows, text, attrs.get("label"), attrs.get("widths"), lineno=lineno))
            continue
        if caption is not None:
            raise MarkdownError(f"{caption[2]}번째 줄 '표: {caption[0]}' 바로 다음에는 표(| … |)가 와야 해요 ({lineno}번째 줄).")
        m = _TABLE_CAPTION.match(line)
        if m:
            caption = (m.group(1), _attrs(m.group(2), lineno), lineno)
            i += 1
            continue
        if line == "---쪽---":
            blocks.append(PageBreak())
            i += 1
            continue
        if line.startswith("$$"):
            closing = line.find("$$", 2)
            if closing != -1 and line[closing + 2:].strip() and not line[closing + 2:].strip().startswith("{"):
                raise MarkdownError(f"{lineno}번째 줄: 문단 수식($$…$$)은 한 줄에 수식만 써 주세요. 설명 글은 다음 줄에 쓰세요.")
            m = _MATH_LINE.match(line)
            if m:
                blocks.append(Math(m.group(1).strip(), _attrs(m.group(2), lineno).get("label")))
                i += 1
                continue
            buf = [line[2:]]
            i += 1
            while i < len(lines) and "$$" not in lines[i]:
                buf.append(lines[i])
                i += 1
            if i >= len(lines):
                raise MarkdownError(f"{lineno}번째 줄에서 $$로 시작한 수식이 닫히지 않았어요.")
            last = lines[i].strip()
            k = last.index("$$")
            buf.append(last[:k])
            blocks.append(Math("\n".join(x.strip() for x in buf).strip(), _attrs(last[k + 2:].strip() or None, i + 1).get("label")))
            i += 1
            continue
        m = _FIGURE.match(line)
        if m:
            attrs = _attrs(m.group(3), lineno)
            blocks.append(Figure(m.group(2).strip(), m.group(1).strip(), attrs.get("label"), attrs.get("width", 1.0)))
        elif (m := _HEADING.match(line)):
            blocks.append(Heading(len(m.group(1)), parse_inline(m.group(2).strip())))
        elif (m := _BULLET.match(line)):
            blocks.append(Bullet(BULLETS[m.group(1)], parse_inline(m.group(2).strip())))
        elif (m := _NOTE.match(line)):
            blocks.append(Note([Span("text", m.group(1) + " ")] + parse_inline(m.group(2).strip())))
        else:
            blocks.append(Para(parse_inline(line)))
        i += 1
    if caption is not None:
        raise MarkdownError(f"{caption[2]}번째 줄 '표: {caption[0]}' 다음에 표가 없어요.")
    return blocks
