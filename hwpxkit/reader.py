"""HWPX → 보고서 마크다운. 이어쓰기·부분 수정·검토에 쓴다.

anchors=True면 블록마다 <!-- @n --> (n = 최상위 문단 번호)를 붙인다. render --replace a:b 와 같은 번호다.
수식은 한글 수식 문법 그대로 $…$ 로 둔다 (계획 3에서 LaTeX로 바꿈).
"""
from __future__ import annotations

import re

from lxml import etree

from .body import all_text, contains, t_text, top_paragraphs
from .header import Header
from .ns import q
from .package import Package
from .equation import hwp_to_latex
from .samples import EQ_NUMBER, bullet_chars, classify, heading_levels

_HEAD_LEVEL = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5}
_SYMBOL = {1: "□", 2: "○", 3: "-", 4: "·"}
_LABEL = re.compile(r"^\[?\s*(표|그림)\s*[\d부A-Z]*\s*[-–.]?\s*\d*\s*\]?\s*")


def to_markdown(pkg: Package, *, anchors: bool = False, section: str | None = None) -> str:
    ctx = _Ctx(pkg)
    tops = top_paragraphs(pkg, section)
    ctx.levels = heading_levels(tops)
    out: list[str] = []
    skip = False
    for i, p in enumerate(tops):
        if skip:  # 앞 그림의 캡션으로 흡수한 문단
            skip = False
            continue
        nxt = tops[i + 1] if i + 1 < len(tops) else None
        lines, skip = ctx.paragraph(p, nxt)
        if not lines:
            continue
        if anchors:
            out.append(f"<!-- @{i} -->")
        out.extend(lines)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


class _Ctx:
    def __init__(self, pkg: Package):
        self.h = Header(pkg)
        self.chars = bullet_chars(self.h)
        self.manifest = pkg.manifest()
        self.levels = None

    def line(self, p: etree._Element) -> tuple[str | None, str]:
        """문단 하나의 마크다운 글 (역할, 글)."""
        text = _inline(p).strip()
        role, st = classify(p, self.h, self.chars, self.levels)
        if role in _HEAD_LEVEL:
            return role, "#" * _HEAD_LEVEL[role] + " " + text
        if role and role.startswith("bullet") and st.auto_bullet:
            return role, f"{_SYMBOL[int(role[-1])]} {text}"
        return role, text

    def cell_line(self, p: etree._Element) -> str:
        """표 칸 안 문단: 제목 기호(#)는 붙이지 않고 자동 글머리 기호만 살린다."""
        text = _inline(p).strip()
        role, st = classify(p, self.h, self.chars)
        if role and role.startswith("bullet") and st.auto_bullet:
            return f"{_SYMBOL[int(role[-1])]} {text}"
        return text

    def paragraph(self, p: etree._Element, nxt: etree._Element | None) -> tuple[list[str], bool]:
        """문단의 마크다운 줄들과, 다음 문단을 그림 캡션으로 흡수했는지 여부."""
        role, text = self.line(p)
        lines = []
        if role == "caption_tbl" and nxt is not None and contains(nxt, "hp:tbl"):
            lines.append("표: " + _LABEL.sub("", text))
        elif text and role != "blank":
            lines.append(text)
        for tbl in _top_objects(p, "hp:tbl"):
            lines += self.table(tbl)
        consumed = False
        for pic in _top_objects(p, "hp:pic"):
            caption = None
            if pic.find(q("hp:caption")) is None and nxt is not None and not consumed:
                nrole, ntext = self.line(nxt)
                if nrole == "caption_fig":
                    caption, consumed = _LABEL.sub("", ntext), True
            lines.append(self.picture(pic, caption))
        return lines, consumed

    def table(self, tbl: etree._Element) -> list[str]:
        rows, cols = int(tbl.get("rowCnt", 0)), int(tbl.get("colCnt", 0))
        if rows == 1 and contains(tbl, "hp:equation"):
            texts = [all_text(tc).strip() for tc in tbl.iter(q("hp:tc"))]
            if any(EQ_NUMBER.match(t) for t in texts):
                script = next(tbl.iter(q("hp:equation"))).findtext(q("hp:script")) or ""
                return [f"$${hwp_to_latex(script)}$$"]
        cap = tbl.find(q("hp:caption"))
        head = ["표: " + _LABEL.sub("", all_text(cap).strip())] if cap is not None and all_text(cap).strip() else []
        grid = [[""] * cols for _ in range(rows)]
        for tr in tbl.findall(q("hp:tr")):
            for tc in tr.findall(q("hp:tc")):
                a, s = tc.find(q("hp:cellAddr")), tc.find(q("hp:cellSpan"))
                r, c = int(a.get("rowAddr")), int(a.get("colAddr"))
                rs, cs = (1, 1) if s is None else (int(s.get("rowSpan")), int(s.get("colSpan")))
                cell = "<br>".join(self.cell_line(cp) for cp in tc.find(q("hp:subList")).findall(q("hp:p")))
                grid[r][c] = cell.replace("|", "｜").strip()
                for i in range(r, r + rs):
                    for j in range(c, c + cs):
                        if (i, j) != (r, c):
                            grid[i][j] = "^^" if j == c else "<<"
        lines = ["| " + " | ".join(row) + " |" for row in grid]
        lines.insert(1, "|" + "---|" * cols)
        return head + lines

    def picture(self, pic: etree._Element, caption: str | None = None) -> str:
        cap = pic.find(q("hp:caption"))
        if caption is None:
            caption = _LABEL.sub("", all_text(cap).strip()) if cap is not None else ""
        img = pic.find(q("hc:img"))
        href = self.manifest.get(img.get("binaryItemIDRef"), "") if img is not None else ""
        return f"![{caption}]({href})"


def _inline(p: etree._Element) -> str:
    parts = []
    for run in p.findall(q("hp:run")):
        for ch in run:
            if ch.tag == q("hp:t"):
                parts.append(t_text(ch))
            elif ch.tag == q("hp:equation"):
                parts.append(f"${hwp_to_latex(ch.findtext(q('hp:script')) or '')}$")
    return "".join(parts)


def _top_objects(p: etree._Element, tag: str) -> list[etree._Element]:
    """문단 p 안의 개체 중 다른 표·그림 안에 들어 있지 않은 것."""
    out = []
    for obj in p.iter(q(tag)):
        a = obj.getparent()
        nested = False
        while a is not None and a is not p:
            if a.tag in (q("hp:tbl"), q("hp:pic")):
                nested = True
                break
            a = a.getparent()
        if not nested:
            out.append(obj)
    return out
