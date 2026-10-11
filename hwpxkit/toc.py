"""차례·표 목차·그림 목차(한글 고유 차례 칸)와 본문 표·그림 참조(한글 상호 참조).

차례 칸은 TABLEOFCONTENTS 필드로 감싼 문단들이다. 엔진은 쪽 번호 없는 임시 목록을 넣고,
한글이 '차례 모두 새로 고침'(UpdateAllContents)으로 항목과 쪽 번호를 다시 만든다 (설계 2장).
"""
from __future__ import annotations

import re

from lxml import etree

from .body import all_text, is_blank, own_text, t_text
from .header import Header
from .ns import q
from .package import Package
from .samples import bullet_chars, classify, heading_levels

ORDER = ("제목", "표", "그림")
MAKE = {"제목": 65, "표": 2, "그림": 4}
_TAG = {"표": "hp:tbl", "그림": "hp:pic"}
_HEAD = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5}
_P = {"id": "0", "pageBreak": "0", "columnBreak": "0", "merged": "0"}
_EMPTY = {"제목": "차례에 넣을 장·절 제목을 찾지 못해 제목 차례는 넣지 않았어요.",
          "표": "캡션 달린 표가 없어 표 목차는 넣지 않았어요.",
          "그림": "캡션 달린 그림이 없어 그림 목차는 넣지 않았어요."}
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _command(make: int, level: int) -> str:
    return (f"TableOfContents:set:139:ContentsMake:uint:{make} ContentsStyles:wstring:0: "
            f"ContentsLevel:int:{level} ContentsAutoTabRight:int:0 ContentsLeader:int:3 ContentsHyperlink:bool:1  ")


def _tops(pkg: Package):
    root = pkg.edit(pkg.section_names()[0])
    return root, [p for p in root if p.tag == q("hp:p")]


class _Ids:
    """필드 id·fieldid: 문서 안 기존 값과 겹치지 않게 새로 준다."""

    def __init__(self, pkg: Package):
        used = [1_500_000_000]
        for sec in pkg.section_names():
            for fb in pkg.xml(sec).iter(q("hp:fieldBegin")):
                for attr in ("id", "fieldid"):
                    v = fb.get(attr)
                    if v and v.isdigit():
                        used.append(int(v))
        self._next = max(used)

    def take(self) -> str:
        self._next += 1
        return str(self._next)


def _field_begin(ids: _Ids, ftype: str, params, editable: str = "0"):
    fb = etree.Element(q("hp:fieldBegin"), {"id": ids.take(), "type": ftype, "name": "", "editable": editable,
                                            "dirty": "0", "zorder": "-1", "fieldid": ids.take(), "metaTag": ""})
    ps = etree.SubElement(fb, q("hp:parameters"), {"cnt": str(len(params)), "name": ""})
    for kind, name, value in params:
        e = etree.SubElement(ps, q(f"hp:{kind}Param"), {"name": name})
        e.text = value
        if value != value.strip():
            e.set(_XML_SPACE, "preserve")
    return fb


def _field_end(fb):
    return etree.Element(q("hp:fieldEnd"), {"beginIDRef": fb.get("id"), "fieldid": fb.get("fieldid")})


def _ctrl(el):
    c = etree.Element(q("hp:ctrl"))
    c.append(el)
    return c


def _style(h: Header, name: str) -> tuple[str, str, str]:
    sid = h.style_id(name)
    if sid is None:
        return "0", "0", "0"
    e = h.get("style", sid)
    return e.get("paraPrIDRef"), sid, e.get("charPrIDRef")


def _new_p(para_pr: str, style: str, char_pr: str):
    p = etree.Element(q("hp:p"), {**_P, "paraPrIDRef": para_pr, "styleIDRef": style})
    return p, etree.SubElement(p, q("hp:run"), {"charPrIDRef": char_pr})


def _kind_of(make: int) -> str | None:
    if make & (1 | 64):
        return "제목"
    if make & 2:
        return "표"
    if make & 4:
        return "그림"
    return None


def toc_blocks(tops: list) -> list[tuple[int, int, int]]:
    """문서의 차례 칸: (시작 문단, 끝 문단(포함), ContentsMake)."""
    out = []
    for i, p in enumerate(tops):
        for fb in p.iter(q("hp:fieldBegin")):
            if fb.get("type") != "TABLEOFCONTENTS":
                continue
            cmd = next((e.text or "" for e in fb.iter(q("hp:stringParam")) if e.get("name") == "Command"), "")
            m = re.search(r"ContentsMake:uint:(\d+)", cmd)
            end = next((j for j in range(i, len(tops))
                        if any(fe.get("beginIDRef") == fb.get("id") for fe in tops[j].iter(q("hp:fieldEnd")))), i)
            out.append((i, end, int(m.group(1)) if m else 0))
    return out


