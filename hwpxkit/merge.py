"""여러 사람 의견 합치기: 의견 목록, 메모 글, 메모 자리(anchor), 고른 수정 반영 (설계 6장)."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from .compare import Unit, diff, memos, units
from .package import Package

_SEP = re.compile(r"^[\s_\-–·]+")
ANCHOR_LEN = 40


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


def opinions(base_pkg: Package, others: list[tuple[str, Package]], notes: list[dict] | None = None) -> list[dict]:
    base_units = units(base_pkg)
    base_memos = {(m["text"], m["anchor"]) for m in memos(base_pkg)}
    ops: list[dict] = []
    for who, pkg in others:
        for m in memos(pkg):
            if (m["text"], m["anchor"]) in base_memos:
                continue
            ops.append({"who": who, "kind": "memo", "text": m["text"], "anchor": m["anchor"], "where": m["where"]})
        for c in diff(base_units, units(pkg)):
            if c["kind"] == "edit":
                ops.append({"who": who, "kind": "edit", "old": c["old"], "new": c["new"], "where": c["where"],
                            "key": c["old_key"]})
            elif c["kind"] == "del":
                ops.append({"who": who, "kind": "del", "old": c["old"], "where": c["where"], "key": c["old_key"]})
            else:
                ops.append({"who": who, "kind": "add", "new": c["new"], "where": c["where"], "key": c["after_key"]})
    for n in notes or []:
        u = _unit_of(base_units, n.get("where_text", ""))
        ops.append({"who": n["who"], "kind": "note", "text": n["text"], "anchor": n.get("where_text", ""),
                    "where": u.where if u else ""})
    for k, op in enumerate(ops, 1):
        op["id"] = f"m{k}"
    for op in ops:
        op["conflict"] = [o["id"] for o in ops
                          if o is not op and op["kind"] in ("edit", "del") and o["kind"] in ("edit", "del")
                          and o["key"] == op["key"] and o["who"] != op["who"] and o.get("new") != op.get("new")]
    order = ["id", "who", "kind", "text", "anchor", "old", "new", "where", "key", "conflict"]
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
    return ("[충돌] " if op.get("conflict") else "") + body


def anchor_for(us: list[Unit], key: tuple | None, text: str | None = None) -> tuple[str, int] | None:
    """메모를 붙일 글과, 문서 처음부터 그 글이 몇 번째로 나오는지 (한글 찾기 순서)."""
    if key is not None:
        idx = next((k for k, u in enumerate(us) if u.key == key), None)
        if idx is None:
            return None
        anchor = us[idx].raw[:ANCHOR_LEN].strip()
    else:
        idx = next((k for k, u in enumerate(us) if text and text in u.raw), None)
        if idx is None:
            return None
        anchor = text
    n = sum(u.raw.count(anchor) for u in us[:idx]) + 1
    return anchor, n


def memo_plan(base_pkg: Package, ops: list[dict]) -> list[dict]:
    us = units(base_pkg)
    plan = []
    for op in ops:
        if op["kind"] in ("memo", "note"):
            spot = anchor_for(us, None, text=(op.get("anchor") or "")[:ANCHOR_LEN].strip() or None)
        else:
            spot = anchor_for(us, op["key"]) if op.get("key") is not None else ((us[0].raw[:ANCHOR_LEN].strip(), 1) if us else None)
        text = memo_text(op)
        if spot is None:
            spot = (us[0].raw[:ANCHOR_LEN].strip(), 1) if us else ("", 1)
            text = "[자리 못 찾음] " + text
        same = next((x for x in plan if (x["anchor"], x["n"]) == spot), None)
        if same is not None:  # 한 자리에 메모를 두 번 달면 둘째는 글을 못 찾는다 → 한 메모에 줄을 나눠
            same["id"] += f",{op['id']}"
            same["text"] += "\n" + text
            continue
        plan.append({"id": op["id"], "anchor": spot[0], "n": spot[1], "text": text})
    return plan


def accept(base_pkg: Package, ops: list[dict], ids: list[str]) -> tuple[list[str], list[str]]:
    """고른 의견만 원본 사본에 반영한다. 문단 모양·첫 글자 모양은 유지."""
    from .editor.doc import _set_text
    from .ns import q
    by_id = {o["id"]: o for o in ops}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise MergeError(f"없는 의견 번호예요: {', '.join(missing)} (있는 번호: {', '.join(by_id)})")
    chosen = [by_id[i] for i in ids]
    for o in chosen:
        both = [c for c in o["conflict"] if c in ids]
        if both:
            raise MergeError(f"{o['id']}와 {', '.join(both)}는 같은 곳을 다르게 고친 충돌 의견이에요. 하나만 골라 주세요.")
    pkg_root = base_pkg.edit(base_pkg.section_names()[0])
    us = {u.key: u for u in units(base_pkg)}
    applied, skipped = [], []
    for o in chosen:
        if o["kind"] in ("memo", "note"):
            skipped.append(f"{o['id']}: 메모 의견은 본문에 반영할 글이 없어요.")
            continue
        u = us.get(o["key"]) if o.get("key") is not None else None
        if o["kind"] in ("edit", "del") and (u is None or u.text != o["old"]):
            skipped.append(f"{o['id']}: 의견을 만든 뒤 원본 그 부분이 바뀌어 반영하지 않았어요.")
            continue
        if o["kind"] == "edit":
            _set_text(u.el, o["new"])
        elif o["kind"] == "del":
            parent = u.el.getparent()
            siblings = [x for x in parent if x.tag == q("hp:p")]
            if parent.tag == q("hp:subList") and len(siblings) == 1:
                _set_text(u.el, "")
            else:
                parent.remove(u.el)
        else:  # add: 앞 단위 문단을 복제해 그 뒤에
            if u is None or u.el.getparent() is None:  # 앞 단위가 같은 반영에서 지워졌으면
                skipped.append(f"{o['id']}: 넣을 자리를 찾지 못해 반영하지 않았어요.")
                continue
            clone = copy.deepcopy(u.el)
            _set_text(clone, o["new"])
            u.el.addnext(clone)
        applied.append(o["id"])
    return applied, skipped
