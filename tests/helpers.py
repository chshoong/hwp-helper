"""테스트에서 쓰는 HWPX 요소 생성기. 실제 한글 문서 구조(월간보고서 분석)를 본떴다."""
from lxml import etree

from hwpxkit.ns import q

SECTION = "Contents/section0.xml"

_P_ATTRS = {"id": "0", "pageBreak": "0", "columnBreak": "0", "merged": "0"}
_SUBLIST = {"id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK", "vertAlign": "CENTER",
            "linkListIDRef": "0", "linkListNextIDRef": "0", "textWidth": "0", "textHeight": "0",
            "hasTextRef": "0", "hasNumRef": "0"}
_MARGIN = {"left": "510", "right": "510", "top": "141", "bottom": "141"}


def para(text, para_pr="0", char_pr="0", style="0"):
    p = etree.Element(q("hp:p"), {**_P_ATTRS, "paraPrIDRef": para_pr, "styleIDRef": style})
    run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": char_pr})
    etree.SubElement(run, q("hp:t")).text = text
    return p


def table(rows, cols, *, border_fill="1", width=42000, cell_h=1000, texts=None, spans=None, skip=()):
    """rows×cols 표를 담은 문단을 만든다.

    texts: {(r, c): "글" 또는 ["줄1", "줄2"]}
    spans: {(r, c): (rowSpan, colSpan)}
    skip: 병합으로 가려져 생략할 칸 {(r, c)} — 일부러 빼먹어 오류를 만들 때도 쓴다.
    """
    texts, spans = texts or {}, spans or {}
    p = etree.Element(q("hp:p"), {**_P_ATTRS, "paraPrIDRef": "0", "styleIDRef": "0"})
    run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": "0"})
    tbl = etree.SubElement(run, q("hp:tbl"), {
        "id": "1000", "zOrder": "0", "numberingType": "TABLE", "textWrap": "TOP_AND_BOTTOM",
        "textFlow": "BOTH_SIDES", "lock": "0", "dropcapstyle": "None", "pageBreak": "CELL",
        "repeatHeader": "1", "rowCnt": str(rows), "colCnt": str(cols), "cellSpacing": "0",
        "borderFillIDRef": border_fill, "noAdjust": "0"})
    etree.SubElement(tbl, q("hp:sz"), {"width": str(width), "widthRelTo": "ABSOLUTE",
                                       "height": str(cell_h * rows), "heightRelTo": "ABSOLUTE", "protect": "0"})
    etree.SubElement(tbl, q("hp:pos"), {
        "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1", "allowOverlap": "0",
        "holdAnchorAndSO": "0", "vertRelTo": "PARA", "horzRelTo": "COLUMN", "vertAlign": "TOP",
        "horzAlign": "LEFT", "vertOffset": "0", "horzOffset": "0"})
    etree.SubElement(tbl, q("hp:outMargin"), {"left": "283", "right": "283", "top": "283", "bottom": "283"})
    etree.SubElement(tbl, q("hp:inMargin"), dict(_MARGIN))
    col_w = width // cols
    for r in range(rows):
        tr = etree.SubElement(tbl, q("hp:tr"))
        for c in range(cols):
            if (r, c) in skip:
                continue
            rs, cs = spans.get((r, c), (1, 1))
            tc = etree.SubElement(tr, q("hp:tc"), {"name": "", "header": "0", "hasMargin": "0", "protect": "0",
                                                   "editable": "0", "dirty": "0", "borderFillIDRef": border_fill})
            sub = etree.SubElement(tc, q("hp:subList"), dict(_SUBLIST))
            value = texts.get((r, c), "")
            for line in (value if isinstance(value, list) else [value]):
                sub.append(para(line))
            etree.SubElement(tc, q("hp:cellAddr"), {"colAddr": str(c), "rowAddr": str(r)})
            etree.SubElement(tc, q("hp:cellSpan"), {"colSpan": str(cs), "rowSpan": str(rs)})
            etree.SubElement(tc, q("hp:cellSz"), {"width": str(col_w * cs), "height": str(cell_h * rs)})
            etree.SubElement(tc, q("hp:cellMargin"), dict(_MARGIN))
    return p


def append_to_body(pkg, element, section=SECTION):
    pkg.edit(section).append(element)
    return element


import io

from PIL import Image

from hwpxkit import shapes
from hwpxkit.header import Header

LONG = "이 문장은 본문 서식을 확인하려고 만든 가상의 견본 문장이며 특별한 뜻 없이 일정한 길이를 채우고 있다."


def tiny_png(size=(120, 60), mode="RGB", fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30) if mode == "RGB" else 128).save(buf, fmt)
    return buf.getvalue()


