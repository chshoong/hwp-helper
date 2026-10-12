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


def align(old: list[Unit], new: list[Unit]) -> tuple[dict[int, int], list[tuple[list[int], list[int], list[tuple[int, int]]]]]:
    """새 판 단위 번호 → 옛 판 단위 번호 (같은 글과 짝지은 수정), 그리고 바뀐 묶음들 (옛 번호들, 새 번호들, 짝)."""
    sm = difflib.SequenceMatcher(None, [u.text for u in old], [u.text for u in new], autojunk=False)
    new_to_old: dict[int, int] = {}
    blocks = []
    for tag, a1, a2, b1, b2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(a2 - a1):
                new_to_old[b1 + k] = a1 + k
            continue
        olds, news, pairs = list(range(a1, a2)), list(range(b1, b2)), []
        if tag == "replace":  # 바뀐 묶음 안에서 가장 비슷한 문단끼리 짝 (앞에 새 문단이 끼어도 수정으로)
            used: set[int] = set()
            for o in olds:
                best, score = None, 0.5
                for n in news:
                    if n in used:
                        continue
                    r = difflib.SequenceMatcher(None, old[o].text, new[n].text).ratio()
                    if r >= score:
                        best, score = n, r
                if best is not None:
                    used.add(best)
                    pairs.append((o, best))
                    new_to_old[best] = o
        blocks.append((olds, news, pairs))
    return new_to_old, blocks


def diff(old: list[Unit], new: list[Unit]) -> list[dict]:
    """add의 after_key = 바로 앞의 짝지어진 새 판 단위의 옛 key, before_key = 바로 뒤 것 (맨 앞 추가용).
    del의 near_key = 그 자리에 가장 가까운 새 판 단위 key (뒤 → 앞)."""
    new_to_old, blocks = align(old, new)
    old_to_new = {o: n for n, o in new_to_old.items()}
    out = []
    for olds, news, pairs in blocks:
        po, pn = {o for o, _ in pairs}, {n for _, n in pairs}
        for o, n in pairs:
            out.append({"kind": "edit", "old": old[o].text, "new": new[n].text, "where": new[n].where,
                        "old_key": old[o].key, "new_key": new[n].key})
        for o in olds:
            if o in po:
                continue
            near = next((old_to_new[j] for j in range(o + 1, len(old)) if j in old_to_new), None)
            if near is None:
                near = next((old_to_new[j] for j in range(o - 1, -1, -1) if j in old_to_new), None)
            out.append({"kind": "del", "old": old[o].text, "where": old[o].where, "old_key": old[o].key,
                        "near_key": new[near].key if near is not None else None})
        for n in news:
            if n in pn:
                continue
            prev = next((new_to_old[j] for j in range(n - 1, -1, -1) if j in new_to_old), None)
            nxt = next((new_to_old[j] for j in range(n + 1, len(new)) if j in new_to_old), None)
            out.append({"kind": "add", "new": new[n].text, "where": new[n].where, "new_key": new[n].key,
                        "after_key": old[prev].key if prev is not None else None,
                        "before_key": old[nxt].key if nxt is not None else None})
    return out


def memos(pkg: Package, elements: bool = False) -> list[dict]:
    """모든 구역의 한글 메모: 메모 글, 메모가 붙은 본문 글, 그 자리의 장. elements면 붙은 문단 요소("el")도."""
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
            m = {"text": _memo_text(bctrl), "anchor": anchor.strip(),
                 "where": where_of.get(p, "") if p is not None else ""}
            if elements:
                m["el"] = p
            out.append(m)
    return out
