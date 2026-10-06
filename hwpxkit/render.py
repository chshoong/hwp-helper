"""보고서 마크다운 → HWPX 요소. 서식은 견본 카탈로그에서만 가져온다(견본 복제).

번호(표·그림)는 먼저 전체를 훑어 매기므로, 뒤에 나오는 그림도 [@fig:x]로 앞에서 참조할 수 있다.
"""
from __future__ import annotations

import copy
import io
import unicodedata
from collections import Counter
from pathlib import Path

from lxml import etree
from PIL import Image

from . import shapes
from .body import IdAllocator, section_of, strip_lineseg
from .eqsize import estimate
from .equation import EquationError, latex_to_hwp
from .header import Header
from .layout import distribute, fit_image, page_geometry
from .mdparse import BULLETS, Bullet, Figure, Heading, Math, PageBreak, Para, Span, Table, parse, parse_inline
from .ns import q
from .package import Package
from .samples import EQ_NUMBER, Catalog, ParaStyle

_SYMBOL = {1: "□", 2: "○", 3: "-", 4: "·"}


class RenderError(ValueError):
    """렌더링할 수 없는 내용. 메시지는 사용자용 한국어."""


class Renderer:
    def __init__(self, pkg: Package, catalog: Catalog, *, base_dir: Path = Path("."),
                 start: dict[str, int] | None = None):
        self.pkg = pkg
        self._start = start or {}  # 넣을 자리 앞에 이미 있는 캡션 수 {"tbl": n, "fig": n}
        self.cat = catalog
        self.h = Header(pkg)
        self.base_dir = Path(base_dir)
        self.geo = page_geometry(pkg)
        self.ids = IdAllocator(pkg)
        self.labels: dict[str, str] = {}
        self._warnings: list[str] = []
        self._numbers: dict[int, str] = {}
        self._counts: dict[int, int] = {}
        self._page_break = False
        self._last_blank = True
        self.equation_count = 0

    @property
    def warnings(self) -> list[str]:
        return list(dict.fromkeys(self._warnings))

    def build(self, blocks) -> list[etree._Element]:
        self._assign_numbers(blocks)
        out: list[etree._Element] = []
        for b in blocks:
            out.extend(self._block(b))
        for el in out:
            strip_lineseg(el)
        return out

    # 번호 -----------------------------------------------------------------
    def _fmt(self, kind: str) -> str:
        return {"tbl": self.cat.tbl_label, "fig": self.cat.fig_label, "eq": self.cat.eq_label}[kind]

    def _assign_numbers(self, blocks) -> None:
        chapter = 0
        counters: Counter = Counter({k: n for k, n in self._start.items() if "{c}" not in self._fmt(k)})
        for b in blocks:
            if isinstance(b, Heading) and b.level == 1:
                chapter += 1
                for kind in list(counters):
                    if "{c}" in self._fmt(kind):
                        counters[kind] = 0
            kind = ("tbl" if isinstance(b, Table) else "fig" if isinstance(b, Figure)
                    else "eq" if isinstance(b, Math) else None)
            if kind is None:
                continue
            counters[kind] += 1
            text = self._fmt(kind).format(c=max(chapter, 1), n=counters[kind])
            self._numbers[id(b)] = text
            self._counts[id(b)] = counters[kind]
            if b.label:
                if b.label in self.labels:
                    raise RenderError(f"같은 이름표가 두 번 쓰였어요: #{b.label}")
                self.labels[b.label] = text

    # 블록 -----------------------------------------------------------------
    def _block(self, b) -> list[etree._Element]:
        if isinstance(b, Heading):
            return self._para(f"h{min(b.level, 5)}", b.spans)
        if isinstance(b, Bullet):
            return self._bullet(b)
        if isinstance(b, Para):
            return self._para("body", b.spans)
        if isinstance(b, PageBreak):
            self._page_break = True
            return []
        if isinstance(b, Table):
            return self._table(b)
        if isinstance(b, Figure):
            return self._figure(b)
        if isinstance(b, Math):
            return self._math_block(b)
        raise RenderError(f"알 수 없는 블록이에요: {b!r}")

    def _bullet(self, b: Bullet) -> list[etree._Element]:
        role = f"bullet{b.level}"
        st = self.cat.require(role)
        spans = list(b.spans)
        if not st.auto_bullet:
            exact = role in self.cat.paras and st.example[:1] in BULLETS
            sym = st.example[0] if exact else _SYMBOL[b.level]
            spans = [Span("text", sym + " ")] + spans
        return self._para(role, spans, style=st)

    def _para(self, role: str, spans, style: ParaStyle | None = None) -> list[etree._Element]:
        st = style or self.cat.require(role)
        out = []
        if st.spacer is not None and not self._last_blank:
            out.append(self._make_p(st.spacer, []))
        out.append(self._make_p(st, spans))
        self._last_blank = False
        return out

    def _make_p(self, st: ParaStyle, spans) -> etree._Element:
        p = etree.Element(q("hp:p"), {"id": "0", "paraPrIDRef": st.para_pr, "styleIDRef": st.style,
                                      "pageBreak": "0", "columnBreak": "0", "merged": "0"})
        self._take_page_break(p)
        self._fill_runs(p, st.char_pr, spans)
        return p

    def _take_page_break(self, p: etree._Element) -> None:
        if self._page_break:
            p.set("pageBreak", "1")
            self._page_break = False

    def _fill_runs(self, p: etree._Element, base_char: str, spans) -> None:
        last_cid, last_t = None, None
        for sp in spans:
            if sp.kind == "math":
                run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": base_char})
                run.append(self._equation(sp.text, base_char))
                last_cid, last_t = None, None
                continue
            text = self._span_text(sp)
            if not text:
                continue
            cid = base_char
            if sp.bold or sp.italic or sp.color:
                cid = self.h.derive_charpr(base_char, bold=True if sp.bold else None,
                                           italic=True if sp.italic else None, color=sp.color)
            if cid == last_cid:
                last_t.text += text
                continue
            run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": cid})
            last_t = etree.SubElement(run, q("hp:t"))
            last_t.text = text
            last_cid = cid
        if not len(p):
            etree.SubElement(p, q("hp:run"), {"charPrIDRef": base_char})

    def _script(self, latex: str) -> str:
        self.equation_count += 1
        try:
            script, warnings = latex_to_hwp(latex)
        except EquationError as e:
            raise RenderError(f"{self.equation_count}번째 수식을 읽지 못했어요 — {e}") from None
        self._warnings.extend(warnings)
        return script

    def _equation(self, latex: str, char_pr: str) -> etree._Element:
        script = self._script(latex)
        base_unit = int(self.h.get("charPr", char_pr).get("height", "1000"))
        w, h, base = estimate(script, base_unit)
        if self.cat.equation is not None:
            eq = copy.deepcopy(self.cat.equation)
            shapes.set_equation(eq, script, w, h, base, base_unit)
        else:
            eq = shapes.new_equation(script, w, h, base, base_unit)
        eq.set("id", self.ids.take())
        return eq

    def _span_text(self, sp: Span) -> str:
        if sp.kind == "text":
            return sp.text
        if sp.kind == "ref":
            if sp.text in self.labels:
                return self.labels[sp.text]
            self._warnings.append(f"[@{sp.text}] 이름표를 찾지 못해 글자 그대로 두었어요.")
            return f"[@{sp.text}]"
        return sp.text

    # 표·그림 (Task 5·6) ---------------------------------------------------
    def _caption(self, kind: str, b) -> tuple[str, tuple | None]:
        """캡션 글과 한글 자동 번호 정보. 장별 번호({c})는 자동 번호로 못 만들어 글자로 둔다."""
        text = f"{self._numbers[id(b)]} {b.caption}".strip()
        fmt = self._fmt(kind)
        if "{c}" in fmt or fmt.count("{n}") != 1:
            return text, None
        before, after = fmt.split("{n}")
        rest = f"{after} {b.caption}" if b.caption else after
        return text, (before, self._counts[id(b)], "TABLE" if kind == "tbl" else "PICTURE", rest)

    def _caption_style(self, role: str) -> ParaStyle:
        """캡션 문단 서식: 양식의 캡션 견본 → 양식의 '캡션' 스타일 → 대신 쓸 견본."""
        if role in self.cat.paras:
            return self.cat.paras[role]
        sid = self.h.style_id("캡션")
        if sid is not None:
            e = self.h.get("style", sid)
            return ParaStyle(e.get("paraPrIDRef"), sid, e.get("charPrIDRef"))
        return self.cat.require(role)

    def _new_caption(self, role: str, text: str, auto, width: int, side: str) -> etree._Element:
        st = self._caption_style(role)
        return shapes.new_caption(text, width, st.para_pr, st.style, st.char_pr, side=side, auto=auto)

    def _table_text_style(self) -> ParaStyle:
        """기본 표의 칸 글자 서식: 본문 견본 → 양식의 '표내용' 스타일 → 바탕글."""
        if "body" in self.cat.paras:
            return self.cat.paras["body"]
        for name in ("표내용", "바탕글"):
            sid = self.h.style_id(name)
            if sid is not None:
                e = self.h.get("style", sid)
                return ParaStyle(e.get("paraPrIDRef"), sid, e.get("charPrIDRef"))
        return self.cat.require("body")

    def _table(self, b: Table) -> list[etree._Element]:
        caption = self._caption("tbl", b) if (b.caption or b.label) else None
        try:
            tp = self._table_para(b, caption)
        except RenderError as e:
            raise RenderError(f"{b.lineno}번째 줄 표: {e}") from None
        self._take_page_break(tp)
        self._last_blank = False
        return [tp]

    def _table_para(self, b: Table, caption) -> etree._Element:
        """표 문단. 캡션은 표에 붙은 한글 캡션(hp:caption, 위쪽)으로 넣는다."""
        rows = b.rows
        n_rows, n_cols = len(rows), len(rows[0])
        spans, covered = _merge_marks(rows)
        if b.widths is not None and len(b.widths) != n_cols:
            raise RenderError(f"열 비율이 {len(b.widths)}개인데 열은 {n_cols}개예요.")
        weights = b.widths or [
            min(20, max(2, max(_display_width(rows[r][c]) for r in range(n_rows) if (r, c) not in covered)))
            for c in range(n_cols)]
        if self.cat.table_para is not None:
            p = copy.deepcopy(self.cat.table_para)
            tbl = next(p.iter(q("hp:tbl")))
            trs = tbl.findall(q("hp:tr"))
            head_tc = trs[0].find(q("hp:tc"))
            body_tc = _clean_cell(trs[1:])
            if body_tc is None:
                body_tc = (trs[1] if len(trs) > 1 else trs[0]).find(q("hp:tc"))
            for tr in trs:
                tbl.remove(tr)
            _clean_object_para(p, tbl)
        else:
            p, tbl, head_tc, body_tc = shapes.new_table_para(self.h, self._table_text_style(), self.geo.text_width)
        total = int(tbl.find(q("hp:sz")).get("width"))
        cap = tbl.find(q("hp:caption"))
        if cap is not None:
            if caption:
                shapes.set_caption(cap, caption[0], total, caption[1])
            else:
                tbl.remove(cap)
        elif caption:
            shapes.attach_caption(tbl, self._new_caption("caption_tbl", *caption, total, "TOP"))
        cols = distribute(total, weights)
        row_h = int(body_tc.find(q("hp:cellSz")).get("height"))
        tbl.set("rowCnt", str(n_rows))
        tbl.set("colCnt", str(n_cols))
        tbl.find(q("hp:sz")).set("height", str(row_h * n_rows))
        for r in range(n_rows):
            tr = etree.SubElement(tbl, q("hp:tr"))
            for c in range(n_cols):
                if (r, c) in covered:
                    continue
                rs, cs = spans[(r, c)]
                tc = copy.deepcopy(head_tc if r == 0 else body_tc)
                tc.find(q("hp:cellAddr")).attrib.update({"colAddr": str(c), "rowAddr": str(r)})
                tc.find(q("hp:cellSpan")).attrib.update({"colSpan": str(cs), "rowSpan": str(rs)})
                tc.find(q("hp:cellSz")).attrib.update({"width": str(sum(cols[c:c + cs])), "height": str(row_h * rs)})
                self._fill_cell(tc, rows[r][c])
                tr.append(tc)
        self.ids.refresh(p)
        return p

    def _fill_cell(self, tc: etree._Element, text: str) -> None:
        sub = tc.find(q("hp:subList"))
        tmpl = sub.find(q("hp:p"))
        char = _cell_char(tmpl)
        attrs = dict(tmpl.attrib)
        for old in list(sub):
            sub.remove(old)
        for line in text.split("<br>"):
            p = etree.SubElement(sub, q("hp:p"), attrs)
            self._fill_runs(p, char, parse_inline(line.strip()))

    def _math_block(self, b: Math) -> list[etree._Element]:
        number = self._numbers[id(b)]
        body = self.cat.require("body")
        if self.cat.eq_table_para is not None:
            p = copy.deepcopy(self.cat.eq_table_para)
            tbl = next(p.iter(q("hp:tbl")))
            _clean_object_para(p, tbl)
            old = next(tbl.iter(q("hp:equation")))
            run = old.getparent()
            cell_char = run.get("charPrIDRef")
            run.replace(old, self._equation(b.latex, cell_char))
            num_tc = next(tc for tc in tbl.iter(q("hp:tc")) if EQ_NUMBER.match("".join(tc.itertext()).strip()))
            self._fill_cell(num_tc, number)
        else:
            eq = self._equation(b.latex, body.char_pr)
            p = shapes.new_eq_table_para(self.h, body, self.geo.text_width, eq, number)
        self._take_page_break(p)
        self.ids.refresh(p)
        self._last_blank = False
        return [p]

    def _figure(self, b: Figure) -> list[etree._Element]:
        path = self.base_dir / b.path
        if path.is_file():
            raw = path.read_bytes()
        elif b.path.replace("\\", "/") in self.pkg.names():
            raw = self.pkg.read(b.path.replace("\\", "/"))  # read 결과의 BinData/… 경로를 다시 넣는 경우
        else:
            raise RenderError(f"그림 파일을 찾을 수 없어요: {b.path}")
        try:
            with Image.open(io.BytesIO(raw)) as im:
                px_w, px_h = im.size
                fmt = (im.format or "").upper()
                if fmt in ("PNG", "JPEG"):
                    data, ext = raw, ("png" if fmt == "PNG" else "jpg")
                else:
                    buf = io.BytesIO()
                    im.save(buf, "PNG")
                    data, ext = buf.getvalue(), "png"
        except OSError as e:
            raise RenderError(f"그림 파일을 읽지 못했어요: {b.path}") from e
        bid = self.pkg.add_bin(data, ext)
        w, h = fit_image(px_w, px_h, self.geo.text_width, ratio=b.width,
                         max_height_hu=int(self.geo.text_height * 0.85))
        caption = self._caption("fig", b)
        cap = None
        if self.cat.figure_para is not None:
            p = copy.deepcopy(self.cat.figure_para)
            pic = next(p.iter(q("hp:pic")))
            _clean_object_para(p, pic)
            shapes.set_picture(pic, bid, px_w, px_h, w, h, path.name)
            cap = pic.find(q("hp:caption"))
            if cap is not None:
                shapes.set_caption(cap, caption[0], w, caption[1])
        else:
            st = self.cat.require("caption_fig")
            p = etree.Element(q("hp:p"), {"id": "0", "paraPrIDRef": st.para_pr, "styleIDRef": st.style,
                                          "pageBreak": "0", "columnBreak": "0", "merged": "0"})
            run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": st.char_pr})
            run.append(shapes.new_picture(bid, px_w, px_h, w, h, path.name))
            etree.SubElement(run, q("hp:t"))
        if cap is None:
            pic = next(p.iter(q("hp:pic")))
            shapes.attach_caption(pic, self._new_caption("caption_fig", *caption, w, "BOTTOM"))
        self._take_page_break(p)
        self.ids.refresh(p)
        self._last_blank = False
        return [p]


