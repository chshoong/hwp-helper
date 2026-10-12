"""여러 사람 의견 합치기: 의견 목록, 메모 글, 메모 자리(anchor), 고른 수정 반영 (설계 6장)."""
from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from .body import contains
from .compare import Unit, align, diff, memos, units
from .ns import q
from .package import Package

_SEP = re.compile(r"^[\s_\-–·]+")
ANCHOR_LEN = 40
_KEEP = ("hp:ctrl", "hp:secPr", "hp:tbl", "hp:pic", "hp:equation")  # 지우면 쪽 설정·개체가 함께 사라지는 것


class MergeError(ValueError):
    """의견 합치기 오류. 메시지는 사용자용 한국어."""


def opinion_name(base: Path, other: Path, taken: set[str]) -> str:
    stem, b = other.stem, base.stem
    name = _SEP.sub("", stem[len(b):]) if stem.startswith(b) and stem != b else stem
    name = name or stem
    if name in taken:
        name = stem
    taken.add(name)
    return name


def _unit_of(us: list[Unit], text: str) -> Unit | None:
    return next((u for u in us if text and text in u.raw), None)


def _hint(text: str | None) -> str:
    return (text or "").strip()[:ANCHOR_LEN].strip()


def opinions(base_pkg: Package, others: list[tuple[str, Package]], notes: list[dict] | None = None) -> list[dict]:
    base_units = units(base_pkg)
    base_memos = {(m["text"], m["anchor"]) for m in memos(base_pkg)}
    ops: list[dict] = []
    for who, pkg in others:
        other_units = units(pkg)
        new_to_old, _ = align(base_units, other_units)
        index_of = {u.el: k for k, u in enumerate(other_units)}  # 요소 자체가 열쇠
        for m in memos(pkg, elements=True):
            if (m["text"], m["anchor"]) in base_memos:
                continue
            op = {"who": who, "kind": "memo", "text": m["text"], "anchor": m["anchor"], "where": m["where"]}
            k = index_of.get(m["el"])
            if k in new_to_old:  # 메모가 붙은 문단과 짝인 원본 문단 (같은 글이 여러 번 나와도 그 자리)
                op["key"] = base_units[new_to_old[k]].key
            ops.append(op)
        for c in diff(base_units, other_units):
            if c["kind"] == "edit":
                ops.append({"who": who, "kind": "edit", "old": c["old"], "new": c["new"], "where": c["where"],
                            "key": c["old_key"]})
            elif c["kind"] == "del":
                ops.append({"who": who, "kind": "del", "old": c["old"], "where": c["where"], "key": c["old_key"]})
            else:
                ops.append({"who": who, "kind": "add", "new": c["new"], "where": c["where"], "key": c["after_key"],
                            "before_key": c["before_key"], "new_key": c["new_key"]})
    for n in notes or []:
        hint = _hint(n.get("where_text"))
        u = _unit_of(base_units, hint)
        op = {"who": n["who"], "kind": "note", "text": n["text"], "anchor": n.get("where_text", ""),
              "where": u.where if u else ""}
        if hint and sum(x.raw.count(hint) for x in base_units) > 1:
            op["ambiguous"] = True  # 같은 글이 여러 곳: 첫 자리에 달고 알린다
        ops.append(op)
    for k, op in enumerate(ops, 1):
        op["id"] = f"m{k}"
    for op in ops:
        op["conflict"] = [o["id"] for o in ops
                          if o is not op and op["kind"] in ("edit", "del") and o["kind"] in ("edit", "del")
                          and o["key"] == op["key"] and o["who"] != op["who"] and o.get("new") != op.get("new")]
    order = ["id", "who", "kind", "text", "anchor", "old", "new", "where", "key", "before_key", "new_key",
             "ambiguous", "conflict"]
    return [{k: op[k] for k in order if k in op} for op in ops]


def memo_text(op: dict) -> str:
    who, kind = op["who"], op["kind"]
    if kind in ("memo", "note"):
        body = f"[{who}] {op['text']}"
    elif kind == "edit":
        body = f"[{who} 수정] 원래: {op['old']} → 고친 글: {op['new']}"
    elif kind == "add":
        body = f"[{who} 추가] {op['new']}"
    else:
        body = f"[{who} 삭제 제안] {op['old']}"
    if op.get("ambiguous"):
        body = "[같은 글이 여러 곳: 첫 자리에 달았어요] " + body
    return ("[충돌] " if op.get("conflict") else "") + body