def picture_para(bid, caption=None, para_pr="0", char_pr="0"):
    p = etree.Element(q("hp:p"), {**_P_ATTRS, "paraPrIDRef": para_pr, "styleIDRef": "0"})
    run = etree.SubElement(p, q("hp:run"), {"charPrIDRef": char_pr})
    pic = shapes.new_picture(bid, 120, 60, 9000, 4500, "견본.png")
    if caption is not None:
        pic.append(shapes.new_caption(caption, 9000, para_pr, "0", char_pr))
    run.append(pic)
    etree.SubElement(run, q("hp:t"))
    return p


def report_template(pkg):
    """samples·render 테스트용 견본 문서. 실제 보고서(장/절/항/□○-/본문/표/그림) 모양을 흉내 낸다."""
    h = Header(pkg)
    ids = {
        "h1": h.derive_charpr("0", bold=True, height=1600),
        "h2": h.derive_charpr("0", bold=True, height=1300),
        "h4": h.derive_charpr("0", bold=True),
        "cap": h.derive_charpr("0", height=900),
        "center": h.derive("paraPr", "0", lambda e: e.find(q("hh:align")).set("horizontal", "CENTER")),
        "border": shapes.solid_border_fill(h),
    }
    add = lambda el: append_to_body(pkg, el)  # noqa: E731
    add(para("제1장 서론", char_pr=ids["h1"]))
    add(para("1.1. 연구 배경", char_pr=ids["h2"]))
    add(para("1) 필요성", char_pr=ids["h4"]))
    add(para("□ 주요 내용"))
    add(para("○ 세부 내용"))
    add(para("- 더 세부 내용"))
    add(para(LONG))
    add(para(LONG))
    add(para(""))
    add(para("제2장 방법", char_pr=ids["h1"]))
    add(para("[표 1-1] 견본 표", para_pr=ids["center"], char_pr=ids["cap"]))
    add(table(2, 3, border_fill=ids["border"], texts={(0, 0): "구분", (0, 1): "계획", (0, 2): "실적"}))
    bid = pkg.add_bin(tiny_png(), "png")
    add(picture_para(bid, caption="[그림 1-1] 견본 그림", para_pr=ids["center"], char_pr=ids["cap"]))
    return ids


def add_inner_caption(table_para, text):
    """표 안쪽 캡션(hp:caption, 위쪽)을 붙인다. 실제 최종보고서 표 49개 중 28개가 이 방식이다."""
    tbl = next(table_para.iter(q("hp:tbl")))
    cap = shapes.new_caption(text, 20000, "0", "0", "0")
    cap.set("side", "TOP")
    tbl.insert(list(tbl).index(tbl.find(q("hp:outMargin"))) + 1, cap)
    return table_para


def add_equation_samples(pkg):
    """수식 견본: 문단 속 수식 한 개, 오른쪽에 (1) 번호가 있는 1행 2열 수식 표 한 개."""
    p = append_to_body(pkg, para("견본 수식 " + LONG))
    p.find(q("hp:run")).append(shapes.new_equation("a", 600, 1000, 86, 1000))
    t = append_to_body(pkg, table(1, 2, texts={(0, 1): "(1)"}))
    next(t.iter(q("hp:tc"))).find(f".//{q('hp:run')}").append(shapes.new_equation("x", 600, 1000, 86, 1000))


_HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def add_bullets(pkg):
    """빈 문서에 □(1번)·-(2번) 자동 글머리를 만들고, 그것을 쓰는 문단모양과 글자모양을 만든다 (월간보고서 구조)."""
    from hwpxkit.package import HEADER
    h = Header(pkg)
    root = pkg.edit(HEADER)
    ref = root.find(f"{_HH}refList")
    bullets = etree.Element(f"{_HH}bullets", {"itemCnt": "2"})
    for bid, ch in (("1", "□"), ("2", "-")):
        b = etree.SubElement(bullets, f"{_HH}bullet", {"id": bid, "char": ch, "useImage": "0"})
        etree.SubElement(b, f"{_HH}paraHead", {
            "level": "0", "align": "LEFT", "useInstWidth": "0", "autoIndent": "1", "widthAdjust": "0",
            "textOffsetType": "PERCENT", "textOffset": "50", "numFormat": "DIGIT", "charPrIDRef": "4294967295",
            "checkable": "0"})
    ref.insert(list(ref).index(ref.find(f"{_HH}numberings")) + 1, bullets)

    def bullet_pp(bid):
        def mutate(e):
            e.find(f"{_HH}heading").attrib.update({"type": "BULLET", "idRef": bid, "level": "0"})
        return h.derive("paraPr", "0", mutate)

    return {
        "box_pp": bullet_pp("1"), "dash_pp": bullet_pp("2"),
        "black": "0", "blue": h.derive_charpr("0", color="#0000FF"),
        "blank_pp": h.derive("paraPr", "0", lambda e: e.find(f"{_HH}align").set("horizontal", "LEFT")),
    }


