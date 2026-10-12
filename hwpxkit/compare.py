"""두 판의 문단·표 칸 비교와 메모 읽기 (설계 3·4장)."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .body import own_text, t_text
from .fit import headings
from .form import _memo_text, tables
from .ns import q
from .package import Package


@dataclass
class Unit:
    key: tuple
    text: str
    raw: str
    where: str
    el: object = field(repr=False, compare=False)


def _norm(s: str) -> str:
    return " ".join(s.split())


def units(pkg: Package) -> list[Unit]:
    """첫 구역의 최상위 문단과 표 칸 문단 (문서 순서, 빈 글 제외)."""
    root = pkg.xml(pkg.section_names()[0])
    numbers = {t: n for n, t in enumerate(tables(pkg), 1)}  # lxml 요소 자체가 열쇠 (id()는 바뀔 수 있음)
    heads = {i: title for i, title, _ in headings(pkg, 2)}
    out, chapter = [], "(앞부분)"
    for i, p in enumerate(x for x in root if x.tag == q("hp:p")):
        if i in heads:
            chapter = heads[i]
        raw = own_text(p).strip()
        if raw:
            out.append(Unit(("p", i), _norm(raw), raw, chapter, p))
        for run in p.findall(q("hp:run")):
            for tbl in run.findall(q("hp:tbl")):
                t = numbers.get(tbl, 0)
                for tr in tbl.findall(q("hp:tr")):
                    for tc in tr.findall(q("hp:tc")):
                        a = tc.find(q("hp:cellAddr"))
                        r, c = int(a.get("rowAddr")), int(a.get("colAddr"))
                        sub = tc.find(q("hp:subList"))
                        for k, cp in enumerate(sub.findall(q("hp:p")) if sub is not None else []):
                            craw = own_text(cp).strip()
                            if craw:
                                out.append(Unit(("c", i, t, r, c, k), _norm(craw), craw,
                                                f"{chapter} · 표{t} {r + 1}행 {c + 1}열", cp))
    return out


def diff(old: list[Unit], new: list[Unit]) -> list[dict]:
    out = []
    sm = difflib.SequenceMatcher(None, [u.text for u in old], [u.text for u in new], autojunk=False)
    for tag, a1, a2, b1, b2 in sm.get_opcodes():
        if tag == "equal":
            continue
        olds, news = old[a1:a2], new[b1:b2]
        pairs = []
        if tag == "replace":  # 바뀐 묶음 안에서 가장 비슷한 문단끼리 짝 (앞에 새 문단이 끼어도 수정으로)
            used: set[int] = set()
            for o in olds:
                best, score = None, 0.5
                for n in news:
                    if id(n) in used:
                        continue
                    r = difflib.SequenceMatcher(None, o.text, n.text).ratio()
                    if r >= score:
                        best, score = n, r
                if best is not None:
                    used.add(id(best))
                    pairs.append((o, best))
        paired_o = {id(o) for o, _ in pairs}
        paired_n = {id(n) for _, n in pairs}
        for o, n in pairs:
            out.append({"kind": "edit", "old": o.text, "new": n.text, "where": n.where,
                        "old_key": o.key, "new_key": n.key})
        for o in olds:
            if id(o) not in paired_o:
                out.append({"kind": "del", "old": o.text, "where": o.where, "old_key": o.key})
        after = old[a1 - 1].key if a1 > 0 else None
        for n in news:
            if id(n) not in paired_n:
                out.append({"kind": "add", "new": n.text, "where": n.where, "new_key": n.key, "after_key": after})
    return out


def memos(pkg: Package) -> list[dict]:
    """모든 구역의 한글 메모: 메모 글, 메모가 붙은 본문 글, 그 자리의 장."""
    where_of = {u.el: u.where for u in units(pkg)}  # 요소 자체가 열쇠
    out = []
    for sec in pkg.section_names():
        root = pkg.xml(sec)
        for begin in root.iter(q("hp:fieldBegin")):
            if begin.get("type") != "MEMO":
                continue
            bctrl = begin.getparent()
            end = next((e for e in root.iter(q("hp:fieldEnd")) if e.get("beginIDRef") == begin.get("id")), None)
            ectrl = end.getparent() if end is not None else None
            anchor, inside = "", False
            for ch in bctrl.getparent():
                if ch is bctrl:
                    inside = True
                    continue
                if ch is ectrl:
                    break
                if inside and ch.tag == q("hp:t"):
                    anchor += t_text(ch)
            p = next((a for a in bctrl.iterancestors() if a.tag == q("hp:p")), None)
            out.append({"text": _memo_text(bctrl), "anchor": anchor.strip(),
                        "where": where_of.get(p, "") if p is not None else ""})
    return out