def _pieces(root) -> list[tuple[object, str]]:
    """한글 찾기 순서의 글 조각 (문단, 글). 탭 같은 hp:t 안의 요소에서 끊기고, 메모 내용은 뺀다."""
    out = []
    for t in root.iter(q("hp:t")):
        if any(a.tag == q("hp:fieldBegin") for a in t.iterancestors()):
            continue
        p = t.getparent().getparent()
        out.append((p, t.text or ""))
        out.extend((p, ch.tail or "") for ch in t)
    return out


def anchor_for(us: list[Unit], key: tuple | None, text: str | None = None, pos: bool = False):
    """메모를 붙일 글과, 문서 처음부터 그 글이 몇 번째로 나오는지 (한글 찾기 순서).
    key가 있으면 그 단위의 글 조각에서 text를 찾고, 없으면 그 단위의 첫 글 조각. pos면 조각 순번도."""
    if not us:
        return None
    pieces = _pieces(us[0].el.getroottree().getroot())
    text = _hint(text)
    if key is not None:
        u = next((u for u in us if u.key == key), None)
        if u is None:
            return None
        own = [k for k, (p, s) in enumerate(pieces) if p is u.el and s.strip()]
        hit = next((k for k in own if text and text in pieces[k][1]), None)
        if hit is None:
            if not own:
                return None
            hit, text = own[0], _hint(pieces[own[0]][1])
    else:
        hit = next((k for k, (_, s) in enumerate(pieces) if text and text in s), None)
        if hit is None:
            return None
    n = sum(s.count(text) for _, s in pieces[:hit]) + 1
    return (text, n, hit) if pos else (text, n)


def _target(us: list[Unit], op: dict) -> Unit | None:
    key = op.get("key")
    if op["kind"] == "add" and key is None:
        key = op.get("before_key")
    if key is not None:
        return next((u for u in us if u.key == key), None)
    if op["kind"] in ("memo", "note"):
        return _unit_of(us, _hint(op.get("anchor")))
    return None


def pin_targets(base_pkg: Package, ops: list[dict]) -> dict[str, object]:
    """반영 전에 각 의견이 붙을 문단 요소를 잡아 둔다 (반영으로 문단 번호가 바뀌어도 그 문단에)."""
    us = units(base_pkg)
    return {op["id"]: u.el for op in ops if (u := _target(us, op)) is not None}


def _plan(us: list[Unit], items: list[tuple[str | None, tuple | None, str]]) -> list[dict]:
    """(번호, 자리, 글) → 메모 계획. 못 찾은 자리는 첫 문단에, 같은 자리는 한 메모에, 문서 뒤쪽부터."""
    first = anchor_for(us, us[0].key, pos=True) if us else None
    plan: list[dict] = []
    for oid, spot, text in items:
        if spot is None:
            spot = first or ("", 1, 0)
            text = "[자리 못 찾음] " + text
        same = next((x for x in plan if (x["anchor"], x["n"]) == spot[:2]), None)
        if same is not None:  # 한 자리에 메모를 두 번 달면 둘째는 글을 못 찾는다 → 한 메모에 줄을 나눠
            if oid:
                same["id"] = f"{same['id']},{oid}" if same.get("id") else oid
            same["text"] += "\n" + text
            continue
        item = {"anchor": spot[0], "n": spot[1], "text": text, "_pos": spot[2]}
        if oid:
            item = {"id": oid, **item}
        plan.append(item)
    plan.sort(key=lambda x: -x["_pos"])  # 뒤쪽부터 달아 앞 메모가 뒤 자리 찾기에 끼어들지 않게
    for x in plan:
        del x["_pos"]
    return plan


def memo_plan(base_pkg: Package, ops: list[dict], pins: dict[str, object] | None = None) -> list[dict]:
    us = units(base_pkg)
    by_el = {u.el: u for u in us}
    items = []
    for op in ops:
        if pins is not None and op["id"] in pins:
            u = by_el.get(pins[op["id"]])
        else:
            u = _target(us, op)
        hint = op.get("anchor") if op["kind"] in ("memo", "note") else None
        spot = anchor_for(us, u.key, hint, pos=True) if u is not None else None
        items.append((op["id"], spot, memo_text(op)))
    return _plan(us, items)


def change_plan(new_pkg: Package, changes: list[dict]) -> list[dict]:
    """compare --memo: 새 판에 바뀐 곳 메모. 삭제는 그 자리 가까운 문단에."""
    us = units(new_pkg)
    items = []
    for c in changes:
        if c["kind"] == "del":
            key, text = c.get("near_key"), f"[삭제됨] {c['old']}"
        else:
            key = c["new_key"]
            text = "[추가됨]" if c["kind"] == "add" else f"[바뀜] 원래: {c['old']}"
        items.append((None, anchor_for(us, key, pos=True) if key is not None else None, text))
    return _plan(us, items)