def _display_width(text: str) -> int:
    """열 폭 비율용 글자 너비 (한글 등 전각 2, 나머지 1)의 절반."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text) // 2


def _clean_cell(rows) -> etree._Element | None:
    """본문 칸 견본: 링크·필드 같은 컨트롤이 없는 칸 (하이퍼링크 글자모양을 옮기지 않으려고). 글이 있는 칸을 먼저 고른다."""
    plain = [tc for tr in rows for tc in tr.findall(q("hp:tc")) if next(tc.iter(q("hp:ctrl")), None) is None]
    return next((tc for tc in plain if "".join(tc.itertext()).strip()), plain[0] if plain else None)


def _cell_char(tmpl: etree._Element) -> str:
    runs = tmpl.findall(q("hp:run"))
    return next((r.get("charPrIDRef") for r in runs if r.find(q("hp:t")) is not None),
                runs[0].get("charPrIDRef") if runs else "0")


def _clean_object_para(p: etree._Element, obj: etree._Element) -> None:
    """복제한 견본 문단에서 obj가 든 run만, 그 run에는 obj와 빈 글자만 남긴다."""
    run = obj.getparent()
    for r in list(p):
        if r.tag == q("hp:run") and r is not run:
            p.remove(r)
    for ch in list(run):
        if ch is not obj:
            run.remove(ch)
    etree.SubElement(run, q("hp:t"))


def _merge_marks(rows: list[list[str]]):
    """'^^'(위와 병합), '<<'(왼쪽과 병합)를 해석한다."""
    owner: dict = {}
    spans: dict = {}
    covered: set = set()
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            v = value.strip()
            if v == "^^":
                if r == 0:
                    raise RenderError(f"표 1행 {c + 1}열: 맨 윗줄에는 ^^(위와 병합)를 쓸 수 없어요.")
                anchor = owner[(r - 1, c)]
            elif v == "<<":
                if c == 0:
                    raise RenderError(f"표 {r + 1}행 1열: 맨 왼쪽 칸에는 <<(왼쪽과 병합)를 쓸 수 없어요.")
                anchor = owner[(r, c - 1)]
            else:
                owner[(r, c)] = (r, c)
                spans[(r, c)] = (1, 1)
                continue
            owner[(r, c)] = anchor
            covered.add((r, c))
            ar, ac = anchor
            rs, cs = spans[anchor]
            spans[anchor] = (max(rs, r - ar + 1), max(cs, c - ac + 1))
    for (ar, ac), (rs, cs) in spans.items():
        for i in range(ar, ar + rs):
            for j in range(ac, ac + cs):
                if owner.get((i, j)) != (ar, ac):
                    raise RenderError(f"표 {ar + 1}행 {ac + 1}열의 병합 영역이 직사각형이 아니에요. ^^와 <<를 확인해 주세요.")
    return spans, covered


def _keep_section_controls(first: etree._Element) -> None:
    """첫 문단에서 구역 설정(secPr)과 컨트롤(단·머리말 등)만 남긴다."""
    for run in first.findall(q("hp:run")):
        for ch in list(run):
            if ch.tag not in (q("hp:secPr"), q("hp:ctrl")):
                run.remove(ch)
        if len(run) == 0:
            first.remove(run)
    strip_lineseg(first)


def _missing_samples(blocks, catalog: Catalog) -> list[str]:
    """append·replace는 넣을 문서 자체에서 견본을 배우므로, 쓰인 역할 중 견본이 없는 것을 찾는다."""
    from .samples import ROLE_KO
    need: dict[str, bool] = {}
    for b in blocks:
        if isinstance(b, Heading):
            need[ROLE_KO.get(f"h{b.level}", f"h{b.level}")] = f"h{b.level}" in catalog.paras
        elif isinstance(b, Bullet):
            need[ROLE_KO.get(f"bullet{b.level}", "글머리")] = f"bullet{b.level}" in catalog.paras
        elif isinstance(b, Table):
            need["표"] = catalog.table_para is not None
            if b.caption:
                need[ROLE_KO.get("caption_tbl", "표 제목")] = "caption_tbl" in catalog.paras
        elif isinstance(b, Figure):
            need["그림"] = catalog.figure_para is not None
        elif isinstance(b, Math):
            need["수식"] = catalog.equation is not None
    return [name for name, ok in need.items() if not ok]


def _caption_counts(paragraphs) -> dict[str, int]:
    """문단들 안에 캡션 달린 표·그림이 몇 개인가 (한글 자동 번호가 세는 것)."""
    out = {"tbl": 0, "fig": 0}
    for p in paragraphs:
        for kind, tag in (("tbl", "hp:tbl"), ("fig", "hp:pic")):
            out[kind] += sum(1 for el in p.iter(q(tag)) if el.find(q("hp:caption")) is not None)
    return out


def _unnumber_captionless(pkg: Package) -> None:
    """캡션 없는 표·그림(표지, 작성 요령 상자, 수식 번호 표 등)은 한글 자동 번호를 세지 않게 한다.
    그대로 두면 첫 캡션 표가 '표 2'처럼 밀린다. 화면에는 변화가 없다."""
    for sec in pkg.section_names():
        for el in pkg.edit(sec).iter(q("hp:tbl"), q("hp:pic")):
            if el.find(q("hp:caption")) is None and el.get("numberingType") in ("TABLE", "PICTURE"):
                el.set("numberingType", "NONE")


def render_into(pkg: Package, catalog: Catalog, md: str, *, mode: str = "new",
                replace: tuple[int, int] | None = None, base_dir: Path = Path("."),
                section: str | None = None) -> list[str]:
    """보고서 마크다운을 문서에 넣고 경고 목록을 돌려준다."""
    blocks = parse(md)
    name = section_of(pkg, section)
    count = sum(1 for p in pkg.xml(name) if p.tag == q("hp:p"))
    if replace is not None:
        start, end = replace
        if start < 1:
            raise RenderError("첫 문단(0번)에는 쪽 설정이 들어 있어 바꿀 수 없어요. 1번부터 지정해 주세요.")
        if not start < end <= count:
            raise RenderError(f"바꿀 범위 {start}:{end}가 문서 문단 범위(1~{count})를 벗어나요.")
    elif mode not in ("new", "append"):
        raise RenderError(f"알 수 없는 넣기 방식이에요: {mode} (가능: new, append)")
    tops = [p for p in pkg.xml(name) if p.tag == q("hp:p")]
    before = [p for sec in pkg.section_names()[:pkg.section_names().index(name)] for p in pkg.xml(sec)]
    before += tops[:replace[0]] if replace is not None else tops if mode == "append" else tops[:1]
    r = Renderer(pkg, catalog, base_dir=base_dir, start=_caption_counts(before))
    els = r.build(blocks)
    if replace is not None or mode == "append":
        missing = _missing_samples(blocks, catalog)
        if missing:
            hint = (" 원래 양식(또는 프리셋)으로 전체 내용을 새로 만들면 양식 서식 그대로 나와요."
                    if mode == "append" and replace is None else "")
            r._warnings.append(f"이 문서에는 {'·'.join(missing)} 견본이 없어 기본 서식으로 넣었어요.{hint}")
    root = pkg.edit(name)
    tops = [p for p in root if p.tag == q("hp:p")]
    if replace is not None:
        start, end = replace
        idx = root.index(tops[start])
        for k, el in enumerate(els):
            root.insert(idx + k, el)
        for p in tops[start:end]:
            root.remove(p)
    elif mode == "new":
        first = tops[0]
        for p in tops[1:]:
            root.remove(p)
        _keep_section_controls(first)
        if els:
            head = els.pop(0)
            for attr in ("paraPrIDRef", "styleIDRef", "pageBreak"):
                first.set(attr, head.get(attr))
            for run in head.findall(q("hp:run")):
                first.append(run)
        for el in els:
            root.append(el)
    else:
        for el in els:
            root.append(el)
    _unnumber_captionless(pkg)
    return r.warnings
