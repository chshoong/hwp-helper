# 차례·표목차·그림목차와 상호 참조 (toc) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한글 고유 차례 칸(장·절 차례, 표 목차, 그림 목차)과 본문 표·그림 번호의 한글 상호 참조를 엔진이 직접 써 넣고, 한글이 있으면 "차례 모두 새로 고침"으로 쪽 번호까지 맞춘다.

**Architecture:** 새 모듈 `hwpxkit/toc.py`가 차례 칸(TABLEOFCONTENTS 필드), 제목 차례 표시(titleMark), 차례 자리 찾기, 상호 참조(CROSSREF 필드)를 다룬다. `bridge` 동작 `toc`이 숨은 한글로 `UpdateAllContents`를 부른다. `cli`의 저장 단계(`_save_checked`)가 차례가 있으면 새로 고치고, `render`·`fill`은 저장 전에 상호 참조를 연결한다. 마크다운 `[차례]` 같은 줄은 렌더러가 자리표 문단을 남기고 `render_into` 끝에서 차례 칸으로 바꾼다.

**Tech Stack:** Python 3.11+, lxml, 기존 hwpxkit, 한글 COM(PowerShell `bridge_hwp.ps1`).

**Spec:** docs/superpowers/specs/2026-10-08-toc-crossref-design.md

## Global Constraints

- 원본 파일은 덮어쓰지 않는다. 결과는 다른 이름으로 저장한다.
- 새 의존성 없음.
- 사용자에게 보이는 글은 한국어 존댓말, 쉬운 말.
- 차례 종류 이름은 정확히 "제목", "표", "그림". ContentsMake 값: 제목 65, 표 2, 그림 4.
- 상호 참조는 문서 전체 번호 문서에서만. 장별 번호(캡션 "n-m") 문서는 건드리지 않는다.
- `HAction.Execute("MakeContents")`는 쓰지 않는다(한글이 죽음). 새로 고침은 `HAction.Run("UpdateAllContents")`.
- 사용자 실제 문서(private/)는 시험·공개 파일에 쓰지 않는다.

## Review Focus

1. 이미 차례가 있는 문서에 `toc`를 다시 실행 — 같은 종류 차례 칸이 하나만 남아야 한다 (Task 2 `test_insert_twice_keeps_one_block`).
2. 본문 "[표 3]"이 실제 표 수보다 큰 번호이거나 "표 2-1" 꼴 — 바꾸지 않아야 한다 (Task 3 `test_link_skips_missing_and_chapter_like`).
3. 표 칸 안·캡션 안·차례 칸 안의 "표 1" 글 — 상호 참조로 바꾸지 않아야 한다 (Task 3 `test_link_skips_cells_captions_and_toc`).
4. 마크다운 첫 블록이 `[차례]`(mode new에서 첫 문단에 합쳐지는 자리) — 차례가 사라지지 않고 문서 앞에 들어가야 한다 (Task 5 `test_toc_block_first_in_document`).
5. 한글 없이 저장 — 결과는 저장되고 쪽 번호가 빈 이유와 새로 고치는 방법을 알려야 한다 (Task 4 `test_save_without_hangul_explains_toc`).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `hwpxkit/toc.py` (새로) | 필드 만들기, 차례 칸 만들기·찾기·바꾸기, 제목 차례 표시, 차례 자리, 상호 참조 |
| `hwpxkit/bridge_hwp.ps1`, `hwpxkit/bridge.py` | 동작 `toc` / `refresh_toc(src, dst)` |
| `hwpxkit/cli.py` | `toc` 명령, `_save_checked`의 차례 새로 고침, `render`·`fill`의 상호 참조 연결 |
| `hwpxkit/review.py` | `toc-stale` 확인 |
| `hwpxkit/mdparse.py`, `hwpxkit/render.py` | `Toc` 블록, 자리표, 제목 문단 목록 |
| `skills/hwp-helper/reference/toc.md`, `SKILL.md`, `reference/markdown.md`, `README.md`, `.claude-plugin/plugin.json` | 안내, 0.4.0 |
| `tests/test_toc.py` (새로) | 모든 시험 |

---

### Task 1: 차례 칸 만들기와 제목 차례 표시 (`at` 자리 넣기)

**Files:**
- Create: `hwpxkit/toc.py`
- Test: `tests/test_toc.py`

**Interfaces:**
- Produces:
  - `ORDER = ("제목", "표", "그림")`, `MAKE = {"제목": 65, "표": 2, "그림": 4}`
  - `toc_blocks(tops: list) -> list[tuple[int, int, int]]` — (시작 문단 번호, 끝 문단 번호(포함), ContentsMake)
  - `has_toc(pkg) -> bool`
  - `mark_titles(pkg, level: int = 2, paragraphs: list | None = None) -> int`
  - `insert_toc(pkg, kinds, *, level: int = 2, at: int | None = None, titles: list | None = None) -> list[str]` — 경고 목록. 이 Task에서는 `at`이 주어진 경우만 구현(없으면 Task 2).
  - 내부: `_Ids(pkg).take() -> str`, `_field_begin(ids, ftype, params, editable="0")`, `_field_end(fb)`, `_ctrl(el)`

- [ ] **Step 1: Write the failing test**