def _top(el, root):
    """구역 바로 아래 문단 (표 칸 문단이면 그 표를 품은 문단)."""
    while el.getparent() is not root:
        el = el.getparent()
    return el


def _fresh(src, text: str):
    """src의 문단 모양·첫 글자 모양만 따른 새 문단 (쪽 설정·개체·메모는 따라오지 않게)."""
    from .editor.doc import _set_text
    p = src.makeelement(q("hp:p"), {"id": "0", "paraPrIDRef": src.get("paraPrIDRef", "0"),
                                     "styleIDRef": src.get("styleIDRef", "0"), "pageBreak": "0",
                                     "columnBreak": "0", "merged": "0"})
    runs = src.findall(q("hp:run"))
    run = next((r for r in runs if r.find(q("hp:t")) is not None), runs[0] if runs else None)
    etree.SubElement(p, q("hp:run"), {"charPrIDRef": run.get("charPrIDRef", "0") if run is not None else "0"})
    _set_text(p, text)
    return p


def accept(base_pkg: Package, ops: list[dict], ids: list[str]) -> tuple[list[str], list[str]]:
    """고른 의견만 원본 사본에 반영한다. 문단 모양·첫 글자 모양은 유지."""
    from .editor.doc import _set_text
    by_id = {o["id"]: o for o in ops}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise MergeError(f"없는 의견 번호예요: {', '.join(missing)} (있는 번호: {', '.join(by_id)})")
    for i in ids:
        both = [c for c in by_id[i]["conflict"] if c in ids]
        if both:
            raise MergeError(f"{i}와 {', '.join(both)}는 같은 곳을 다르게 고친 충돌 의견이에요. 하나만 골라 주세요.")
    order = {o["id"]: k for k, o in enumerate(ops)}
    chosen = sorted({by_id[i]["id"]: by_id[i] for i in ids}.values(), key=lambda o: order[o["id"]])
    root = base_pkg.edit(base_pkg.section_names()[0])
    us = {u.key: u for u in units(base_pkg)}
    tails: dict = {}  # 넣은 자리 → 마지막으로 넣은 문단 (여러 문단을 순서대로)
    applied, skipped = [], []

    def attached(u):
        return u is not None and any(a is root for a in u.el.iterancestors())

    for o in chosen:
        if o["kind"] in ("memo", "note"):
            skipped.append(f"{o['id']}: 메모 의견은 본문에 반영할 글이 없어요.")
            continue
        if o["kind"] in ("edit", "del"):
            u = us.get(o["key"])
            if not attached(u) or u.text != o["old"]:
                skipped.append(f"{o['id']}: 의견을 만든 뒤 원본 그 부분이 바뀌어 반영하지 않았어요.")
                continue
            if o["kind"] == "edit":
                _set_text(u.el, o["new"])
            else:
                parent = u.el.getparent()
                alone = parent.tag == q("hp:subList") and len(parent.findall(q("hp:p"))) == 1
                if alone or any(contains(u.el, t) for t in _KEEP):  # 칸의 마지막 문단, 쪽 설정·개체가 든 문단은 글만 비움
                    _set_text(u.el, "")
                else:
                    parent.remove(u.el)
            applied.append(o["id"])
            continue
        new_key = o["new_key"]
        a = us.get(o["key"]) if o.get("key") is not None else None
        b = us.get(o["before_key"]) if o.get("before_key") is not None else None
        if a is not None:
            if not attached(a):
                skipped.append(f"{o['id']}: 넣을 자리를 찾지 못해 반영하지 않았어요.")
                continue
            if new_key[0] == "p":
                at = a.el if a.key[0] == "p" else _top(a.el, root)
            elif a.key[0] == "c" and a.key[2:5] == new_key[2:5]:
                at = a.el
            else:
                skipped.append(f"{o['id']}: 표 구조가 달라 넣을 자리를 정하지 못했어요. 직접 넣어 주세요.")
                continue
            new = _fresh(at, o["new"])
            tails.get(at, at).addnext(new)
            tails[at] = new
        elif attached(b) and new_key[0] == "p":  # 맨 앞에 넣은 문단: 뒤 문단 앞에
            at = _top(b.el, root)
            new = _fresh(at, o["new"])
            prev = tails.get(("before", at))
            if prev is None:
                at.addprevious(new)
            else:
                prev.addnext(new)
            tails[("before", at)] = new
        else:
            skipped.append(f"{o['id']}: 넣을 자리를 찾지 못해 반영하지 않았어요.")
            continue
        applied.append(o["id"])
    return applied, skipped
