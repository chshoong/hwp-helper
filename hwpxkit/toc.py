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


def _direct(p, tag: str) -> list:
    """문단 바로 아래(run/ctrl)의 필드 요소만. 표 칸·글상자 안 것은 제외."""
    return [c.find(q(tag)) for run in p.findall(q("hp:run")) for c in run.findall(q("hp:ctrl"))
            if c.find(q(tag)) is not None]


def toc_blocks(tops: list) -> list[tuple[int, int, int]]:
    """문서의 차례 칸: (시작 문단, 끝 문단(포함), ContentsMake). 끝(fieldEnd)을 못 찾은 칸은 건드리지 않게 뺀다."""
    out = []
    for i, p in enumerate(tops):
        for fb in _direct(p, "hp:fieldBegin"):
            if fb.get("type") != "TABLEOFCONTENTS":
                continue
            cmd = next((e.text or "" for e in fb.iter(q("hp:stringParam")) if e.get("name") == "Command"), "")
            m = re.search(r"ContentsMake:uint:(\d+)", cmd)
            end = next((j for j in range(i, len(tops))
                        if any(fe.get("beginIDRef") == fb.get("id") for fe in _direct(tops[j], "hp:fieldEnd"))), None)
            if end is not None:
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


_LABEL = {"제목": "차례", "표": "표 목차", "그림": "그림 목차"}
_SLOT = {"목차": "*", "차례": "*", "표목차": "표", "표차례": "표", "그림목차": "그림", "그림차례": "그림"}
_EMPTY_CELL = {"", "…", "...", "·", "‥"}


def _droppable(p) -> bool:
    """양식 목차 자리 밑의 빈 문단, 빈 목차 표(모든 칸이 비었거나 '…'만)."""
    if p.get("pageBreak") == "1" or p.get("columnBreak") == "1":
        return False
    tbl = next(p.iter(q("hp:tbl")), None)
    if tbl is None:  # 머리말·쪽 번호·필드 같은 개체(ctrl)가 든 문단은 빈 줄처럼 보여도 남긴다
        return is_blank(p) and not any(run.findall(q("hp:ctrl")) for run in p.findall(q("hp:run")))
    if own_text(p).strip():
        return False
    return all(all_text(tc).strip() in _EMPTY_CELL for tc in tbl.iter(q("hp:tc")))


def find_slot(pkg: Package, kind: str) -> tuple[int, str, list[int]]:
    """차례 칸을 넣을 자리: (이 문단 앞에, 근거, 지울 문단들)."""
    _, tops = _tops(pkg)
    for s, e, m in toc_blocks(tops):
        if _kind_of(m) == kind:
            return s, "기존 차례 칸", list(range(s, e + 1))
    texts = [re.sub(r"\s+", "", own_text(p)) for p in tops]
    for want, reason in ((kind, f"양식 {_LABEL[kind]} 자리"), ("*", "양식 목차 자리")):
        hit = next((i for i, t in enumerate(texts) if _SLOT.get(t) == want), None)
        if hit is not None and not (kind == "제목" and want == kind):
            ends = {s: e for s, e, _ in toc_blocks(tops)}
            j = hit + 1
            while j in ends:  # 이미 그 제목 아래 있는 다른 차례 칸 뒤에
                j = ends[j] + 1
            drop, k = [], j
            while k < len(tops) and _droppable(tops[k]):
                drop.append(k)
                k += 1
            return j, reason, drop
    k = next((i for i, p in enumerate(tops) if i > 0 and p.get("pageBreak") == "1"), None)
    if k is not None:
        return k, "표지 다음", []
    return min(1, len(tops)), "문서 처음", []


def _insert_before(root, ref, els) -> None:
    pos = root.index(ref) if ref is not None else len(root)
    for k, el in enumerate(els):
        root.insert(pos + k, el)


_KEEP = ("hp:secPr", "hp:colPr", "hp:tbl", "hp:pic", "hp:equation")


def _drop_ctrl(p, tag: str, field_id: str) -> None:
    for el in _direct(p, tag):
        if el.get("id") == field_id or el.get("beginIDRef") == field_id:
            ctrl = el.getparent()
            ctrl.getparent().remove(ctrl)


def _remove_block(root, tops: list, s: int, e: int):
    """기존 차례 칸을 지운다. 0번 문단(쪽 설정)·다른 개체가 든 시작 문단과 본문이 합쳐진 끝 문단은
    필드만 떼고 남긴다. 새 칸을 넣을 자리(이 문단 앞, 없으면 None)를 돌려준다."""
    fid = next(fb.get("id") for fb in _direct(tops[s], "hp:fieldBegin") if fb.get("type") == "TABLEOFCONTENTS")
    target = tops[e + 1] if e + 1 < len(tops) else None
    for i in range(s, e + 1):
        p = tops[i]
        keep_begin = i == s and (i == 0 or any(next(p.iter(q(t)), None) is not None for t in _KEEP))
        keep_end = i == e and i != s and bool(own_text(p).strip())
        if keep_begin or keep_end:
            _drop_ctrl(p, "hp:fieldBegin", fid)
            _drop_ctrl(p, "hp:fieldEnd", fid)
            if keep_end:
                target = p
        else:
            root.remove(p)
    return target


