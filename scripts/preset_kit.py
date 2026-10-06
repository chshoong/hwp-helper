"""프리셋 제작 도구 (제작 시점에만 쓴다; 엔진 런타임은 이 모듈을 쓰지 않는다).

프리셋은 빈 문서의 기본 서식(글자모양 0, 문단모양 0, 가장 작은 테두리)을 복제해 바꾼 서식으로 견본을 넣고,
한글로 다시 저장해 정규화한다. 글꼴은 한글 기본 설치 글꼴만 쓴다.
"""
from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from hwpxkit import shapes
from hwpxkit.header import LANGS, Header
from hwpxkit.layout import mm_to_hu
from hwpxkit.ns import NS, q
from hwpxkit.package import HEADER, Package

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
_P = {"id": "0", "pageBreak": "0", "columnBreak": "0", "merged": "0"}


def font_id(h: Header, face: str) -> dict[str, str]:
    """face를 7개 언어 fontface에 등록하고 언어별 id를 돌려준다 (이미 있으면 그 id)."""
    root = h.pkg.edit(HEADER)
    ids = {}
    for ff in root.iter(f"{HH}fontface"):
        fonts = ff.findall(f"{HH}font")
        found = next((f for f in fonts if f.get("face") == face), None)
        if found is None:
            found = copy.deepcopy(fonts[0])
            found.set("id", str(max(int(f.get("id")) for f in fonts) + 1))
            found.set("face", face)
            ff.append(found)
            ff.set("fontCnt", str(len(fonts) + 1))
        ids[ff.get("lang")] = found.get("id")
    return ids


def char(h: Header, size_pt: float, *, bold=False, font=None, color=None) -> str:
    cid = h.derive_charpr("0", bold=bold or None, color=color, height=round(size_pt * 100))
    if font:
        ids = font_id(h, font)

        def mutate(e):
            ref = e.find(f"{HH}fontRef")
            for lang in LANGS:
                ref.set(lang.lower(), ids[lang])

        cid = h.derive("charPr", cid, mutate)
    return cid


def _pt_hu(pt: float) -> int:
    return round(pt * 100)


def para(h: Header, *, align="JUSTIFY", left_mm=0.0, indent_mm=0.0, prev_pt=0.0, next_pt=0.0, line=160,
         keep_next=False, bullet=None) -> str:
    def mutate(e):
        e.find(f"{HH}align").set("horizontal", align)
        for m in e.iter(f"{HH}margin"):
            m.find(f"{HC}left").set("value", str(mm_to_hu(left_mm)))
            m.find(f"{HC}intent").set("value", str(mm_to_hu(indent_mm)))
            m.find(f"{HC}prev").set("value", str(_pt_hu(prev_pt)))
            m.find(f"{HC}next").set("value", str(_pt_hu(next_pt)))
        for ls in e.iter(f"{HH}lineSpacing"):
            ls.set("type", "PERCENT")
            ls.set("value", str(line))
        e.find(f"{HH}breakSetting").set("keepWithNext", "1" if keep_next else "0")
        head = e.find(f"{HH}heading")
        if bullet is not None:
            head.attrib.update({"type": "BULLET", "idRef": bullet, "level": "0"})
        else:
            head.attrib.update({"type": "NONE", "idRef": "0", "level": "0"})

    return h.derive("paraPr", "0", mutate)


def add_bullets(h: Header, chars: list[str]) -> list[str]:
    root = h.pkg.edit(HEADER)
    ref = root.find(f"{HH}refList")
    bullets = ref.find(f"{HH}bullets")
    if bullets is None:
        bullets = etree.Element(f"{HH}bullets", {"itemCnt": "0"})
        ref.insert(list(ref).index(ref.find(f"{HH}numberings")) + 1, bullets)
    out = []
    for ch in chars:
        found = next((b for b in bullets.findall(f"{HH}bullet") if b.get("char") == ch), None)
        if found is None:
            bid = str(max((int(b.get("id")) for b in bullets.findall(f"{HH}bullet")), default=0) + 1)
            found = etree.SubElement(bullets, f"{HH}bullet", {"id": bid, "char": ch, "useImage": "0"})
            etree.SubElement(found, f"{HH}paraHead", {
                "level": "0", "align": "LEFT", "useInstWidth": "0", "autoIndent": "1", "widthAdjust": "0",
                "textOffsetType": "PERCENT", "textOffset": "50", "numFormat": "DIGIT",
                "charPrIDRef": "4294967295", "checkable": "0"})
            bullets.set("itemCnt", str(len(bullets.findall(f"{HH}bullet"))))
        out.append(found.get("id"))
    return out


def fill_border(h: Header, color: str) -> str:
    """실선 0.12mm 테두리 + 배경색 (color='none'이면 배경 없음)."""
    base = shapes.solid_border_fill(h)

    def mutate(e):
        brush = e.find(f"{HC}fillBrush")
        if brush is None:
            brush = etree.SubElement(e, f"{HC}fillBrush")
        win = brush.find(f"{HC}winBrush")
        if win is None:
            win = etree.SubElement(brush, f"{HC}winBrush", {"hatchColor": "#999999", "alpha": "0"})
        win.set("faceColor", color)

    return h.derive("borderFill", base, mutate)