```python
"""차례·표목차·그림목차(한글 차례 칸)와 상호 참조."""
import re

import pytest

from helpers import LONG, SECTION, append_to_body, para, table, tiny_png
from hwpxkit.body import all_text, own_text
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import render_into
from hwpxkit.samples import infer

DOC_MD = """# 제1장 서론

## 1.1 연구 배경

{long}

표: 첫째 표
| 가 | 나 |
|---|---|
| 1 | 2 |

![첫째 그림](g.png)

# 제2장 방법

{long} [표 2]를 본다.

표: 둘째 표
| 다 | 라 |
|---|---|
| 3 | 4 |
"""


def make_doc(blank, tmp_path, md=None, name="doc.hwpx"):
    (tmp_path / "g.png").write_bytes(tiny_png())
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), (md or DOC_MD).format(long=LONG), base_dir=tmp_path)
    return pkg


def tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def command(fb):
    return next(e.text for e in fb.iter(q("hp:stringParam")) if e.get("name") == "Command")


def test_insert_table_toc_at_position(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    warnings = toc.insert_toc(pkg, ["표"], at=1)
    assert warnings == []
    ps = tops(pkg)
    fb = next(ps[1].iter(q("hp:fieldBegin")))
    assert fb.get("type") == "TABLEOFCONTENTS" and "ContentsMake:uint:2 " in command(fb)
    assert "ContentsLevel:int:2" in command(fb) and "ContentsLeader:int:3" in command(fb)
    assert [own_text(p) for p in ps[2:4]] == ["[표 1] 첫째 표", "[표 2] 둘째 표"]
    end = next(ps[4].iter(q("hp:fieldEnd")))
    assert end.get("beginIDRef") == fb.get("id") and end.get("fieldid") == fb.get("fieldid")
    assert toc.toc_blocks(ps) == [(1, 4, 2)] and toc.has_toc(pkg)


def test_title_toc_marks_headings(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["제목"], at=1)
    marked = [own_text(p) for p in tops(pkg) if next(p.iter(q("hp:titleMark")), None) is not None]
    assert marked == ["제1장 서론", "1.1 연구 배경", "제2장 방법"]
    tm = next(tops(pkg)[0].getparent().iter(q("hp:titleMark")))
    assert tm.get("ignore") == "1" and tm.getparent().tag == q("hp:t")
    fb = next(tops(pkg)[1].iter(q("hp:fieldBegin")))
    assert "ContentsMake:uint:65 " in command(fb)
    assert toc.mark_titles(pkg) == 0  # 다시 해도 하나


def test_title_level_limit(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    assert toc.mark_titles(pkg, level=1) == 2


def test_all_kinds_in_order_and_warnings(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md="# 제1장 서론\n\n{long}\n")
    warnings = toc.insert_toc(pkg, ["그림", "표", "제목"], at=1)
    assert len(warnings) == 2 and all("없어" in w for w in warnings)
    makes = [m for _, _, m in toc.toc_blocks(tops(pkg))]
    assert makes == [65]


def test_field_ids_unique(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["제목", "표", "그림"], at=1)
    ids = [fb.get("id") for fb in pkg.xml(SECTION).iter(q("hp:fieldBegin"))]
    assert len(ids) == 3 and len(set(ids)) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_toc.py -q`
Expected: FAIL — `ImportError: cannot import name 'toc' from 'hwpxkit'`

- [ ] **Step 3: Write implementation**

```python
"""차례·표 목차·그림 목차(한글 고유 차례 칸)와 본문 표·그림 참조(한글 상호 참조).

차례 칸은 TABLEOFCONTENTS 필드로 감싼 문단들이다. 엔진은 쪽 번호 없는 임시 목록을 넣고,
한글이 '차례 모두 새로 고침'(UpdateAllContents)으로 항목과 쪽 번호를 다시 만든다 (설계 2장).
"""
from __future__ import annotations

import re

from lxml import etree

from .body import all_text, is_blank, own_text
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
    return [all_text(o.find(q("hp:caption"))).strip() for o in root.iter(q(_TAG[kind]))
            if o.find(q("hp:caption")) is not None]


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_toc.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/toc.py tests/test_toc.py
git commit -m "feat: 한글 차례 칸 만들기와 제목 차례 표시"
```

---

### Task 2: 차례 자리 찾기와 다시 넣기

**Files:**
- Modify: `hwpxkit/toc.py`
- Test: `tests/test_toc.py`

**Interfaces:**
- Consumes: Task 1 전부
- Produces:
  - `find_slot(pkg, kind) -> tuple[int, str, list[int]]` — (넣을 자리: 이 최상위 문단 번호 앞, 근거, 지울 문단 번호 목록). 근거: "기존 차례 칸" / "양식 표 목차 자리"(종류별 이름 `_LABEL[kind]`) / "양식 목차 자리" / "표지 다음" / "문서 처음"
  - `insert_toc(..., at=None)` 동작 완성

- [ ] **Step 1: Write the failing tests**