def insert_toc(pkg: Package, kinds, *, level: int = 2, at: int | None = None,
               titles: list | None = None, scan: bool = True) -> list[str]:
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
    anchor = ref if at is not None else None  # 자기 자리가 없는 다음 칸은 앞 칸 바로 뒤에
    for kind in [k for k in ORDER if k in set(kinds)]:
        if kind == "제목":
            if titles is not None:
                mark_titles(pkg, level, titles)
            if titles is None or scan:
                mark_titles(pkg, level)
        entries = _entries(pkg, kind)
        if not entries:
            warnings.append(_EMPTY[kind])
            continue
        els = _block(pkg, kind, level, entries, ids)
        root, tops = _tops(pkg)
        existing = next(((s, e) for s, e, m in toc_blocks(tops) if _kind_of(m) == kind), None)
        drop = []
        if at is not None:
            if existing:  # 같은 종류 칸은 하나만
                _remove_block(root, tops, *existing)
            target = anchor
        else:
            idx, reason, drop_idx = find_slot(pkg, kind)
            own = reason == "기존 차례 칸" or reason == f"양식 {_LABEL[kind]} 자리"
            if not own and anchor is not None:
                target = anchor
            elif reason == "기존 차례 칸":
                if idx != 0:
                    els[0].set("pageBreak", tops[idx].get("pageBreak", "0"))
                target = _remove_block(root, tops, *existing)
            else:
                drop = [tops[i] for i in drop_idx]
                nxt = idx + len(drop_idx)
                target = tops[nxt] if nxt < len(tops) else None
                if reason == "표지 다음":
                    page_break = True
        for p in drop:
            root.remove(p)
        if page_break:
            els[0].set("pageBreak", "1")
            page_break = False
        _insert_before(root, target, els)
        anchor = target
    return warnings


_CHAPTER = re.compile(r"(표|그림)\s*\d+\s*[-–.]\s*\d+")
_REF = re.compile(r"(?<![가-힣A-Za-z])(표|그림)\s*(\d+)(?!\s*[-–.]?\s*\d)")


def uses_chapter_numbers(pkg: Package) -> bool:
    """캡션이 '[표 2-1]'처럼 장별 번호인가 (한글 상호 참조 번호로는 만들 수 없음)."""
    return any(_CHAPTER.search(all_text(cap)) for sec in pkg.section_names()
               for cap in pkg.xml(sec).iter(q("hp:caption")))


def _crossref(ids: _Ids, kind: str, obj_id: str):
    target = "0" if kind == "표" else "1"
    return _field_begin(ids, "CROSSREF", [
        ("boolean", "Fiexde", "1"), ("integer", "Prop", "0"),
        ("string", "Command", f"?#{obj_id};{target};1;0;0;"), ("string", "RefPath", f"?#{obj_id};"),
        ("string", "RefType", "TARGET_TABLE" if kind == "표" else "TARGET_PICTURE"),
        ("string", "RefContentType", "OBJECT_TYPE_NUMBER"), ("boolean", "RefHyperLink", "false"),
        ("string", "RefOpenType", "HWPHYPERLINK_JUMP_CURRENTTAB")])


def _t(text: str):
    t = etree.Element(q("hp:t"))
    t.text = text
    return t


def _link_t(run, t, objs: dict, ids: _Ids) -> int:
    text, pos, out, n = t.text, 0, [], 0
    for m in _REF.finditer(text):
        kind, num = m.group(1), int(m.group(2))
        if num not in objs[kind]:
            continue
        fb = _crossref(ids, kind, objs[kind][num])
        if text[pos:m.start(2)]:
            out.append(_t(text[pos:m.start(2)]))
        out += [_ctrl(fb), _t(m.group(2)), _ctrl(_field_end(fb))]
        pos, n = m.end(2), n + 1
    if not n:
        return 0
    if text[pos:]:
        out.append(_t(text[pos:]))
    at = list(run).index(t)
    run.remove(t)
    for k, el in enumerate(out):
        run.insert(at + k, el)
    return n


def link_refs(pkg: Package) -> tuple[int, str | None]:
    """본문의 '[표 3]', '그림 2'의 번호를 한글 상호 참조로 바꾼다. 장별 번호 문서는 그대로."""
    if uses_chapter_numbers(pkg):
        return 0, "chapter"
    root, tops = _tops(pkg)
    objs = {k: _numbered(root, k) for k in _TAG}
    skip, ids, n = _in_toc(tops), _Ids(pkg), 0
    for i, p in enumerate(tops):
        if i in skip:
            continue
        depth = 0  # 기존 필드(하이퍼링크·누름틀·메모 등) 안의 글은 건드리지 않는다
        for run in p.findall(q("hp:run")):  # 바로 아래 글만: 표 칸·캡션 안 글은 제외
            for el in list(run):
                if el.tag == q("hp:ctrl"):
                    depth += (el.find(q("hp:fieldBegin")) is not None) - (el.find(q("hp:fieldEnd")) is not None)
                elif el.tag == q("hp:t") and depth == 0 and len(el) == 0 and el.text:
                    n += _link_t(run, el, objs, ids)
    return n, None


def _numbered(root, kind: str) -> dict[int, str]:
    """한글이 보여 줄 번호 → 개체 id. 번호를 세는 개체(numberingType)를 문서 순서로 세고(새 번호 ctrl 반영),
    캡션에 한글 자동 번호가 있는 것만 담는다 (손으로 쓴 번호는 상호 참조로 만들지 않음)."""
    ntype = "TABLE" if kind == "표" else "PICTURE"
    out, n = {}, 0
    for el in root.iter(q(_TAG[kind]), q("hp:newNum")):
        if el.tag == q("hp:newNum"):
            if el.get("numType") == ntype:
                n = int(el.get("num", "1")) - 1
            continue
        if el.get("numberingType") != ntype:
            continue
        n += 1
        cap = el.find(q("hp:caption"))
        if cap is not None and next(cap.iter(q("hp:autoNum")), None) is not None:
            out[n] = el.get("id")
    return out
