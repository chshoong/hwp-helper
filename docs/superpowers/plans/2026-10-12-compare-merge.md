# 이전 판 비교(compare)와 의견 합치기(merge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 두 판의 문단·표 칸 비교(`compare`), 여러 사람의 메모·직접 수정·따로 받은 의견을 원본 사본 하나에 이름 붙인 한글 메모로 모으고 고른 것만 반영하는 `merge`를 만든다.

**Architecture:** `hwpxkit/compare.py`가 비교 단위(최상위 문단·칸 문단)·diff·메모 읽기를, `hwpxkit/merge.py`가 의견 목록·메모 글·anchor 고르기·반영을 맡는다. 메모 달기는 `bridge_hwp.ps1`의 새 동작 `memos`(숨은 한글 InsertFieldMemo)로 하고, 반영은 엔진이 문단 글을 직접 바꾼다(`editor.doc._set_text`).

**Tech Stack:** Python 3.10+, difflib, lxml, 한글 COM.

**Spec:** docs/superpowers/specs/2026-10-12-compare-merge-design.md

## Global Constraints

- 원본·의견 파일은 읽기만 한다. 결과는 항상 새 파일(같은 경로면 거절).
- 자동 반영 없음. `--accept`로 고른 의견만 반영한다.
- 반영 전 원본 글이 의견을 만들 때와 같은지 확인한다(다르면 건너뜀).
- 새 의존성 없음. 사용자에게 보이는 글은 한국어 존댓말.
- 사용자 실제 문서(private/)는 시험·공개 파일에 쓰지 않는다.

## Review Focus

1. 같은 글이 문서에 여러 번(예: "해당 없음") — 메모가 맞는 자리(n번째)에 달려야 한다 (Task 2 `test_anchor_counts_earlier_occurrences`, Task 5 한글 시험).
2. 두 사람이 같은 문단을 다르게 고침 — 충돌 표시, 둘 다 반영하려 하면 멈춤 (Task 2 `test_conflict_marked`, Task 3 `test_accept_both_conflicting_refused`).
3. 의견 파일을 만든 뒤 원본이 바뀜 — 그 의견은 반영하지 않고 알림 (Task 3 `test_accept_skips_changed_original`).
4. 칸의 유일한 문단 삭제 제안 — 칸이 깨지지 않게 글만 비움 (Task 3 `test_delete_last_cell_paragraph_blanks`).
5. 메모 내용(필드 안 글)이 비교 글에 섞임 — 메모만 단 파일은 수정으로 나오면 안 된다 (Task 1 `test_memo_text_not_in_units`).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `hwpxkit/compare.py` (새로) | `Unit`, `units`, `diff`, `memos` |
| `hwpxkit/merge.py` (새로) | `opinion_name`, `opinions`, `memo_text`, `anchor_for`, `memo_plan`, `accept` |
| `hwpxkit/bridge_hwp.ps1`, `hwpxkit/bridge.py` | 동작 `memos`, `add_memos(src, dst, memos)` |
| `hwpxkit/cli.py` | `compare`, `merge` 명령 |
| `skills/hwp-helper/reference/merge.md`, `SKILL.md`, `README.md`, `.claude-plugin/plugin.json`, `tests/test_plugin_files.py` | 안내, 0.7.0 |
| `tests/test_merge.py` (새로) | 시험 |

---

### Task 1: 비교 단위·diff·메모 읽기 (`compare.py`)

**Files:**
- Create: `hwpxkit/compare.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Produces:
  - `@dataclass Unit: key: tuple; text: str; raw: str; where: str; el` — key `("p", i)` 또는 `("c", i, t, r, c, k)`; text는 공백 하나로 줄인 글, raw는 원래 글
  - `units(pkg) -> list[Unit]` (빈 글 제외, 첫 구역)
  - `diff(old: list[Unit], new: list[Unit]) -> list[dict]` — kind "add"|"del"|"edit"; edit은 `old, new, where, old_key, new_key`; del은 `old, where, old_key`; add는 `new, where, new_key, after_key`(앞 old 단위 key 또는 None)
  - `memos(pkg) -> list[dict]` — `{"text", "anchor", "where"}`

- [ ] **Step 1: Write the failing test**

```python
"""이전 판 비교(compare)와 의견 합치기(merge)."""
import json
import shutil

import pytest

from helpers import LONG, SECTION, append_to_body, memo_run, para, table
from hwpxkit.ns import q
from hwpxkit.package import Package


def base_doc(blank, tmp_path, name="보고서.hwpx"):
    pkg = Package.open(blank)
    append_to_body(pkg, para("제1장 서론"))
    append_to_body(pkg, para("연구 배경을 설명하는 첫 문단이다. " + LONG))
    append_to_body(pkg, para("연구 목적을 설명하는 둘째 문단이다. " + LONG))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "구분", (0, 1): "값", (1, 0): "표본", (1, 1): "120명"}))
    append_to_body(pkg, para("제2장 방법"))
    append_to_body(pkg, para("해당 없음"))
    append_to_body(pkg, para("자료 수집 절차를 설명한다. " + LONG))
    append_to_body(pkg, para("해당 없음"))
    return pkg.save(tmp_path / name)


def tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def edited(src, dst, change):
    """src 사본을 만들고 change(pkg)로 고쳐 dst에 저장."""
    shutil.copy(src, dst)
    pkg = Package.open(dst)
    change(pkg)
    out = dst.with_name(dst.stem + ".tmp.hwpx")
    pkg.save(out)
    out.replace(dst)
    return dst


def set_text(pkg, i, text):
    from hwpxkit.editor.doc import _set_text
    _set_text(tops(pkg)[i] if False else [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][i], text)


def test_units_and_where(blank, tmp_path):
    from hwpxkit.compare import units
    us = units(Package.open(base_doc(blank, tmp_path)))
    keys = [u.key for u in us]
    assert ("p", 2) in keys and ("c", 4, 1, 1, 1, 0) in keys
    cell = next(u for u in us if u.key == ("c", 4, 1, 1, 1, 0))
    assert cell.text == "120명" and cell.where == "제1장 서론 · 표1 2행 2열"
    assert next(u for u in us if u.key == ("p", 7)).where == "제2장 방법"
    assert all(u.text for u in us)


def test_diff_edit_add_del(blank, tmp_path):
    from hwpxkit.compare import diff, units
    src = base_doc(blank, tmp_path)

    def change(pkg):
        set_text(pkg, 2, "연구 목적을 설명하는 둘째 문단이며 조금 고쳤다. " + LONG)
        root = pkg.edit(SECTION)
        ps = [p for p in root if p.tag == q("hp:p")]
        root.remove(ps[7])  # 자료 수집 절차 문단 삭제
        root.insert(root.index(ps[1]) + 1, para("새로 넣은 문단이다."))
        from hwpxkit.editor.doc import _set_text
        cell = [tc for tc in root.iter(q("hp:tc"))][3]
        _set_text(cell.find(q("hp:subList")).find(q("hp:p")), "150명")
    new = edited(src, tmp_path / "새판.hwpx", change)
    changes = diff(units(Package.open(src)), units(Package.open(new)))
    kinds = sorted((c["kind"], c.get("new", c.get("old"))[:10]) for c in changes)
    assert ("add", "새로 넣은 문단이다.") in kinds
    assert ("del", "자료 수집 절차를 ") in kinds
    edits = {c["old"][:6]: c for c in changes if c["kind"] == "edit"}
    assert set(edits) == {"연구 목적을", "120명"}
    assert edits["120명"]["new"] == "150명" and edits["120명"]["where"] == "제1장 서론 · 표1 2행 2열"
    add = next(c for c in changes if c["kind"] == "add")
    assert add["after_key"] == ("p", 2)


def test_memos_read(blank, tmp_path):
    from hwpxkit.compare import memos
    src = base_doc(blank, tmp_path)

    def change(pkg):
        p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
        p.append(memo_run("메모가 붙은 글", "근거를 더 쓰세요"))
    out = edited(src, tmp_path / "메모.hwpx", change)
    ms = memos(Package.open(out))
    assert ms == [{"text": "근거를 더 쓰세요", "anchor": "메모가 붙은 글", "where": "제1장 서론"}]


def test_memo_text_not_in_units(blank, tmp_path):
    from hwpxkit.compare import diff, units
    src = base_doc(blank, tmp_path)

    def change(pkg):
        p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
        run = memo_run("", "근거를 더 쓰세요")
        for el in list(run):
            if el.tag == q("hp:t"):
                run.remove(el)
        p.insert(0, run)
    out = edited(src, tmp_path / "메모만.hwpx", change)
    assert diff(units(Package.open(src)), units(Package.open(out))) == []