def memo_run(text, memo, char_pr="0"):
    """메모가 붙은 run: fieldBegin(MEMO, 메모 내용) + 글 + fieldEnd (월간보고서 구조를 단순화)."""
    run = etree.Element(q("hp:run"), {"charPrIDRef": char_pr})
    ctrl = etree.SubElement(run, q("hp:ctrl"))
    begin = etree.SubElement(ctrl, q("hp:fieldBegin"), {
        "id": "2100334526", "type": "MEMO", "name": "", "editable": "1", "dirty": "1", "zorder": "1",
        "fieldid": "623209829", "metaTag": ""})
    params = etree.SubElement(begin, q("hp:parameters"), {"cnt": "1", "name": ""})
    etree.SubElement(params, q("hp:stringParam"), {"name": "Author"}).text = "검토자"
    sub = etree.SubElement(begin, q("hp:subList"), dict(_SUBLIST))
    sub.append(para(memo))
    etree.SubElement(run, q("hp:t")).text = text
    end_ctrl = etree.SubElement(run, q("hp:ctrl"))
    etree.SubElement(end_ctrl, q("hp:fieldEnd"), {"beginIDRef": "2100334526", "fieldid": "623209829"})
    return run


def set_cell(table_para, rc, paragraphs):
    r, c = rc
    for tc in table_para.iter(q("hp:tc")):
        a = tc.find(q("hp:cellAddr"))
        if (int(a.get("rowAddr")), int(a.get("colAddr"))) == (r, c):
            sub = tc.find(q("hp:subList"))
            for p in list(sub):
                sub.remove(p)
            for p in paragraphs:
                sub.append(p)
            return
    raise KeyError(rc)


def monthly_form(pkg):
    """가상 월간보고서 양식 (실제 월간보고서의 칸 구조·글머리·메모를 본뜸)."""
    ids = add_bullets(pkg)
    border = shapes.solid_border_fill(Header(pkg))
    add = lambda el: append_to_body(pkg, el)  # noqa: E731
    add(para("‘26년 2월 월간업무보고서"))
    add(para("보 고 일 : 2025.03.12.(목)"))
    add(table(2, 4, border_fill=border, texts={(0, 0): "계획(A)", (0, 1): "실적(B)", (0, 2): "계획 대비 실적(B/A)",
                                               (0, 3): "비고", (1, 0): "12.5%", (1, 1): "12.5%", (1, 2): "100%"}))
    t2 = add(table(4, 3, border_fill=border, spans={(3, 1): (1, 2)}, skip={(3, 2)}, texts={
        (0, 0): "구분", (0, 1): "금월 추진실적(26. 02.)", (0, 2): "향후 계획사항(26. 03.)",
        (1, 0): "가상 분야 표본 데이터 모델 개발 및 품질 평가",
        (2, 0): "가상 표본 자료 기반 활용 서비스 기획", (3, 0): "요청사항", (3, 1): "-"}))
    box = lambda t: para(t, para_pr=ids["box_pp"], char_pr=ids["black"])  # noqa: E731
    dash = lambda t: para(t, para_pr=ids["dash_pp"], char_pr=ids["blue"])  # noqa: E731
    blank_line = para("", para_pr=ids["blank_pp"])
    memo_p = box("")
    memo_p.remove(memo_p.find(q("hp:run")))
    memo_p.append(memo_run("원시 자료 변환", "해당 부분 이외에는 모두 협력 기관 작성", ids["black"]))
    set_cell(t2, (1, 1), [box("기초 자료 점검 및 정리"), dash("표본 자료 전수 점검"), blank_line,
                          memo_p, dash("분석 단위 변환")])
    set_cell(t2, (1, 2), [box("표본 생성 모형 개선 지속"), dash("생성 결과 점검")])
    set_cell(t2, (2, 2), [box("활용 사례 조사"), dash("후보 분야 정리")])
    add(table(3, 2, border_fill=border, texts={(0, 0): "구분", (0, 1): "상세 추진 내용",
                                               (1, 0): "표본 자료 전수 점검", (1, 1): "상세 추진 내용",
                                               (2, 0): "분석 단위 변환", (2, 1): "상세 추진 내용"}))
    return ids



def add_section(pkg, element):
    """둘째 구역(section1.xml)을 만들고 element를 넣는다 (여러 구역 양식 흉내)."""
    import copy as _copy
    from hwpxkit.package import CONTENT_HPF
    root = _copy.deepcopy(pkg.xml(SECTION))
    for p in list(root)[1:]:
        root.remove(p)
    root.append(element)
    pkg.write("Contents/section1.xml", etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True))
    hpf = pkg.edit(CONTENT_HPF)
    man = hpf.find(q("opf:manifest"))
    etree.SubElement(man, q("opf:item"), {"id": "section1", "href": "Contents/section1.xml",
                                          "media-type": "application/xml"})
    spine = hpf.find(q("opf:spine"))
    etree.SubElement(spine, q("opf:itemref"), {"idref": "section1", "linear": "yes"})