def no_border(h: Header) -> str:
    return shapes.no_border_fill(h)


def set_page(pkg: Package, *, top, bottom, left, right, header, footer) -> None:
    sec = pkg.edit(pkg.section_names()[0])
    margin = next(sec.iter(q("hp:pagePr"))).find(q("hp:margin"))
    for k, v in dict(top=top, bottom=bottom, left=left, right=right, header=header, footer=footer).items():
        margin.set(k, str(mm_to_hu(v)))


def p(text: str, pp: str, cp: str, style: str = "0") -> etree._Element:
    el = etree.Element(q("hp:p"), {**_P, "paraPrIDRef": pp, "styleIDRef": style})
    run = etree.SubElement(el, q("hp:run"), {"charPrIDRef": cp})
    etree.SubElement(run, q("hp:t")).text = text
    return el


def table(rows: int, cols: int, *, width: int, head_bf: str, body_bf: str, head: tuple, body: tuple,
          texts: dict | None = None, widths: list[float] | None = None) -> etree._Element:
    from hwpxkit.layout import distribute
    texts = texts or {}
    cols_w = distribute(width, widths or [1] * cols)
    holder = etree.Element(q("hp:p"), {**_P, "paraPrIDRef": body[0], "styleIDRef": "0"})
    run = etree.SubElement(holder, q("hp:run"), {"charPrIDRef": body[1]})
    tbl = etree.SubElement(run, q("hp:tbl"), {
        "id": "0", "zOrder": "0", "numberingType": "TABLE", "textWrap": "TOP_AND_BOTTOM", "textFlow": "BOTH_SIDES",
        "lock": "0", "dropcapstyle": "None", "pageBreak": "CELL", "repeatHeader": "1", "rowCnt": str(rows),
        "colCnt": str(cols), "cellSpacing": "0", "borderFillIDRef": body_bf, "noAdjust": "0"})
    etree.SubElement(tbl, q("hp:sz"), {"width": str(width), "widthRelTo": "ABSOLUTE", "height": str(1500 * rows),
                                       "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(tbl, q("hp:pos"), {
        "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1", "allowOverlap": "0", "holdAnchorAndSO": "0",
        "vertRelTo": "PARA", "horzRelTo": "COLUMN", "vertAlign": "TOP", "horzAlign": "LEFT", "vertOffset": "0",
        "horzOffset": "0"})
    etree.SubElement(tbl, q("hp:outMargin"), {"left": "283", "right": "283", "top": "283", "bottom": "283"})
    etree.SubElement(tbl, q("hp:inMargin"), {"left": "510", "right": "510", "top": "141", "bottom": "141"})
    etree.SubElement(run, q("hp:t"))
    for r in range(rows):
        tr = etree.SubElement(tbl, q("hp:tr"))
        pp, cp = head if r == 0 else body
        for c in range(cols):
            tc = etree.SubElement(tr, q("hp:tc"), {"name": "", "header": "1" if r == 0 else "0", "hasMargin": "0",
                                                   "protect": "0", "editable": "0", "dirty": "0",
                                                   "borderFillIDRef": head_bf if r == 0 else body_bf})
            sub = etree.SubElement(tc, q("hp:subList"), {
                "id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK", "vertAlign": "CENTER",
                "linkListIDRef": "0", "linkListNextIDRef": "0", "textWidth": "0", "textHeight": "0",
                "hasTextRef": "0", "hasNumRef": "0"})
            sub.append(p(texts.get((r, c), ""), pp, cp))
            etree.SubElement(tc, q("hp:cellAddr"), {"colAddr": str(c), "rowAddr": str(r)})
            etree.SubElement(tc, q("hp:cellSpan"), {"colSpan": "1", "rowSpan": "1"})
            etree.SubElement(tc, q("hp:cellSz"), {"width": str(cols_w[c]), "height": "1500"})
            etree.SubElement(tc, q("hp:cellMargin"), {"left": "510", "right": "510", "top": "141", "bottom": "141"})
    return holder


def cell_paragraphs(table_para: etree._Element, rc: tuple[int, int], paragraphs: list) -> None:
    for tc in table_para.iter(q("hp:tc")):
        a = tc.find(q("hp:cellAddr"))
        if (int(a.get("rowAddr")), int(a.get("colAddr"))) == rc:
            sub = tc.find(q("hp:subList"))
            for old in sub.findall(q("hp:p")):
                sub.remove(old)
            for el in paragraphs:
                sub.append(el)
            return
    raise KeyError(rc)


PERSONAL_META = ("creator", "lastsaveby", "CreatedDate", "ModifiedDate", "date")


def scrub_metadata(path: Path) -> None:
    """문서 정보(content.hpf)의 작성자·저장자·날짜를 지운다. 한글로 저장하면 PC 사용자 이름이 들어가고,
    프리셋으로 만든 모든 결과 문서에 그대로 퍼지기 때문이다."""
    pkg = Package.open(path)
    root = pkg.edit("Contents/content.hpf")
    for m in root.iter(f"{{{NS['opf']}}}meta"):
        if m.get("name") in PERSONAL_META:
            m.text = None
    tmp = path.with_name(path.stem + ".scrub.hwpx")
    pkg.save(tmp)
    tmp.replace(path)