```

`set_text`의 첫 줄은 단순하게 다음으로 쓴다(위 줄 대신):

```python
def set_text(pkg, i, text):
    from hwpxkit.editor.doc import _set_text
    _set_text([p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][i], text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_merge.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hwpxkit.compare'`

- [ ] **Step 3: Write implementation**

```python
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
    numbers = {id(t): n for n, t in enumerate(tables(pkg), 1)}
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
                t = numbers.get(id(tbl), 0)
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
        if tag == "replace":
            for o, n in zip(olds, news):
                if difflib.SequenceMatcher(None, o.text, n.text).ratio() >= 0.5:
                    pairs.append((o, n))
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
    where_of = {id(u.el): u.where for u in units(pkg)}
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
                        "where": where_of.get(id(p), "")})
    return out
```

`_memo_text`는 `form`에 있는 내부 함수다(메모 칸 글을 공백 하나로 이음). `form.tables`는 문서 순서로 표를 센다(칸 주소 `표N`과 같은 번호).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_merge.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/compare.py tests/test_merge.py
git commit -m "feat: 두 판 문단·표 칸 비교와 메모 읽기"
```

---

### Task 2: 의견 목록·메모 글·anchor (`merge.py` 앞부분)

**Files:**
- Create: `hwpxkit/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `units`, `diff`, `memos`, `Unit`
- Produces:
  - `opinion_name(base: Path, other: Path, taken: set[str]) -> str`
  - `opinions(base_pkg, others: list[tuple[str, Package]], notes: list[dict] | None = None) -> list[dict]` — 항목 키: `id, who, kind (memo|edit|add|del|note), text?, anchor?, old?, new?, where, key?, conflict (list[str])`
  - `memo_text(op: dict) -> str`
  - `anchor_for(us: list[Unit], key: tuple | None, text: str | None = None) -> tuple[str, int] | None` — (찾을 글, n번째)
  - `memo_plan(base_pkg, ops: list[dict]) -> list[dict]` — `[{"anchor", "n", "text", "id"}]`

- [ ] **Step 1: Write the failing tests**

```python
def opinion_files(blank, tmp_path):
    src = base_doc(blank, tmp_path)

    def hong(pkg):
        set_text(pkg, 2, "연구 목적을 설명하는 둘째 문단이며 홍이 고쳤다. " + LONG)
        p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][1]
        p.append(memo_run("연구 배경", "출처를 다세요"))

    def kim(pkg):
        set_text(pkg, 2, "연구 목적을 설명하는 둘째 문단이며 김이 고쳤다. " + LONG)
    a = edited(src, tmp_path / "보고서_홍길동.hwpx", hong)
    b = edited(src, tmp_path / "보고서-김철수.hwpx", kim)
    return src, a, b


def test_opinion_name():
    from pathlib import Path
    from hwpxkit.merge import opinion_name
    base = Path("보고서.hwpx")
    taken = set()
    assert opinion_name(base, Path("보고서_홍길동.hwpx"), taken) == "홍길동"
    assert opinion_name(base, Path("보고서-김철수.hwpx"), taken) == "김철수"
    assert opinion_name(base, Path("보고서_홍길동.hwpx"), taken) == "보고서_홍길동"  # 겹치면 파일 이름
    assert opinion_name(base, Path("의견.hwpx"), taken) == "의견"


def test_opinions_numbered_with_conflict(blank, tmp_path):
    from hwpxkit.merge import opinions
    src, a, b = opinion_files(blank, tmp_path)
    ops = opinions(Package.open(src), [("홍길동", Package.open(a)), ("김철수", Package.open(b))])
    assert [o["id"] for o in ops] == ["m1", "m2", "m3"]
    kinds = [(o["who"], o["kind"]) for o in ops]
    assert kinds == [("홍길동", "memo"), ("홍길동", "edit"), ("김철수", "edit")]
    assert ops[1]["conflict"] == ["m3"] and ops[2]["conflict"] == ["m2"] and ops[0]["conflict"] == []


def test_conflict_marked(blank, tmp_path):
    from hwpxkit.merge import memo_text, opinions
    src, a, b = opinion_files(blank, tmp_path)
    ops = opinions(Package.open(src), [("홍길동", Package.open(a)), ("김철수", Package.open(b))])
    assert memo_text(ops[0]) == "[홍길동] 출처를 다세요"
    assert memo_text(ops[1]).startswith("[충돌] [홍길동 수정] 원래: 연구 목적을") and "→ 고친 글:" in memo_text(ops[1])


def test_original_memos_not_repeated(blank, tmp_path):
    from hwpxkit.merge import opinions
    src = base_doc(blank, tmp_path)
    with_memo = edited(src, tmp_path / "원본메모.hwpx",
                       lambda pkg: [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][1].append(
                           memo_run("연구 배경", "원래 있던 메모")))
    copy = tmp_path / "원본메모_박.hwpx"
    shutil.copy(with_memo, copy)
    assert opinions(Package.open(with_memo), [("박", Package.open(copy))]) == []


def test_notes_become_opinions(blank, tmp_path):
    from hwpxkit.merge import opinions
    src = base_doc(blank, tmp_path)
    ops = opinions(Package.open(src), [], notes=[{"who": "교수님", "where_text": "자료 수집 절차", "text": "표본 크기 근거"}])
    assert ops == [{"id": "m1", "who": "교수님", "kind": "note", "text": "표본 크기 근거", "anchor": "자료 수집 절차",
                    "where": "제2장 방법", "conflict": []}]


def test_anchor_counts_earlier_occurrences(blank, tmp_path):
    from hwpxkit.compare import units
    from hwpxkit.merge import anchor_for
    us = units(Package.open(base_doc(blank, tmp_path)))
    assert anchor_for(us, ("p", 8)) == ("해당 없음", 2)
    assert anchor_for(us, ("p", 6)) == ("해당 없음", 1)
    assert anchor_for(us, None, text="자료 수집 절차") == ("자료 수집 절차", 1)
    assert anchor_for(us, None, text="없는 글") is None


def test_memo_plan_falls_back(blank, tmp_path):
    from hwpxkit.merge import memo_plan, opinions
    src = base_doc(blank, tmp_path)
    ops = opinions(Package.open(src), [], notes=[{"who": "교수님", "where_text": "없는 글", "text": "의견"}])
    plan = memo_plan(Package.open(src), ops)
    assert plan[0]["anchor"] == "제1장 서론" and plan[0]["text"].startswith("[자리 못 찾음] [교수님]")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_merge.py -q -k "opinion or conflict or original or notes or anchor or plan"`
Expected: FAIL — `ModuleNotFoundError: No module named 'hwpxkit.merge'`

- [ ] **Step 3: Write implementation**

```python
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
            spot = anchor_for(us, None, text=op.get("anchor") or None)
        else:
            spot = anchor_for(us, op.get("key")) if op.get("key") is not None else None
        text = memo_text(op)
        if spot is None:
            spot = (us[0].raw[:ANCHOR_LEN].strip(), 1) if us else ("", 1)
            text = "[자리 못 찾음] " + text
        plan.append({"id": op["id"], "anchor": spot[0], "n": spot[1], "text": text})
    return plan
```

`add`의 key가 None(문서 맨 앞 추가)이면 `memo_plan`이 첫 단위에 "[자리 못 찾음]" 없이 붙이도록, 위 `else` 분기를 다음으로 쓴다:

```python
        else:
            spot = anchor_for(us, op["key"]) if op.get("key") is not None else ((us[0].raw[:ANCHOR_LEN].strip(), 1) if us else None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_merge.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/merge.py tests/test_merge.py
git commit -m "feat: 의견 목록(메모·수정·노트), 충돌, 메모 글, 메모 자리"
```

---

### Task 3: 고른 의견 반영 (`accept`)

**Files:**
- Modify: `hwpxkit/merge.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Produces: `accept(base_pkg, ops: list[dict], ids: list[str]) -> tuple[list[str], list[str]]` — (반영한 id, 건너뛴 이유 글). 없는 id·충돌 둘 다 → `MergeError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_accept_edit_keeps_format(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    before = tops(base)[2].get("paraPrIDRef"), tops(base)[2].find(q("hp:run")).get("charPrIDRef")
    ops = opinions(base, [("홍길동", Package.open(a))])
    applied, skipped = accept(base, ops, ["m2"])
    from hwpxkit.body import own_text
    p = tops(base)[2]
    assert applied == ["m2"] and skipped == []
    assert "홍이 고쳤다" in own_text(p) and (p.get("paraPrIDRef"), p.find(q("hp:run")).get("charPrIDRef")) == before


def test_accept_cell_edit_add_del(blank, tmp_path):
    from hwpxkit.body import own_text
    from hwpxkit.compare import units
    from hwpxkit.merge import accept, opinions
    src = base_doc(blank, tmp_path)

    def change(pkg):
        from hwpxkit.editor.doc import _set_text
        root = pkg.edit(SECTION)
        cell = [tc for tc in root.iter(q("hp:tc"))][3]
        _set_text(cell.find(q("hp:subList")).find(q("hp:p")), "150명")
        ps = [p for p in root if p.tag == q("hp:p")]
        root.remove(ps[7])
        root.insert(root.index(ps[2]) + 1, para("셋째로 넣은 문단."))
    other = edited(src, tmp_path / "보고서_이.hwpx", change)
    base = Package.open(src)
    ops = opinions(base, [("이", Package.open(other))])
    applied, skipped = accept(base, ops, [o["id"] for o in ops])
    texts = [u.text for u in units(base)]
    assert "150명" in texts and "셋째로 넣은 문단." in texts and not any(t.startswith("자료 수집") for t in texts)
    assert texts.index("셋째로 넣은 문단.") == texts.index(next(t for t in texts if t.startswith("연구 목적"))) + 1


def test_accept_skips_changed_original(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    ops = opinions(base, [("홍길동", Package.open(a))])
    set_text(base, 2, "그 사이 원본이 바뀜")
    applied, skipped = accept(base, ops, ["m2"])
    assert applied == [] and "m2" in skipped[0]


def test_accept_both_conflicting_refused(blank, tmp_path):
    from hwpxkit.merge import MergeError, accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    ops = opinions(base, [("홍길동", Package.open(a)), ("김철수", Package.open(b))])
    with pytest.raises(MergeError, match="충돌"):
        accept(base, ops, ["m2", "m3"])
    with pytest.raises(MergeError, match="m9"):
        accept(base, ops, ["m9"])


def test_delete_last_cell_paragraph_blanks(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src = base_doc(blank, tmp_path)

    def change(pkg):
        from hwpxkit.editor.doc import _set_text
        cell = [tc for tc in pkg.edit(SECTION).iter(q("hp:tc"))][3]
        _set_text(cell.find(q("hp:subList")).find(q("hp:p")), "")
    other = edited(src, tmp_path / "보고서_최.hwpx", change)
    base = Package.open(src)
    ops = opinions(base, [("최", Package.open(other))])
    assert [o["kind"] for o in ops] == ["del"]
    accept(base, ops, ["m1"])
    cell = [tc for tc in base.xml(SECTION).iter(q("hp:tc"))][3]
    assert len(cell.find(q("hp:subList")).findall(q("hp:p"))) == 1


def test_accept_memo_ignored(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    ops = opinions(base, [("홍길동", Package.open(a))])
    applied, skipped = accept(base, ops, ["m1"])
    assert applied == [] and "메모" in skipped[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_merge.py -q -k "accept or delete_last"`
Expected: FAIL — `ImportError: cannot import name 'accept'`

- [ ] **Step 3: Write implementation** (merge.py에 추가)

```python
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
            if u is None:
                skipped.append(f"{o['id']}: 넣을 자리를 찾지 못해 반영하지 않았어요.")
                continue
            clone = copy.deepcopy(u.el)
            _set_text(clone, o["new"])
            u.el.addnext(clone)
        applied.append(o["id"])
    return applied, skipped
```

`del`이 앞에 와서 `u.el`이 문서에서 빠진 뒤에도 다른 의견은 자기 `u.el`(다른 문단)을 쓰므로 순서는 상관없다. `add`의 key 단위가 같은 accept에서 지워졌으면(`u.el.getparent() is None`) 건너뛰도록 `add` 분기 첫 줄을 `if u is None or u.el.getparent() is None:`로 쓴다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_merge.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/merge.py tests/test_merge.py
git commit -m "feat: 고른 의견만 반영(수정·추가·삭제), 바뀐 원본·충돌 거절"
```

---

### Task 4: 한글 메모 달기와 `compare`·`merge` 명령

**Files:**
- Modify: `hwpxkit/bridge_hwp.ps1`, `hwpxkit/bridge.py`, `hwpxkit/cli.py`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: `units`, `diff`, `opinions`, `memo_plan`, `accept`, `MergeError`
- Produces:
  - `bridge.add_memos(src, dst, memos: list[dict]) -> tuple[int, list[dict]]` (단 수, 못 단 메모)
  - CLI `compare <옛판> <새판> [--memo OUT] [--json]`, `merge <원본> <의견…> <모음본> [--accept ids] [--notes FILE] [--json]`

- [ ] **Step 1: Write the failing tests**

```python
def test_add_memos_uses_bridge(tmp_path, monkeypatch):
    from hwpxkit import bridge
    seen = {}

    def fake_run(action, work, *, src=None, dst=None, fmt=None, timeout=0):
        seen["action"], seen["memos"] = action, json.loads(open(fmt, encoding="utf-8").read())
        open(dst, "wb").write(b"x")
        return {"ok": True, "placed": 1, "missed": [1]}
    monkeypatch.setattr(bridge, "_require", lambda: None)
    monkeypatch.setattr(bridge, "_run", fake_run)
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"y")
    memos = [{"anchor": "가", "n": 1, "text": "m"}, {"anchor": "나", "n": 2, "text": "n"}]
    placed, missed = bridge.add_memos(src, tmp_path / "b.hwpx", memos)
    assert seen["action"] == "memos" and seen["memos"] == memos and placed == 1 and missed == [memos[1]]
    assert (tmp_path / "b.hwpx").read_bytes() == b"x"


def test_cli_compare(blank, tmp_path, capsys, monkeypatch):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src, a, b = opinion_files(blank, tmp_path)
    assert main(["compare", str(src), str(a)]) == 0
    out = capsys.readouterr().out
    assert "제1장 서론" in out and "~ 수정" in out and "홍이 고쳤다" in out
    assert main(["compare", str(src), str(src)]) == 0
    assert "바뀐 곳이 없어요" in capsys.readouterr().out
    assert main(["compare", str(src), str(a), "--memo", str(tmp_path / "표시.hwpx")]) == 0
    assert "한글이 있어야" in capsys.readouterr().out and not (tmp_path / "표시.hwpx").exists()


def test_cli_merge_table_and_accept(blank, tmp_path, capsys, monkeypatch):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src, a, b = opinion_files(blank, tmp_path)
    out = tmp_path / "모음본.hwpx"
    assert main(["merge", str(src), str(a), str(b), str(out), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [o["id"] for o in data["opinions"]] == ["m1", "m2", "m3"] and not out.exists()
    assert main(["merge", str(src), str(a), str(b), str(out), "--accept", "m2"]) == 0
    text = capsys.readouterr().out
    assert "m2" in text and out.exists()
    from hwpxkit.body import own_text
    assert "홍이 고쳤다" in own_text(tops(Package.open(out))[2])
    assert main(["merge", str(src), str(a), str(b), str(out), "--accept", "m2,m3"]) == 2
    assert "충돌" in capsys.readouterr().err


def test_cli_merge_notes_and_errors(blank, tmp_path, capsys, monkeypatch):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src = base_doc(blank, tmp_path)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps([{"who": "교수님", "where_text": "자료 수집 절차", "text": "근거"}], ensure_ascii=False),
                     encoding="utf-8")
    assert main(["merge", str(src), str(tmp_path / "out.hwpx"), "--notes", str(notes), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["opinions"][0]["kind"] == "note"
    assert main(["merge", str(src), str(src)]) == 2
    assert "덮어쓸 수 없어요" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_merge.py -q -k "add_memos or cli"`
Expected: FAIL — `AttributeError: ... 'add_memos'`, argparse `invalid choice`

- [ ] **Step 3: Write implementation**

`hwpxkit/bridge_hwp.ps1`의 `"pagemap"` 다음에:

```powershell
    "memos" {
      # 메모 달기: Format = JSON 파일 [{anchor, n, text}]. 처음부터 anchor를 n번째까지 찾아 그 자리에 한글 메모.
      $list = Get-Content -Raw -Encoding UTF8 $Format | ConvertFrom-Json
      $placed = 0; $missed = @(); $k = 0
      foreach ($m in @($list)) {
        $k++
        ToTop $hwp
        $set = $hwp.HParameterSet.HFindReplace
        $null = $hwp.HAction.GetDefault("RepeatFind", $set.HSet)
        $set.FindString = [string]$m.anchor; $set.Direction = 0; $set.IgnoreMessage = 1
        foreach ($opt in @("MatchCase", "WholeWordOnly", "FindRegExp", "FindJaso", "AllWordForms", "SeveralWords", "UseWildCards")) {
          try { $null = $set.HSet.SetItem($opt, $(if ($opt -eq "MatchCase") { 1 } else { 0 })) } catch {}
        }
        $found = $true
        for ($j = 0; $j -lt [int]$m.n; $j++) { if (-not $hwp.HAction.Execute("RepeatFind", $set.HSet)) { $found = $false; break } }
        if (-not $found) { $missed += $k; continue }
        $before = [int]$hwp.GetPosBySet().Item("List")
        $opened = [bool]$hwp.HAction.Run("InsertFieldMemo")
        if ($opened -and [int]$hwp.GetPosBySet().Item("List") -ne $before) {
          $ins = $hwp.HParameterSet.HInsertText
          $null = $hwp.HAction.GetDefault("InsertText", $ins.HSet); $ins.Text = [string]$m.text
          $null = $hwp.HAction.Execute("InsertText", $ins.HSet)
          $null = $hwp.HAction.Run("CloseEx")
          $placed++
        } else { $null = $hwp.HAction.Run("Cancel"); $missed += $k }
      }
      ToTop $hwp
      $r = $hwp.SaveAs($Dst, "HWPX", "")
      Emit @{ ok = [bool]$r; pages = $pages; placed = $placed; missed = $missed }
    }
```

`hwpxkit/bridge.py`의 `page_map` 다음에:

```python
def add_memos(src, dst, memos: list[dict]) -> tuple[int, list[dict]]:
    """숨은 한글로 src를 열어 메모들({anchor, n, text})을 달고 dst(.hwpx)로 저장. (단 수, 못 단 메모)."""
    dst = Path(dst)
    if Path(src).resolve() == dst.resolve():
        raise ValueError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    _require()
    with _workdir() as work:
        spec = work / "memos.json"
        spec.write_text(json.dumps(memos, ensure_ascii=False), encoding="utf-8")
        out = work / "out.hwpx"
        result = _run("memos", work, src=_stage(src, work), dst=out, fmt=str(spec))
        if not out.exists():
            raise BridgeError("메모를 단 파일이 만들어지지 않았어요.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dst)
    missed = result.get("missed") or []
    if isinstance(missed, int):
        missed = [missed]
    return int(result.get("placed", 0)), [memos[int(k) - 1] for k in missed]
```

`bridge.py` 첫머리에 `import json`이 없으면 더한다.

`hwpxkit/cli.py`:

```python
def _place_memos(src: Path, out: Path, plan: list[dict], workdir: Path) -> None:
    """메모를 단다. 자리를 못 찾은 메모는 첫 문단에 '[자리 못 찾음]'으로 한 번 더."""
    placed, missed = bridge.add_memos(src, out, plan)
    if missed:
        from .compare import units
        us = units(_open_any(src, workdir))
        first = us[0].raw[:40].strip() if us else ""
        retry = [{"anchor": first, "n": 1, "text": "[자리 못 찾음] " + m["text"]} for m in missed]
        tmp = workdir / "memo2.hwpx"
        n2, missed2 = bridge.add_memos(out, tmp, retry)
        shutil.copyfile(tmp, out)
        placed += n2
        for m in missed2:
            print(f"[주의] 메모를 달지 못했어요: {m['text'][:60]}")
    print(f"한글 메모 {placed}개를 달았어요: {out}")


def _cmd_compare(args, workdir) -> int:
    from .compare import diff, units
    old, new = Path(args.old), Path(args.new)
    changes = diff(units(_open_any(old, workdir)), units(_open_any(new, workdir)))
    if args.json:
        print(json.dumps({"changes": changes}, ensure_ascii=False, default=list))
        return 0
    if not changes:
        print("바뀐 곳이 없어요.")
    where = None
    for c in changes:
        if c["where"] != where:
            where = c["where"]
            print(where)
        if c["kind"] == "add":
            print(f"  + 추가: {c['new']}")
        elif c["kind"] == "del":
            print(f"  - 삭제: {c['old']}")
        else:
            print(f"  ~ 수정: 원래 {c['old']} → 새 {c['new']}")
    if args.memo and changes:
        out = Path(args.memo)
        if out.resolve() in (old.resolve(), new.resolve()):
            raise PackageError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
        if not bridge.available():
            print("한글이 있어야 메모를 달 수 있어요. 바뀐 곳 목록만 보여 드렸어요.")
            return 0
        from .merge import anchor_for
        us = units(_open_any(new, workdir))
        plan = []
        for c in changes:
            if c["kind"] == "del":
                spot = None
                text = f"[삭제됨] {c['old']}"
            else:
                spot = anchor_for(us, c["new_key"])
                text = "[추가됨]" if c["kind"] == "add" else f"[바뀜] 원래: {c['old']}"
            if spot is None:
                spot = (us[0].raw[:40].strip(), 1) if us else ("", 1)
            plan.append({"anchor": spot[0], "n": spot[1], "text": text})
        _place_memos(new, out, plan, workdir)
    return 0


def _cmd_merge(args, workdir) -> int:
    from . import merge as merge_mod
    paths = [Path(p) for p in args.files]
    if len(paths) < 2:
        raise PackageError("원본과 결과 파일을 주세요: merge <원본> <의견…> <모음본.hwpx>")
    base, others, out = paths[0], paths[1:-1], paths[-1]
    if out.resolve() in [p.resolve() for p in paths[:-1]]:
        raise PackageError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8")) if args.notes else []
    if not others and not notes:
        raise PackageError("의견 파일을 하나 이상 주세요 (또는 --notes).")
    taken: set[str] = set()
    named = [(merge_mod.opinion_name(base, p, taken), _open_any(p, workdir)) for p in others]
    base_pkg = _open_any(base, workdir)
    ops = merge_mod.opinions(base_pkg, named, notes)
    applied, skipped = [], []
    if args.accept:
        ids = [x.strip() for x in args.accept.split(",") if x.strip()]
        applied, skipped = merge_mod.accept(base_pkg, ops, ids)
    rest = [o for o in ops if o["id"] not in applied]
    if args.json:
        print(json.dumps({"opinions": ops, "applied": applied, "skipped": skipped}, ensure_ascii=False, default=list))
    else:
        for o in ops:
            mark = " (반영함)" if o["id"] in applied else ""
            print(f"{o['id']} {merge_mod.memo_text(o)}  — {o['where']}{mark}")
        for s in skipped:
            print(f"[주의] {s}")
    if not args.accept and not bridge.available():
        if not args.json:
            print("한글이 있어야 의견 모음본(메모)을 만들 수 있어요. 의견 목록만 보여 드렸어요.")
        return 0
    staged = workdir / "merged.hwpx"
    base_pkg.save(staged)
    if bridge.available() and rest:
        _place_memos(staged, out, merge_mod.memo_plan(base_pkg, rest), workdir)
    else:
        shutil.copyfile(staged, out)
        if rest and not args.json:
            print("[주의] 한글이 없어 남은 의견을 메모로 달지 못했어요.")
        if not args.json:
            print(f"저장했어요: {out}")
    return 0
```

`merge_mod.accept`가 내는 `MergeError`는 ValueError라 `main()`이 종료 코드 2로 처리한다. `_parser()`의 `guide` 다음에:

```python
    s = sub.add_parser("compare", help="두 판의 바뀐 곳(문단·표 칸) 보기, --memo로 새 판에 메모")
    s.add_argument("old")
    s.add_argument("new")
    s.add_argument("--memo", help="바뀐 곳에 메모를 단 새 판 사본 (한글 필요)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_compare)
    s = sub.add_parser("merge", help="여러 사람 의견(메모·수정)을 원본 사본 하나에 메모로 모으기")
    s.add_argument("files", nargs="+", help="<원본> <의견 파일…> <모음본.hwpx>")
    s.add_argument("--accept", help="본문에 반영할 의견 번호 (예: m2,m5)")
    s.add_argument("--notes", help="따로 받은 의견 JSON [{who, where_text, text}]")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_merge)
```

`--notes`만 쓸 때(`merge 원본 결과 --notes …`)는 `paths`가 2개라 의견 파일이 없다. 위 코드가 그 경우를 받는다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_merge.py -q` 그리고 `python -m pytest -q -m "not hangul"`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit tests/test_merge.py
git commit -m "feat: 한글 메모 달기(memos), compare·merge 명령"
```

---

### Task 5: 한글 시험, 안내 문서, 0.7.0

**Files:**
- Create: `skills/hwp-helper/reference/merge.md`
- Modify: `skills/hwp-helper/SKILL.md`, `README.md`, `.claude-plugin/plugin.json`, `tests/test_plugin_files.py`
- Test: `tests/test_merge.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.hangul
def test_add_memos_with_hangul(blank, tmp_path):
    from hwpxkit import bridge
    from hwpxkit.compare import memos
    src = base_doc(blank, tmp_path)
    plan = [{"anchor": "해당 없음", "n": 2, "text": "[홍길동] 둘째 자리"},
            {"anchor": "120명", "n": 1, "text": "[김철수] 칸 메모"},
            {"anchor": "없는 글", "n": 1, "text": "x"}]
    placed, missed = bridge.add_memos(src, tmp_path / "메모본.hwpx", plan)
    assert placed == 2 and missed == [plan[2]]
    ms = memos(Package.open(tmp_path / "메모본.hwpx"))
    texts = {m["text"]: m for m in ms}
    assert set(texts) == {"[홍길동] 둘째 자리", "[김철수] 칸 메모"}
    assert texts["[홍길동] 둘째 자리"]["where"] == "제2장 방법"


def test_skill_documents_merge():
    from pathlib import Path
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "merge.md").read_text(encoding="utf-8")
    for word in ('hwpx.py" compare', 'hwpx.py" merge', "--accept", "--notes", "충돌"):
        assert word in text, word
    assert "reference/merge.md" in (root / "SKILL.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_merge.py -q -k "skill_documents or with_hangul"`
Expected: `test_skill_documents_merge` FAIL. 한글 시험은 Task 4로 PASS일 수 있다(회귀 고정용). FAIL이면 systematic-debugging으로 원인을 찾는다. 예: 한글 찾기의 순서·옵션, 메모 칸 열림 확인, 메모 위치의 where 계산. 고친 뒤 Ruling으로 기록한다.

- [ ] **Step 3: Write docs**

`skills/hwp-helper/reference/merge.md`:

```markdown
# 이전 판 비교와 의견 합치기

## 이전 판과 비교 ("지난번이랑 뭐가 바뀌었어?")

- `python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" compare <옛판> <새판>` — 장별로 추가·삭제·수정.
- 한글에서 보며 확인하고 싶어 하면 `--memo <표시본.hwpx>`(한글 필요): 새 판 사본에 "[바뀜] 원래: …" 메모.
- 글만 비교한다(서식·그림 바뀜은 나오지 않는다).

## 여러 사람 의견 합치기 ("교수님이랑 선배 의견 합쳐줘")

1. 의견 파일 이름에서 사람 이름을 딴다(`보고서_홍길동.hwpx` → 홍길동). 이름이 없으면 사용자에게 누구 것인지 묻고 파일 이름을 바꿔 달라고 하거나 그대로 쓴다.
2. 카톡·메일·미팅 메모처럼 따로 받은 의견은 의견마다 원본의 해당 문단을 찾아 `notes.json`을 만든다:
   `[{"who": "교수님", "where_text": "그 문단의 고유한 글 일부", "text": "의견"}]`. 자리가 확실하지 않으면 묻는다.
3. `python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" merge <원본> <의견…> <모음본.hwpx> [--notes notes.json]`
   - 한글이 있으면 모든 의견이 이름 붙은 한글 메모로 달린 모음본이 만들어진다. 없으면 목록만.
   - 출력의 의견 표(m1, m2 …)를 사용자에게 보여 준다. **[충돌]**(같은 곳을 다르게 고침)을 먼저 보여 준다.
4. "어느 수정을 반영할까요?"라고 묻고, 고른 번호로 `merge … --accept m2,m5`. 반영하지 않은 의견은 메모로 남는다.
   - 충돌하는 둘을 함께 고르면 멈춘다. 하나만 고르게 한다.
   - "원본 그 부분이 바뀌어 반영하지 않았어요"가 나오면 사용자에게 알리고 직접 확인한다.
5. 반영 뒤 `compare <원본> <결과>`로 바뀐 곳을 보여 준다.

- 원본과 의견 파일은 읽기만 한다. 결과는 늘 새 파일이다.
- 의견을 반영하면서 원문에 없는 수치·사실을 지어내지 않는다.
```

`SKILL.md`의 fit 단락 다음에:

```markdown
"바뀐 곳 보여줘", "여러 사람 의견 합쳐줘"라고 하면 `compare`·`merge`를 쓴다. 의견은 이름 붙은 한글 메모로 모으고, 반영은 사용자가 고른 것만 한다. 절차는 `reference/merge.md`.
```

`tests/test_plugin_files.py` 허용 옵션에 `"--memo"`는 이미 있고 `"--accept", "--notes"`를 더한다. `README.md` 명령 표의 `guide` 줄 다음에:

```markdown
| `compare 옛판 새판` | 두 판의 바뀐 곳(문단·표 칸) 보기, `--memo`로 새 판에 메모 | 메모만 |
| `merge 원본 의견… 모음본` | 여러 사람의 메모·직접 수정·따로 받은 의견을 이름 붙은 한글 메모로 모으고, `--accept`로 고른 것만 반영 | 메모만 |
```

`plugin.json` 버전 `"0.7.0"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -m "not hangul"` 그리고 `python -m pytest -q tests/test_merge.py -m hangul`
Expected: 모두 PASS

- [ ] **Step 5: 실제 흐름 수동 확인**

1. 시험용 원본(base_doc)과 의견 파일 두 개를 만든다.
   - 홍: 메모 하나 + 한 문단 수정.
   - 김: 같은 문단을 다르게 수정 → 충돌.
2. `merge`로 모음본을 만들고 `preview`로 쪽 그림을 본다. 메모가 오른쪽 여백에 보이는지 확인한다.
3. `--accept`로 하나를 반영하고 `compare`로 확인한다.
4. 결과를 ledger에 한 줄로 남긴다.

- [ ] **Step 6: Commit**

```bash
git add skills tests .claude-plugin README.md
git commit -m "feat: 비교·의견 합치기 안내, 한글 시험, 0.7.0"
```

---

## Self-Review 결과

- 스펙 대응:
  - 3장 → Task 1
  - 4장 → Task 1(memos)·2(원본 메모 제외)
  - 5장 → Task 2(anchor·n, 대체 자리)·4(add_memos, 재시도)
  - 6장 → Task 2·3·4
  - 7장 → Task 5 문서
  - 8장 오류 → Task 3(없는 번호·충돌·바뀐 원본)·4(덮어쓰기·의견 없음·한글 없음)
  - 10장 시험 → 각 Task
- 이름 일관성:
  - `opinions(...)` 항목 키, `memo_plan` 결과 `{id, anchor, n, text}`
  - `add_memos(src, dst, memos) -> (placed, missed)`
  - `accept(base_pkg, ops, ids) -> (applied, skipped)`
  - Task 2~4에서 같다.
- 계획 안 코드 보완 지시(set_text 단순화, memo_plan의 add 맨 앞, add의 지워진 앞 단위): 실행 때 지시대로 쓰고, 계획과 달라진 점은 Ruling 없이 계획대로다.