```python
def test_slot_existing_block_and_reinsert(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["표"], at=1)
    assert toc.find_slot(pkg, "표") == (1, "기존 차례 칸", [1, 2, 3, 4])


def test_insert_twice_keeps_one_block(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["제목", "표"])
    toc.insert_toc(pkg, ["제목", "표"])
    makes = [m for _, _, m in toc.toc_blocks(tops(pkg))]
    assert makes == [65, 2]


def test_slot_template_heading_drops_blank_and_empty_table(blank, tmp_path):
    from hwpxkit import toc
    pkg = Package.open(blank)
    append_to_body(pkg, para("표 지"))
    append_to_body(pkg, para("목 차"))
    append_to_body(pkg, para(""))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "…"}))
    append_to_body(pkg, para("제1장 서론"))
    append_to_body(pkg, para(LONG))
    assert toc.find_slot(pkg, "제목") == (3, "양식 목차 자리", [3, 4])
    toc.insert_toc(pkg, ["제목"])
    texts = [own_text(p) for p in tops(pkg)]
    assert texts[2] == "목 차" and next(tops(pkg)[3].iter(q("hp:fieldBegin"))).get("type") == "TABLEOFCONTENTS"
    assert sum(1 for _ in pkg.xml(SECTION).iter(q("hp:tbl"))) == 0


def test_slot_kind_specific_heading(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    root = pkg.edit(SECTION)
    root.insert(2, para("표 목차"))
    root.insert(2, para("목차"))
    at, reason, drop = toc.find_slot(pkg, "표")
    assert reason == "양식 표 목차 자리" and own_text(tops(pkg)[at - 1]) == "표 목차"
    assert toc.find_slot(pkg, "그림")[1] == "양식 목차 자리"


def test_slot_after_cover_page(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    ps = tops(pkg)
    k = next(i for i, p in enumerate(ps) if own_text(p).startswith("제1장"))
    ps[k].set("pageBreak", "1")
    assert toc.find_slot(pkg, "표") == (k, "표지 다음", [])
    toc.insert_toc(pkg, ["제목", "표"])
    ps = tops(pkg)
    starts = [s for s, _, _ in toc.toc_blocks(ps)]
    assert ps[starts[0]].get("pageBreak") == "1" and ps[starts[1]].get("pageBreak") == "0"
    after = toc.toc_blocks(ps)[-1][1] + 1
    assert own_text(ps[after]).endswith("제1장 서론") and ps[after].get("pageBreak") == "1"


def test_slot_document_start(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    assert toc.find_slot(pkg, "표") == (1, "문서 처음", [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_toc.py -q -k "slot or twice"`
Expected: FAIL — `AttributeError: module 'hwpxkit.toc' has no attribute 'find_slot'`

- [ ] **Step 3: Write implementation** (toc.py에 추가·교체)

```python
_LABEL = {"제목": "차례", "표": "표 목차", "그림": "그림 목차"}
_SLOT = {"목차": "*", "차례": "*", "표목차": "표", "표차례": "표", "그림목차": "그림", "그림차례": "그림"}
_EMPTY_CELL = {"", "…", "...", "·", "‥"}


def _droppable(p) -> bool:
    """양식 목차 자리 밑의 빈 문단, 빈 목차 표(모든 칸이 비었거나 '…'만)."""
    tbl = next(p.iter(q("hp:tbl")), None)
    if tbl is None:
        return is_blank(p)
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
            drop, j = [], hit + 1
            while j < len(tops) and _droppable(tops[j]):
                drop.append(j)
                j += 1
            return hit + 1, reason, drop
    k = next((i for i, p in enumerate(tops) if i > 0 and p.get("pageBreak") == "1"), None)
    if k is not None:
        return k, "표지 다음", []
    return min(1, len(tops)), "문서 처음", []
```

`_SLOT`의 "*" 항목("목차", "차례")은 제목 차례 자리이기도 하다. 그래서 `kind == "제목"`일 때 종류별 검색(`want == "제목"`)은 건너뛰고 "*"로 찾는다. 위 조건식이 그 일을 한다.

`insert_toc`의 반복문을 아래로 바꾼다. `at`이 없을 때 쓰는 코드다.

```python
    ids = _Ids(pkg)
    root, tops = _tops(pkg)
    ref = tops[at] if at is not None and at < len(tops) else None
    page_break = at is not None and ref is not None and ref.get("pageBreak") == "1"
    anchor = ref if at is not None else None  # 자기 자리가 없는 다음 칸은 앞 칸 바로 뒤에
    for kind in [k for k in ORDER if k in set(kinds)]:
        if kind == "제목":
            mark_titles(pkg, level, titles)
        entries = _entries(pkg, kind)
        if not entries:
            warnings.append(_EMPTY[kind])
            continue
        els = _block(pkg, kind, level, entries, ids)
        root, tops = _tops(pkg)
        if at is not None:
            target, drop = anchor, []
        else:
            idx, reason, drop_idx = find_slot(pkg, kind)
            own = reason == "기존 차례 칸" or reason == f"양식 {_LABEL[kind]} 자리"
            if not own and anchor is not None:
                target, drop = anchor, []
            else:
                drop = [tops[i] for i in drop_idx]
                nxt = idx + len(drop_idx)
                target = tops[nxt] if nxt < len(tops) else None
                if reason == "기존 차례 칸":
                    els[0].set("pageBreak", tops[idx].get("pageBreak", "0"))
                elif reason == "표지 다음":
                    page_break = True
        for p in drop:
            root.remove(p)
        if page_break:
            els[0].set("pageBreak", "1")
            page_break = False
        _insert_before(root, target, els)
        anchor = target
    return warnings
```

"기존 차례 칸"에서 `nxt`는 끝 문단 다음이다. `drop_idx`가 시작부터 끝까지 이어진 번호라서 `idx + len(drop_idx)`가 맞다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_toc.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/toc.py tests/test_toc.py
git commit -m "feat: 차례 자리 찾기(기존 칸·양식 목차·표지 다음)와 다시 넣기"
```

---

### Task 3: 상호 참조 연결

**Files:**
- Modify: `hwpxkit/toc.py`
- Test: `tests/test_toc.py`

**Interfaces:**
- Produces:
  - `uses_chapter_numbers(pkg) -> bool`
  - `link_refs(pkg) -> tuple[int, str | None]` — (연결한 수, 안 한 이유: None 또는 "chapter")

- [ ] **Step 1: Write the failing tests**

```python
def crossrefs(pkg):
    return [fb for fb in pkg.xml(SECTION).iter(q("hp:fieldBegin")) if fb.get("type") == "CROSSREF"]


