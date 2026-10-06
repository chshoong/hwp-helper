"""견본이 없을 때 쓰는 최소 골격 (그림, 캡션, 실선 표).

서식 ID는 만들지 않고 header.derive로 기존 항목을 복제해 얻는다.
그림 구조는 한글이 저장한 실제 보고서의 hp:pic을 본떴다.
"""
from __future__ import annotations

import copy

from lxml import etree

from .header import Header
from .layout import px_to_hu
from .ns import q

_SUBLIST = {"id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK", "vertAlign": "TOP",
            "linkListIDRef": "0", "linkListNextIDRef": "0", "textWidth": "0", "textHeight": "0",
            "hasTextRef": "0", "hasNumRef": "0"}
_P = {"id": "0", "pageBreak": "0", "columnBreak": "0", "merged": "0"}
_CELL_MARGIN = {"left": "510", "right": "510", "top": "141", "bottom": "141"}


def solid_border_fill(h: Header) -> str:
    """선이 있는 표 테두리(실선 0.12mm). 가장 작은 ID의 borderFill을 복제해 바꾼다."""
    base = min(h.ids("borderFill"), key=int)

    def mutate(e):
        for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
            b = e.find(q(f"hh:{side}"))
            b.set("type", "SOLID")
            b.set("width", "0.12 mm")
            b.set("color", "#000000")

    return h.derive("borderFill", base, mutate)


def new_picture(bid: str, px_w: int, px_h: int, w: int, h: int, name: str) -> etree._Element:
    pic = etree.Element(q("hp:pic"), {
        "id": "0", "zOrder": "0", "numberingType": "PICTURE", "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES", "lock": "0", "dropcapstyle": "None", "href": "", "groupLevel": "0",
        "instid": "0", "reverse": "0"})
    etree.SubElement(pic, q("hp:offset"), {"x": "0", "y": "0"})
    etree.SubElement(pic, q("hp:orgSz"))
    etree.SubElement(pic, q("hp:curSz"))
    etree.SubElement(pic, q("hp:flip"), {"horizontal": "0", "vertical": "0"})
    etree.SubElement(pic, q("hp:rotationInfo"), {"angle": "0", "rotateimage": "1"})
    ri = etree.SubElement(pic, q("hp:renderingInfo"))
    ident = {"e1": "1", "e2": "0", "e3": "0", "e4": "0", "e5": "1", "e6": "0"}
    etree.SubElement(ri, q("hc:transMatrix"), ident)
    etree.SubElement(ri, q("hc:scaMatrix"), ident)
    etree.SubElement(ri, q("hc:rotMatrix"), ident)
    etree.SubElement(pic, q("hc:img"), {"binaryItemIDRef": bid, "bright": "0", "contrast": "0",
                                        "effect": "REAL_PIC", "alpha": "0"})
    rect = etree.SubElement(pic, q("hp:imgRect"))
    for k in range(4):
        etree.SubElement(rect, q(f"hc:pt{k}"))
    etree.SubElement(pic, q("hp:imgClip"))
    etree.SubElement(pic, q("hp:inMargin"), {"left": "0", "right": "0", "top": "0", "bottom": "0"})
    etree.SubElement(pic, q("hp:imgDim"))
    etree.SubElement(pic, q("hp:effects"))
    etree.SubElement(pic, q("hp:sz"), {"widthRelTo": "ABSOLUTE", "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(pic, q("hp:pos"), {
        "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1", "allowOverlap": "0",
        "holdAnchorAndSO": "0", "vertRelTo": "PARA", "horzRelTo": "PARA", "vertAlign": "TOP",
        "horzAlign": "LEFT", "vertOffset": "0", "horzOffset": "0"})
    etree.SubElement(pic, q("hp:outMargin"), {"left": "0", "right": "0", "top": "0", "bottom": "0"})
    etree.SubElement(pic, q("hp:shapeComment"))
    set_picture(pic, bid, px_w, px_h, w, h, name)
    return pic