def has_toc(pkg: Package) -> bool:
    return bool(toc_blocks([p for p in pkg.xml(pkg.section_names()[0]) if p.tag == q("hp:p")]))


def _in_toc(tops: list) -> set[int]:
    return {i for s, e, _ in toc_blocks(tops) for i in range(s, e + 1)}


def _headings(pkg: Package, level: int) -> list:
    h = Header(pkg)
    chars = bullet_chars(h)
    _, tops = _tops(pkg)
    levels = heading_levels(tops)
    skip = _in_toc(tops)
    return [p for i, p in enumerate(tops)
            if i not in skip and _HEAD.get(classify(p, h, chars, levels)[0], 9) <= level]


def mark_titles(pkg: Package, level: int = 2, paragraphs: list | None = None) -> int:
    """제목 문단 앞에 '제목 차례 표시'(titleMark)를 넣는다. 이미 있으면 그대로. 넣은 수를 돌려준다."""
    n = 0
    for p in (paragraphs if paragraphs is not None else _headings(pkg, level)):
        if next(p.iter(q("hp:titleMark")), None) is not None or not own_text(p).strip():
            continue
        t = next((t for run in p.findall(q("hp:run")) for t in run.findall(q("hp:t"))), None)
        if t is None:
            continue
        tm = etree.Element(q("hp:titleMark"), {"ignore": "1"})
        tm.tail, t.text = t.text, None
        t.insert(0, tm)
        n += 1
    return n


def _entries(pkg: Package, kind: str) -> list[str]:
    root, tops = _tops(pkg)
    if kind == "제목":
        return [own_text(p).strip() for p in tops if next(p.iter(q("hp:titleMark")), None) is not None]
    caps = [o.find(q("hp:caption")) for o in root.iter(q(_TAG[kind])) if o.find(q("hp:caption")) is not None]
    return [_caption_text(cap, n) for n, cap in enumerate(caps, 1)]


def _caption_text(cap, n: int) -> str:
    """캡션 글. 한글 자동 번호(autoNum)는 문서 순서 번호 n으로 채운다 (한글이 세는 방식)."""
    out = []
    for el in cap.iter(q("hp:t"), q("hp:autoNum")):
        out.append(str(n) if el.tag == q("hp:autoNum") else t_text(el))
    return "".join(out).strip()


def _block(pkg: Package, kind: str, level: int, entries: list[str], ids: _Ids) -> list:
    """차례 칸 문단들: 시작(필드) · 임시 항목(쪽 번호 없음) · 끝(필드 닫기)."""
    h = Header(pkg)
    head, item = _style(h, "차례 제목"), _style(h, "차례 1")
    first, run = _new_p(*head)
    fb = _field_begin(ids, "TABLEOFCONTENTS",
                      [("integer", "Prop", "8"), ("string", "Command", _command(MAKE[kind], level))], editable="1")
    run.append(_ctrl(fb))
    etree.SubElement(run, q("hp:t"))
    out = [first]
    for text in entries:
        p, r = _new_p(*item)
        etree.SubElement(r, q("hp:t")).text = text
        out.append(p)
    last, r = _new_p(*item)
    r.append(_ctrl(_field_end(fb)))
    etree.SubElement(r, q("hp:t"))
    out.append(last)
    return out


def _insert_before(root, ref, els) -> None:
    pos = root.index(ref) if ref is not None else len(root)
    for k, el in enumerate(els):
        root.insert(pos + k, el)


def insert_toc(pkg: Package, kinds, *, level: int = 2, at: int | None = None,
               titles: list | None = None) -> list[str]:
    """차례 칸을 넣는다. at(최상위 문단 번호)이 있으면 그 문단 앞에, 없으면 차례 자리(find_slot)에.
    같은 종류의 기존 칸은 바꾼다. 경고 목록을 돌려준다."""
    bad = [k for k in kinds if k not in ORDER]
    if bad:
        raise ValueError(f"차례 종류는 제목·표·그림 중에서 골라 주세요: {', '.join(bad)}")
    warnings: list[str] = []
    if len(pkg.section_names()) > 1:
        warnings.append("구역이 여러 개인 문서예요. 첫 구역에만 차례를 넣었어요.")
    ids = _Ids(pkg)
    root, tops = _tops(pkg)
    ref = tops[at] if at is not None and at < len(tops) else None
    page_break = at is not None and ref is not None and ref.get("pageBreak") == "1"
    for kind in [k for k in ORDER if k in set(kinds)]:
        if kind == "제목":
            mark_titles(pkg, level, titles)
        entries = _entries(pkg, kind)
        if not entries:
            warnings.append(_EMPTY[kind])
            continue
        els = _block(pkg, kind, level, entries, ids)
        if page_break:
            els[0].set("pageBreak", "1")
            page_break = False
        _insert_before(root, ref, els)
    return warnings