def params(fb):
    return {e.get("name"): e.text for e in fb.find(q("hp:parameters"))}


def test_link_number_becomes_crossref(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    n, why = toc.link_refs(pkg)
    assert (n, why) == (1, None)
    fb = crossrefs(pkg)[0]
    tbl2 = [t for t in pkg.xml(SECTION).iter(q("hp:tbl")) if t.find(q("hp:caption")) is not None][1]
    pr = params(fb)
    assert pr["Command"] == f"?#{tbl2.get('id')};0;1;0;0;" and pr["RefType"] == "TARGET_TABLE"
    assert pr["RefContentType"] == "OBJECT_TYPE_NUMBER" and pr["RefPath"] == f"?#{tbl2.get('id')};"
    p = next(p for p in tops(pkg) if "를 본다" in own_text(p))
    assert own_text(p).endswith("[표 2]를 본다.")
    run = fb.getparent().getparent()
    i = [el.tag for el in run].index(q("hp:ctrl"))
    assert run[i + 1].text == "2" and run[i + 2].find(q("hp:fieldEnd")) is not None
    assert toc.link_refs(pkg) == (0, None)  # 다시 해도 같음


def test_link_picture(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md="# 제1장\n\n![그림](g.png)\n\n그림 1에서 보듯이 결과가 좋다. " + LONG + "\n")
    assert toc.link_refs(pkg) == (1, None)
    pr = params(crossrefs(pkg)[0])
    assert pr["RefType"] == "TARGET_PICTURE" and ";1;1;0;0;" in pr["Command"]


def test_link_skips_missing_and_chapter_like(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md=DOC_MD.replace("[표 2]를 본다.", "[표 5]와 표 2-1, 도표 1을 본다."))
    assert toc.link_refs(pkg) == (0, None)


def test_link_skips_cells_captions_and_toc(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md=DOC_MD.replace("| 1 | 2 |", "| 표 1 | 2 |").replace("[표 2]를 본다.", "본다."))
    toc.insert_toc(pkg, ["표"], at=1)
    assert toc.link_refs(pkg) == (0, None)


def test_chapter_numbered_document_untouched(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path)
    cap = next(pkg.xml(SECTION).iter(q("hp:caption")))
    t = next(cap.iter(q("hp:t")))
    t.text = "[표 1-1] 첫째 표"
    assert toc.uses_chapter_numbers(pkg) is True
    assert toc.link_refs(pkg) == (0, "chapter")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_toc.py -q -k "link or chapter"`
Expected: FAIL — `AttributeError: module 'hwpxkit.toc' has no attribute 'link_refs'`

- [ ] **Step 3: Write implementation** (toc.py에 추가)

```python
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
        if not 1 <= num <= len(objs[kind]):
            continue
        fb = _crossref(ids, kind, objs[kind][num - 1].get("id"))
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
    objs = {k: [o for o in root.iter(q(tag)) if o.find(q("hp:caption")) is not None] for k, tag in _TAG.items()}
    skip, ids, n = _in_toc(tops), _Ids(pkg), 0
    for i, p in enumerate(tops):
        if i in skip:
            continue
        for run in p.findall(q("hp:run")):  # 바로 아래 글만: 표 칸·캡션 안 글은 제외
            for t in list(run.findall(q("hp:t"))):
                if len(t) == 0 and t.text:
                    n += _link_t(run, t, objs, ids)
    return n, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_toc.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/toc.py tests/test_toc.py
git commit -m "feat: 본문 표·그림 번호를 한글 상호 참조로 연결"
```

---

### Task 4: 한글 새로 고침, `toc` 명령, 저장 단계 연결, 검토

**Files:**
- Modify: `hwpxkit/bridge_hwp.ps1`, `hwpxkit/bridge.py`, `hwpxkit/cli.py`, `hwpxkit/review.py`
- Test: `tests/test_toc.py`

**Interfaces:**
- Consumes: `insert_toc`, `link_refs`, `has_toc`, `toc_blocks`, `ORDER`
- Produces:
  - `bridge.refresh_toc(src, dst) -> Path`
  - CLI `toc <file> <out> [--kinds 제목,표,그림] [--level 2] [--refs] [--preview DIR]`
  - `_save_checked`: 차례가 있으면 한글로 새로 고침, 한글이 없으면 `[주의] 한글이 없어 차례 쪽 번호를 비워 두었어요. 한글에서 도구 → 차례 새로 고침을 눌러 주세요.`
  - `render`·`fill`: 저장 전 `link_refs`, 연결했으면 `[상호 참조] 본문의 표·그림 번호 N곳을 한글 상호 참조로 연결했어요.`
  - review Finding code `toc-stale`

- [ ] **Step 1: Write the failing tests**

```python
def test_cli_toc_without_hangul(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src = make_doc(blank, tmp_path).save(tmp_path / "보고서.hwpx")
    out = tmp_path / "차례.hwpx"
    assert main(["toc", str(src), str(out), "--kinds", "제목,표", "--refs"]) == 0
    text = capsys.readouterr().out
    assert "차례 새로 고침" in text and "상호 참조" in text
    from hwpxkit import toc
    pkg = Package.open(out)
    assert [m for _, _, m in toc.toc_blocks(tops(pkg))] == [65, 2]


def test_save_without_hangul_explains_toc(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    md = tmp_path / "새.md"
    (tmp_path / "g.png").write_bytes(tiny_png())
    md.write_text("[차례]\n\n" + DOC_MD.format(long=LONG), encoding="utf-8")
    out = tmp_path / "결과.hwpx"
    assert main(["render", str(blank), str(md), str(out)]) == 0
    text = capsys.readouterr().out
    assert out.exists() and "차례 새로 고침" in text


def test_render_links_refs(blank, tmp_path, monkeypatch, capsys):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    md = tmp_path / "새.md"
    (tmp_path / "g.png").write_bytes(tiny_png())
    md.write_text(DOC_MD.format(long=LONG), encoding="utf-8")
    out = tmp_path / "결과.hwpx"
    assert main(["render", str(blank), str(md), str(out)]) == 0
    assert "상호 참조로 연결" in capsys.readouterr().out
    assert crossrefs(Package.open(out))


def test_cli_toc_bad_kind(blank, tmp_path, capsys):
    from hwpxkit.cli import main
    src = make_doc(blank, tmp_path).save(tmp_path / "보고서.hwpx")
    assert main(["toc", str(src), str(tmp_path / "o.hwpx"), "--kinds", "수식"]) == 2
    assert "제목·표·그림" in capsys.readouterr().err


def test_refresh_toc_uses_bridge_action(tmp_path, monkeypatch):
    from hwpxkit import bridge
    seen = {}

    def fake_run(action, work, *, src=None, dst=None, fmt=None, timeout=0):
        seen["action"] = action
        Path(dst).write_bytes(b"x")
        return {"ok": True}
    monkeypatch.setattr(bridge, "_require", lambda: None)
    monkeypatch.setattr(bridge, "_run", fake_run)
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"y")
    out = bridge.refresh_toc(src, tmp_path / "b.hwpx")
    assert seen["action"] == "toc" and out.read_bytes() == b"x"
    with pytest.raises(ValueError):
        bridge.refresh_toc(src, src)


def test_review_flags_stale_toc(blank, tmp_path):
    from hwpxkit import toc
    from hwpxkit.review import review
    pkg = make_doc(blank, tmp_path)
    toc.insert_toc(pkg, ["표"], at=1)
    assert [f.code for f in review(pkg)].count("toc-stale") == 1
```

`from pathlib import Path`를 파일 첫머리 import에 더한다.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_toc.py -q -k "cli or save_without or render_links or refresh_toc or stale"`
Expected: FAIL — argparse `invalid choice: 'toc'`, `AttributeError: ... refresh_toc`, 등

- [ ] **Step 3: Write implementation**

`hwpxkit/bridge_hwp.ps1`의 `switch ($Action)` 안 `"refresh"` 다음에:

```powershell
    "toc" {
      # 문서 안 차례 칸(TABLEOFCONTENTS)을 한글이 다시 만들고 쪽 번호를 채운다 (MakeContents는 한글이 죽어 쓰지 않음)
      $u = $hwp.HAction.Run("UpdateAllContents")
      ToTop $hwp
      $r = $hwp.SaveAs($Dst, "HWPX", "")
      Emit @{ ok = [bool]$r; pages = $pages; updated = [bool]$u }
    }
```

`hwpxkit/bridge.py`의 `refresh_equations` 다음에:

```python
def refresh_toc(src, dst) -> Path:
    """한글로 열어 차례 칸을 모두 새로 고치고(쪽 번호 채움) dst(.hwpx)로 저장한다."""
    dst = Path(dst)
    if dst.suffix.lower() != ".hwpx":
        raise ValueError(f"차례를 새로 고친 결과는 .hwpx로 저장해요: {dst.name}")
    if Path(src).resolve() == dst.resolve():
        raise ValueError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    _require()
    with _workdir() as work:
        out = work / "out.hwpx"
        _run("toc", work, src=_stage(src, work), dst=out)
        if not out.exists():
            raise BridgeError("차례를 새로 고친 파일이 만들어지지 않았어요.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, dst)
    return dst
```

`hwpxkit/cli.py`:
- import에 `from . import toc as toc_mod`를 더한다.
- `_save_checked`에서 수식 처리(`elif total: ...` 블록) 바로 뒤, `if hwpx != out:` 앞에:

```python
    if toc_mod.has_toc(pkg):
        if bridge.available():
            _refresh_toc_in_place(hwpx, workdir)
        else:
            print("[주의] 한글이 없어 차례 쪽 번호를 비워 두었어요. 한글에서 도구 → 차례 새로 고침을 눌러 주세요.")
```

- `_refresh_in_place` 다음에:

```python
def _refresh_toc_in_place(hwpx: Path, workdir: Path) -> None:
    """차례 칸을 한글로 새로 고친다. 실패해도 임시 목록 파일은 그대로 두고 안내만 한다."""
    fixed = workdir / "toc_fixed.hwpx"
    try:
        bridge.refresh_toc(hwpx, fixed)
    except bridge.BridgeError as e:
        print(f"[주의] 한글로 차례 쪽 번호를 채우지 못했어요 ({e}). 한글에서 도구 → 차례 새로 고침을 눌러 주세요.")
        return
    shutil.copyfile(fixed, hwpx)
    print("차례 쪽 번호를 한글로 채웠어요.")


def _link(pkg: Package) -> None:
    n, _ = toc_mod.link_refs(pkg)
    if n:
        print(f"[상호 참조] 본문의 표·그림 번호 {n}곳을 한글 상호 참조로 연결했어요.")


def _cmd_toc(args, workdir) -> int:
    src, out = _resolve_template(args.file), Path(args.out)
    if out.resolve() == src.resolve():
        raise PackageError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    pkg = _open_any(src, workdir)
    for w in toc_mod.insert_toc(pkg, kinds, level=args.level):
        print(f"[주의] {w}")
    if args.refs:
        n, why = toc_mod.link_refs(pkg)
        if why == "chapter":
            print("[상호 참조] 장별 번호([표 2-1])는 한글 상호 참조로 만들 수 없어 글로 두었어요. 번호가 바뀌면 renumber가 본문까지 함께 고쳐요.")
        else:
            print(f"[상호 참조] 본문의 표·그림 번호 {n}곳을 한글 상호 참조로 연결했어요.")
    return _save_checked(pkg, out, workdir, args.preview)
```

- `_cmd_render`와 `_cmd_fill`에서 `return _save_checked(...)` 바로 앞에 `_link(pkg)` 한 줄.
- `_parser()`에서 `renumber` 다음에:

```python
    s = sub.add_parser("toc", help="차례·표 목차·그림 목차 넣기 (한글이 있으면 쪽 번호까지)")
    s.add_argument("file")
    s.add_argument("out")
    s.add_argument("--kinds", default="제목,표,그림", help="넣을 차례 (쉼표로): 제목,표,그림")
    s.add_argument("--level", type=int, default=2, help="제목 차례에 넣을 단계 (기본 2: 장·절)")
    s.add_argument("--refs", action="store_true", help="본문 표·그림 번호도 한글 상호 참조로")
    s.add_argument("--preview", help="쪽 이미지를 만들 폴더 (한글 필요)")
    s.set_defaults(func=_cmd_toc)
```

`hwpxkit/review.py`: `_check_guide_text` 다음에 아래 함수를 넣고, `review()`의 합계에 `+ _check_toc(pkg)`를 더한다.

```python
def _check_toc(pkg: Package) -> list[Finding]:
    """차례 칸의 항목에 쪽 번호(탭)가 하나도 없으면 아직 새로 고치지 않은 것."""
    from .toc import toc_blocks
    tops = [p for p in pkg.xml(pkg.section_names()[0]) if p.tag == q("hp:p")]
    for s, e, _ in toc_blocks(tops):
        items = tops[s + 1:e]
        if items and not any(next(p.iter(q("hp:tab")), None) is not None for p in items):
            return [Finding("확인", "toc-stale",
                            "차례 쪽 번호가 비어 있어요. 한글에서 도구 → 차례 새로 고침을 눌러 주세요.")]
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_toc.py -q`
Expected: `test_save_without_hangul_explains_toc`만 FAIL(`[차례]`는 Task 5), 나머지 PASS.
Run: `python -m pytest -q -m "not hangul"`
Expected: 기존 시험 모두 PASS (상호 참조 연결로 깨지는 기존 시험이 있으면 Ruling으로 기록하고, 시험 기대값을 본문 글 기준으로 고친다).

- [ ] **Step 5: Commit**

```bash
git add hwpxkit tests/test_toc.py
git commit -m "feat: toc 명령, 한글 차례 새로 고침, render·fill 상호 참조 연결, 검토 toc-stale"
```

---

### Task 5: 마크다운 `[차례]` `[표 목차]` `[그림 목차]`

**Files:**
- Modify: `hwpxkit/mdparse.py`, `hwpxkit/render.py`
- Test: `tests/test_toc.py`

**Interfaces:**
- Consumes: `insert_toc(pkg, kinds, at=..., titles=...)`
- Produces: `mdparse.Toc(kind: str)` 블록, `Renderer.toc_marks: list[tuple[element, str]]`, `Renderer.heading_els: list[tuple[element, int]]`

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_toc_lines():
    from hwpxkit.mdparse import Toc, parse
    blocks = parse("[차례]\n[ 표 목차 ]\n[그림 차례]\n[목차]\n")
    assert [b.kind for b in blocks] == ["제목", "표", "그림", "제목"] and all(isinstance(b, Toc) for b in blocks)


def test_render_toc_blocks_in_place(blank, tmp_path):
    from hwpxkit import toc
    md = "# 제1장 서론\n\n[차례]\n\n[표 목차]\n\n---쪽---\n\n" + DOC_MD.split("\n", 2)[2]
    pkg = make_doc(blank, tmp_path, md=md)
    ps = tops(pkg)
    blocks = toc.toc_blocks(ps)
    assert [m for _, _, m in blocks] == [65, 2]
    assert own_text(ps[blocks[0][0] - 1]).endswith("제1장 서론")
    after = blocks[-1][1] + 1
    assert ps[after].get("pageBreak") == "1"
    marked = [own_text(p) for p in ps if next(p.iter(q("hp:titleMark")), None) is not None]
    assert "제1장 서론" in marked and "1.1 연구 배경" in marked


def test_toc_block_first_in_document(blank, tmp_path):
    from hwpxkit import toc
    pkg = make_doc(blank, tmp_path, md="[차례]\n\n" + DOC_MD)
    blocks = toc.toc_blocks(tops(pkg))
    assert [m for _, _, m in blocks] == [65] and blocks[0][0] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_toc.py -q -k "parse_toc or render_toc or first_in"`
Expected: FAIL — `ImportError: cannot import name 'Toc'`

- [ ] **Step 3: Write implementation**

`hwpxkit/mdparse.py`:

```python
@dataclass
class Toc:
    """[차례] [표 목차] [그림 목차] 줄: 그 자리에 한글 차례 칸."""
    kind: str  # "제목" | "표" | "그림"
```

`Block = ... | Note | Toc`로 늘리고, 정규식과 `parse()` 안 `---쪽---` 처리 바로 앞에 아래를 넣는다.

```python
_TOC_LINE = re.compile(r"^\[\s*(차\s*례|목\s*차|표\s*목\s*차|표\s*차\s*례|그림\s*목\s*차|그림\s*차\s*례)\s*\]$")
```

```python
        m = _TOC_LINE.match(line)
        if m:
            word = re.sub(r"\s+", "", m.group(1))
            blocks.append(Toc("표" if word.startswith("표") else "그림" if word.startswith("그림") else "제목"))
            i += 1
            continue
```

`hwpxkit/render.py`:
- import 줄에 `Toc`를 더한다.
- `Renderer.__init__` 끝에 `self.toc_marks = []`, `self.heading_els = []`를 더한다.
- `_block`의 `Heading` 처리:

```python
        if isinstance(b, Heading):
            els = self._para(f"h{min(b.level, 5)}", b.spans)
            self.heading_els.append((els[-1], b.level))
            return els
```

- `_block`에 `PageBreak` 처리 앞:

```python
        if isinstance(b, Toc):
            p = self._make_p(self.cat.require("body"), [])
            self.toc_marks.append((p, b.kind))
            return [p]
```

- `render_into`의 `_unnumber_captionless(pkg)` 다음, `return r.warnings` 앞에 아래를 넣는다. 자리표의 쪽 나누기는 `insert_toc(at=…)`가 첫 차례 문단으로 옮긴다(Task 1의 `page_break`).

```python
    if r.toc_marks:
        from .toc import insert_toc
        root = pkg.edit(name)
        titles = [p for p, lvl in r.heading_els if lvl <= 2 and p.getparent() is not None]
        for marker, kind in r.toc_marks:
            ps = [p for p in root if p.tag == q("hp:p")]
            merged = marker.getparent() is None  # 맨 앞 블록이라 첫 문단(쪽 설정)에 합쳐짐
            r._warnings += insert_toc(pkg, [kind], at=1 if merged else ps.index(marker), titles=titles)
            if not merged:
                root.remove(marker)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_toc.py -q` 그리고 `python -m pytest -q -m "not hangul"`
Expected: 모두 PASS (Task 4의 `test_save_without_hangul_explains_toc` 포함)

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/mdparse.py hwpxkit/render.py tests/test_toc.py
git commit -m "feat: 마크다운 [차례]·[표 목차]·[그림 목차] 줄"
```

---

### Task 6: 한글 시험, 안내 문서, 0.4.0

**Files:**
- Create: `skills/hwp-helper/reference/toc.md`
- Modify: `skills/hwp-helper/SKILL.md`, `skills/hwp-helper/reference/markdown.md`, `tests/test_plugin_files.py`(허용 옵션 `--kinds`, `--level`, `--refs`), `README.md`, `.claude-plugin/plugin.json`(0.4.0)
- Test: `tests/test_toc.py`

- [ ] **Step 1: Write the failing tests**

```python
def entry_pages(pkg):
    """새로 고친 차례 칸의 항목마다 (ContentsMake, 쪽 번호 글)."""
    from hwpxkit import toc
    ps = tops(pkg)
    out = []
    for s, e, m in toc.toc_blocks(ps):
        for p in ps[s + 1:e]:
            tab = next(p.iter(q("hp:tab")), None)
            if tab is not None:
                out.append((m, (tab.tail or "").strip()))
    return out


@pytest.mark.hangul
def test_refresh_fills_page_numbers(blank, tmp_path):
    from hwpxkit import bridge, toc
    md = ("[차례]\n\n[표 목차]\n\n[그림 목차]\n\n---쪽---\n\n# 제1장 서론\n\n" + LONG + "\n\n표: 첫째 표\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n\n"
          "---쪽---\n\n# 제2장 방법\n\n## 2.1 자료\n\n" + LONG + "\n\n![첫째 그림](g.png)\n\n표: 둘째 표\n| 다 | 라 |\n|---|---|\n| 3 | 4 |\n")
    pkg = make_doc(blank, tmp_path, md=md)
    src = pkg.save(tmp_path / "before.hwpx")
    out = bridge.refresh_toc(src, tmp_path / "after.hwpx")
    pages = entry_pages(Package.open(out))
    tables = [pg for m, pg in pages if m == 2]
    figures = [pg for m, pg in pages if m == 4]
    titles = [pg for m, pg in pages if m == 65]
    assert tables == ["2", "3"] and figures == ["3"]
    assert len(titles) == 3 and titles[0] == "2"


@pytest.mark.hangul
def test_crossref_number_recomputed_by_hangul(blank, tmp_path):
    from hwpxkit import bridge, toc
    pkg = make_doc(blank, tmp_path)
    toc.link_refs(pkg)
    fb = crossrefs(pkg)[0]
    shown = fb.getparent().getnext()
    shown.text = "9"  # 일부러 틀린 값
    src = pkg.save(tmp_path / "stale.hwpx")
    out = bridge.convert(src, tmp_path / "resaved.hwpx")
    fb2 = crossrefs(Package.open(out))[0]
    assert fb2.getparent().getnext().text == "2"


def test_skill_documents_toc():
    from pathlib import Path as P
    root = P(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "toc.md").read_text(encoding="utf-8")
    for word in ("hwpx.py\" toc", "[차례]", "[표 목차]", "[그림 목차]", "--refs", "차례 새로 고침"):
        assert word in text, word
    assert "reference/toc.md" in (root / "SKILL.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_toc.py -q -k "skill_documents or refresh_fills or recomputed"`
Expected: `test_skill_documents_toc` FAIL (`FileNotFoundError`). 한글 시험 두 개는 Task 4·5 구현으로 이미 PASS일 수 있다. PASS면 회귀 고정용으로 둔다. FAIL이면 기대값과 실제 쪽 번호를 비교해 원인을 찾는다(systematic-debugging). 원인이 시험 문서의 쪽 배치라면 기대값을 실제 쪽에 맞춰 고치고 Ruling으로 기록한다.

- [ ] **Step 3: Write docs**

`skills/hwp-helper/reference/toc.md`:

```markdown
# 차례·표 목차·그림 목차와 상호 참조

한글 고유 차례 칸과 상호 참조로 넣는다. 그래서 사용자가 나중에 한글에서 고쳐도 "차례 새로 고침"으로 다시 맞춰진다.

| 사용자가 말하면 | 할 일 |
|---|---|
| 보고서 새로 쓸 때 차례도 넣어줘 | 마크다운의 표지 다음 자리에 `[차례]`, `[표 목차]`, `[그림 목차]` 줄을 쓰고 `---쪽---`으로 본문과 쪽을 나눈다 |
| 이 문서에 차례 넣어줘 | `python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" toc <문서> <결과> [--kinds 제목,표,그림] [--level 2]` |
| 본문 표 번호도 자동으로 바뀌게 | `toc … --refs` (render·fill은 저장할 때 자동으로 연결) |
| 차례 다시 맞춰줘 | 같은 `toc` 명령을 다시 실행한다 (기존 칸을 바꿈) |

- 차례 자리: 기존 차례 칸 → 양식의 "목차/차례/표 목차/그림 목차" 제목 아래 → 표지 다음 쪽 → 문서 처음.
- 한글이 있으면 저장할 때 쪽 번호까지 채운다. 한글이 없으면 쪽 번호가 비어 있으니, 사용자에게 "한글에서 도구 → 차례 새로 고침"을 누르라고 안내한다.
- 상호 참조는 문서 전체 번호([표 3])일 때만 만든다. 장별 번호([표 2-1])는 글로 두고, 번호가 바뀌면 `renumber`가 본문 참조까지 고친다.
- 제목 차례는 장·절(2단계)까지가 기본이다. 단계별 들여쓰기는 한글이 새로 고칠 때 정한다.
```

`SKILL.md`의 `## 6-1` 단락 아래(live·edit 안내 다음)에:

```markdown
차례·표 목차·그림 목차가 필요하면 마크다운에 `[차례]` 같은 줄을 쓰거나 `toc` 명령을 쓴다. 본문 표·그림 번호는 render·fill이 한글 상호 참조로 연결한다. 절차는 `reference/toc.md`.
```

`reference/markdown.md`의 블록 목록에 한 줄: `` | `[차례]` `[표 목차]` `[그림 목차]` | 그 자리에 한글 차례 칸 (쪽 번호는 한글이 채움) | ``. 표 형식이 다르면 그 문서의 기존 형식에 맞춘다.

`tests/test_plugin_files.py`의 허용 옵션 튜플에 `"--kinds", "--level", "--refs"`를 더한다. `README.md` 명령 표에 `` | `toc 문서 결과` | 차례·표 목차·그림 목차 넣기, 본문 표·그림 번호 상호 참조 (쪽 번호는 한글이 채움) | 쪽 번호만 | ``를 넣는다. `plugin.json`의 버전을 `"0.4.0"`으로 올린다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -m "not hangul"` 그리고 `python -m pytest -q tests/test_toc.py -m hangul`
Expected: 모두 PASS

- [ ] **Step 5: 실제 모양 수동 확인**

1. Step 1의 `md`와 같은 내용을 국가R&D 프리셋과 공문서 프리셋 각각으로 `render`한다(한글 있음 → 쪽 번호까지).
2. `python hwpx.py preview <결과> <폴더>`로 쪽 그림을 만들고, 차례 쪽을 읽어 확인한다.
   - 점선과 오른쪽 쪽 번호가 있는지
   - 제목 차례의 단계별 들여쓰기가 있는지
   - 표지 다음 쪽에 들어갔는지
3. 결과를 ledger에 한 줄로 남긴다. 들여쓰기가 없으면 toc.md의 마지막 줄을 실제 결과에 맞게 고친다.

- [ ] **Step 6: Commit**

```bash
git add skills tests .claude-plugin README.md
git commit -m "feat: toc 안내, 한글 시험, 0.4.0"
```

---

## Self-Review 결과

- 스펙 대응:
  - 1장 목적 → Task 1~5
  - 2장 검증 사실 → Task 1(필드 모양), Task 3(CROSSREF), Task 4(UpdateAllContents)
  - 3장 흐름 → Task 4·5
  - 4장 구성 → File Structure
  - 5장 규칙: 차례 칸 → Task 1, 자리 → Task 2, 상호 참조 → Task 3, 새로 고침 → Task 4
  - 6장 오류 → Task 1 경고, Task 4 안내
  - 8장 시험 → 각 Task와 Task 6
- 스펙과 다른 점(실행 때 Ruling으로 기록): 임시 항목은 글만 넣고 탭·쪽 번호 칸을 넣지 않는다. 한글 새로 고침이 항목을 다시 만들므로 탭 너비를 엔진이 추정할 필요가 없다. 대신 "쪽 번호 탭이 없음"이 `toc-stale`의 판정 기준이 된다.
- 포트·타입 일관성: `insert_toc(pkg, kinds, *, level, at, titles)`가 Task 1·2·4·5에서 같은 이름으로 쓰인다. `toc_blocks` 반환은 (시작, 끝, make)로 일관된다.