def set_picture(pic: etree._Element, bid: str, px_w: int, px_h: int, w: int, h: int, name: str) -> None:
    ow, oh = px_to_hu(px_w), px_to_hu(px_h)
    pic.find(q("hp:offset")).attrib.update({"x": "0", "y": "0"})
    pic.find(q("hp:orgSz")).attrib.update({"width": str(ow), "height": str(oh)})
    pic.find(q("hp:curSz")).attrib.update({"width": str(w), "height": str(h)})
    pic.find(q("hp:rotationInfo")).attrib.update({"centerX": str(w // 2), "centerY": str(h // 2)})
    sca = pic.find(f"{q('hp:renderingInfo')}/{q('hc:scaMatrix')}")
    sca.attrib.update({"e1": f"{w / ow:.6f}", "e5": f"{h / oh:.6f}"})
    pic.find(q("hc:img")).set("binaryItemIDRef", bid)
    pts = pic.find(q("hp:imgRect"))
    for k, (x, y) in enumerate(((0, 0), (ow, 0), (ow, oh), (0, oh))):
        pts.find(q(f"hc:pt{k}")).attrib.update({"x": str(x), "y": str(y)})
    pic.find(q("hp:imgClip")).attrib.update({"left": "0", "right": str(ow), "top": "0", "bottom": str(oh)})
    pic.find(q("hp:imgDim")).attrib.update({"dimwidth": str(ow), "dimheight": str(oh)})
    pic.find(q("hp:sz")).attrib.update({"width": str(w), "height": str(h)})
    pic.find(q("hp:shapeComment")).text = (
        f"그림입니다.\n원본 그림의 이름: {name}\n원본 그림의 크기: 가로 {px_w}pixel, 세로 {px_h}pixel")


def new_caption(text: str, width: int, para_pr: str, style: str, char_pr: str) -> etree._Element:
    cap = etree.Element(q("hp:caption"), {"side": "BOTTOM", "fullSz": "0", "width": "8504", "gap": "850",
                                          "lastWidth": str(width)})
    sub = etree.SubElement(cap, q("hp:subList"), dict(_SUBLIST))
    p = etree.SubElement(sub, q("hp:p"), {**_P, "paraPrIDRef": para_pr, "styleIDRef": style})
    run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": char_pr})
    etree.SubElement(run, q("hp:t")).text = text
    return cap


def set_caption(cap: etree._Element, text: str, width: int) -> None:
    """캡션을 글자 한 덩어리로 바꾼다. 견본의 자동 번호 컨트롤은 지운다(번호는 엔진이 계산)."""
    sub = cap.find(q("hp:subList"))
    tmpl = sub.find(q("hp:p"))
    runs = tmpl.findall(q("hp:run")) if tmpl is not None else []
    char = next((r.get("charPrIDRef") for r in runs if r.find(q("hp:t")) is not None),
                runs[0].get("charPrIDRef") if runs else "0")
    attrs = dict(tmpl.attrib) if tmpl is not None else {**_P, "paraPrIDRef": "0", "styleIDRef": "0"}
    for p in list(sub):
        sub.remove(p)
    p = etree.SubElement(sub, q("hp:p"), attrs)
    run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": char})
    etree.SubElement(run, q("hp:t")).text = text
    cap.set("lastWidth", str(width))


def _cell(border_fill: str, para_pr: str, style: str, char_pr: str, row_h: int) -> etree._Element:
    tc = etree.Element(q("hp:tc"), {"name": "", "header": "0", "hasMargin": "0", "protect": "0",
                                    "editable": "0", "dirty": "0", "borderFillIDRef": border_fill})
    sub = etree.SubElement(tc, q("hp:subList"), {**_SUBLIST, "vertAlign": "CENTER"})
    p = etree.SubElement(sub, q("hp:p"), {**_P, "paraPrIDRef": para_pr, "styleIDRef": style})
    etree.SubElement(p, q("hp:run"), {"charPrIDRef": char_pr})
    etree.SubElement(tc, q("hp:cellAddr"), {"colAddr": "0", "rowAddr": "0"})
    etree.SubElement(tc, q("hp:cellSpan"), {"colSpan": "1", "rowSpan": "1"})
    etree.SubElement(tc, q("hp:cellSz"), {"width": "0", "height": str(row_h)})
    etree.SubElement(tc, q("hp:cellMargin"), dict(_CELL_MARGIN))
    return tc


def new_table_para(h: Header, body, width: int, row_h: int = 1500):
    """행이 없는 실선 표를 담은 문단과, 머리행·본문행 칸 견본을 돌려준다."""
    bf = solid_border_fill(h)
    p = etree.Element(q("hp:p"), {**_P, "paraPrIDRef": body.para_pr, "styleIDRef": body.style})
    run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": body.char_pr})
    tbl = etree.SubElement(run, q("hp:tbl"), {
        "id": "0", "zOrder": "0", "numberingType": "TABLE", "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES", "lock": "0", "dropcapstyle": "None", "pageBreak": "CELL",
        "repeatHeader": "1", "rowCnt": "0", "colCnt": "0", "cellSpacing": "0",
        "borderFillIDRef": bf, "noAdjust": "0"})
    etree.SubElement(tbl, q("hp:sz"), {"width": str(width), "widthRelTo": "ABSOLUTE", "height": "0",
                                       "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(tbl, q("hp:pos"), {
        "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1", "allowOverlap": "0",
        "holdAnchorAndSO": "0", "vertRelTo": "PARA", "horzRelTo": "COLUMN", "vertAlign": "TOP",
        "horzAlign": "LEFT", "vertOffset": "0", "horzOffset": "0"})
    etree.SubElement(tbl, q("hp:outMargin"), {"left": "283", "right": "283", "top": "283", "bottom": "283"})
    etree.SubElement(tbl, q("hp:inMargin"), dict(_CELL_MARGIN))
    etree.SubElement(run, q("hp:t"))
    head = _cell(bf, body.para_pr, body.style, h.derive_charpr(body.char_pr, bold=True), row_h)
    cell = _cell(bf, body.para_pr, body.style, body.char_pr, row_h)
    return p, tbl, head, cell


def new_equation(script: str, width: int, height: int, baseline: int, base_unit: int) -> etree._Element:
    eq = etree.Element(q("hp:equation"), {
        "id": "0", "zOrder": "0", "numberingType": "EQUATION", "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES", "lock": "0", "dropcapstyle": "None", "version": "Equation Version 60",
        "baseLine": "86", "textColor": "#000000", "baseUnit": "1000", "lineMode": "CHAR", "font": "HancomEQN"})
    etree.SubElement(eq, q("hp:sz"), {"width": "0", "widthRelTo": "ABSOLUTE", "height": "0",
                                      "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(eq, q("hp:pos"), {
        "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1", "allowOverlap": "0",
        "holdAnchorAndSO": "0", "vertRelTo": "PARA", "horzRelTo": "PARA", "vertAlign": "TOP",
        "horzAlign": "LEFT", "vertOffset": "0", "horzOffset": "0"})
    etree.SubElement(eq, q("hp:outMargin"), {"left": "56", "right": "56", "top": "0", "bottom": "0"})
    etree.SubElement(eq, q("hp:shapeComment")).text = "수식입니다."
    etree.SubElement(eq, q("hp:script"))
    set_equation(eq, script, width, height, baseline, base_unit)
    return eq


def set_equation(eq: etree._Element, script: str, width: int, height: int, baseline: int, base_unit: int) -> None:
    eq.set("baseLine", str(baseline))
    eq.set("baseUnit", str(base_unit))
    eq.find(q("hp:sz")).attrib.update({"width": str(width), "height": str(height)})
    eq.find(q("hp:script")).text = script


def _aligned_para_pr(h: Header, base: str, align: str) -> str:
    return h.derive("paraPr", base, lambda e: e.find(q("hh:align")).set("horizontal", align))


def no_border_fill(h: Header) -> str:
    """선 없는 테두리. 가장 작은 ID의 borderFill을 복제해 네 변을 NONE으로."""
    base = min(h.ids("borderFill"), key=int)

    def mutate(e):
        for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
            e.find(q(f"hh:{side}")).set("type", "NONE")

    return h.derive("borderFill", base, mutate)


def new_eq_table_para(h: Header, body, width: int, eq: etree._Element, number: str) -> etree._Element:
    """번호 붙은 문단 수식: 선 없는 1행 2열 표 (왼쪽 수식 가운데, 오른쪽 번호 오른쪽 정렬)."""
    p, tbl, _, cell = new_table_para(h, body, width)
    bf = no_border_fill(h)
    tbl.set("borderFillIDRef", bf)
    tbl.set("rowCnt", "1")
    tbl.set("colCnt", "2")
    left, right = int(width * 0.85), width - int(width * 0.85)
    tr = etree.SubElement(tbl, q("hp:tr"))
    for c, (w, align) in enumerate(((left, "CENTER"), (right, "RIGHT"))):
        tc = copy.deepcopy(cell)
        tc.set("borderFillIDRef", bf)
        tc.find(q("hp:cellAddr")).set("colAddr", str(c))
        tc.find(q("hp:cellSz")).set("width", str(w))
        cp = tc.find(f"{q('hp:subList')}/{q('hp:p')}")
        cp.set("paraPrIDRef", _aligned_para_pr(h, body.para_pr, align))
        run = cp.find(q("hp:run"))
        if c == 0:
            run.append(eq)
        else:
            etree.SubElement(run, q("hp:t")).text = number
        tr.append(tc)
    tbl.find(q("hp:sz")).set("height", cell.find(q("hp:cellSz")).get("height"))
    return p
