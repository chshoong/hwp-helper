# 앱 안 한글 편집 화면 (edit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude 앱 브라우저 창에서 HWPX 사본을 문서처럼 보며 문단·표 칸을 직접 고치고, 부탁을 남기면 Claude가 양식 서식 그대로 반영하는 로컬 편집 화면을 만든다.

**Architecture:** `hwpxkit/editor/`에 문서 모델(doc.py), 부탁 대기 목록(queue.py), 표준 라이브러리 HTTP 서버(server.py), 화면(page.html)을 둔다. 사본에 쓰는 곳은 EditDoc 하나(서버 안 잠금)이고, Claude의 부탁 반영도 CLI → 서버 `/api/apply`를 거친다. 부탁 반영은 기존 `render_into(replace=(a, b))`를 쓴다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(http.server, threading, secrets, json, urllib), lxml, 기존 hwpxkit 엔진. 화면은 외부 자원 없는 HTML+JS 하나.

**Spec:** docs/superpowers/specs/2026-10-07-app-editor-design.md

## Global Constraints

- 원본 파일은 읽기만 한다. 수정은 `<원본이름>_수정.hwpx` 사본에만.
- 새 의존성 없음(표준 라이브러리 + lxml + 기존 hwpxkit).
- 서버는 127.0.0.1에만 묶고, 모든 요청은 열쇠값(`secrets.token_urlsafe(16)`)이 맞아야 한다(틀리면 403).
- 사용자에게 보이는 글(오류·안내·화면)은 한국어 존댓말, 쉬운 말.
- 이력은 최근 50단계, 유휴 종료는 마지막 요청 뒤 2시간(7200초).
- 화면은 외부 자원(글꼴, 스크립트, CDN)을 불러오지 않는다.
- 사용자 실제 문서(private/)를 시험이나 공개 파일에 쓰지 않는다.
- 문서 내용(수치·사실)을 지어내지 않는다(부탁 반영 시 스킬 안내에 명시).

## Review Focus

1. 사본이 한글에서 열려 있어 쓰기가 막힐 때 — 사본·이력이 망가지지 않고 423과 안내가 나와야 한다 (Task 2 `test_locked_copy_is_not_damaged`).
2. 부탁을 남긴 뒤 사용자가 그 앞 문단을 고쳐 번호가 밀린 경우 — 같은 글을 다시 찾아 반영하고, 두 곳 이상이면 반영하지 않아야 한다 (Task 3 `test_locate_*`).
3. 0번 문단(구역 설정)·표만 있는 문단·글자 모양이 섞인 문단 고치기 — 구역 설정·개체는 남고, 개체만 있는 문단은 거절 (Task 2 `test_edit_keeps_section_controls`, `test_edit_refuses_object_only`).
4. 반영 마크다운이 렌더 오류를 낼 때 — 사본은 그대로, 부탁은 error 상태 (Task 4 `test_apply_render_error_keeps_copy`).
5. 이미 서버가 떠 있는데 `edit start`를 또 부를 때 — 새 서버를 띄우지 않고 같은 주소 (Task 6 `test_start_reuses_running_server`).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `hwpxkit/editor/__init__.py` | 공개 이름: `EditDoc`, `EditError`, `AskQueue`, `copy_path` |
| `hwpxkit/editor/doc.py` | 사본 준비, 화면용 블록, 문단·칸 글 바꾸기, 판 번호, 이력·되돌리기, 외부 변경, 부탁 반영 |
| `hwpxkit/editor/queue.py` | 부탁 JSONL 읽기·쓰기·상태, 범위 다시 찾기(`locate`) |
| `hwpxkit/editor/server.py` | HTTP 처리, 열쇠값, 상태 파일, 유휴 종료, 쪽 그림 |
| `hwpxkit/editor/page.html` | 화면 |
| `hwpxkit/cli.py` | `edit start/serve/asks/apply/watch/stop` |
| `skills/hwp-helper/reference/editor.md`, `SKILL.md` | 사용 절차 |
| `tests/test_editor.py` | 모든 시험 |

---

### Task 1: 사본과 화면용 블록 (doc.py 읽기)

**Files:**
- Create: `hwpxkit/editor/__init__.py`, `hwpxkit/editor/doc.py`
- Test: `tests/test_editor.py`

**Interfaces:**
- Produces:
  - `copy_path(src: Path) -> Path` — `보고서.hwpx` → `보고서_수정.hwpx` (같은 폴더, 확장자는 항상 .hwpx)
  - `class EditError(Exception)` — `.status: int`(HTTP 코드), `str(e)`는 사용자에게 보일 한국어
  - `class EditDoc(src: Path)` — 속성 `src`, `path`(사본), `history_dir`, `version: int`; 메서드 `doc() -> dict` (스펙 4장 `/api/doc` 모양)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_editor.py
"""앱 안 편집 화면(edit): 문서 모델, 부탁 목록, 서버, CLI."""
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from helpers import LONG, SECTION, append_to_body, para, table
from hwpxkit.body import own_text
from hwpxkit.ns import q
from hwpxkit.package import Package


def make_doc(blank, tmp_path, name="보고서.hwpx"):
    """제목·본문·표가 있는 시험 문서. 0번 문단은 빈 문서의 구역 설정 문단."""
    pkg = Package.open(blank)
    append_to_body(pkg, para("□ 제1장. 데이터 이해"))
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para("둘째 본문 문단이며 " + LONG))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "창고", (0, 1): "기간", (1, 0): "A", (1, 1): "6개월"}))
    append_to_body(pkg, para("셋째 본문 문단이며 " + LONG))
    return pkg.save(tmp_path / name)


def tops(path):
    pkg = Package.open(path)
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def test_start_makes_copy_and_keeps_original(blank, tmp_path):
    from hwpxkit.editor import EditDoc, copy_path
    src = make_doc(blank, tmp_path)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    d = EditDoc(src)
    assert d.path == copy_path(src) == tmp_path / "보고서_수정.hwpx"
    assert d.path.exists() and d.version == 1
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_existing_copy_is_reused(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    src = make_doc(blank, tmp_path)
    d = EditDoc(src)
    d.edit_para(1, 2, "고친 문단")
    again = EditDoc(src)
    assert any(b.get("text") == "고친 문단" for b in again.doc()["blocks"])


def test_doc_blocks_roles_and_table(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    out = d.doc()
    assert out["version"] == 1 and out["name"] == "보고서_수정.hwpx" and out["external_change"] is False
    by_i = {b["i"]: b for b in out["blocks"]}
    assert by_i[1]["kind"] == "para" and by_i[1]["text"] == "□ 제1장. 데이터 이해"
    assert by_i[2]["role"] == "body" and by_i[2]["size"] == 10.0 and by_i[2]["bold"] is False
    tbl = by_i[4]
    assert tbl["kind"] == "table"
    assert [[c["text"] for c in row] for row in tbl["rows"]] == [["창고", "기간"], ["A", "6개월"]]
    assert tbl["rows"][1][1] == {"r": 1, "c": 1, "text": "6개월", "rs": 1, "cs": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_editor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'hwpxkit.editor'`

- [ ] **Step 3: Write minimal implementation**

```python
# hwpxkit/editor/__init__.py
"""앱 안 편집 화면: 원본은 그대로 두고 사본(<이름>_수정.hwpx)을 고친다."""
from .doc import EditDoc, EditError, copy_path
from .queue import AskQueue

__all__ = ["EditDoc", "EditError", "copy_path", "AskQueue"]
```

```python
# hwpxkit/editor/doc.py
"""편집 화면의 문서 모델. 사본에 쓰는 곳은 이 클래스 하나이고, 쓰기는 잠금으로 차례대로 한다."""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from lxml import etree

from ..body import own_text
from ..header import Header
from ..ns import q
from ..package import Package
from ..samples import bullet_chars, classify, heading_levels

HISTORY_KEEP = 50


class EditError(Exception):
    """사용자에게 그대로 보여 줄 한국어 메시지와 HTTP 상태 코드."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def copy_path(src: Path) -> Path:
    src = Path(src)
    return src.with_name(f"{src.stem}_수정.hwpx")


def _section(pkg: Package) -> str:
    return pkg.section_names()[0]


def _tops(root) -> list:
    return [p for p in root if p.tag == q("hp:p")]


class EditDoc:
    def __init__(self, src: Path):
        self.src = Path(src)
        self.path = copy_path(self.src)
        self.history_dir = self.path.with_name(f"{self.path.stem}.이력")
        self.lock = threading.Lock()
        if not self.path.exists():
            if self.src.suffix.lower() == ".hwp":
                from .. import bridge
                bridge.convert(self.src, self.path)
            else:
                shutil.copyfile(self.src, self.path)
        self.version = 1
        self._stamp = self._stat()
        self._external = False

    def _stat(self) -> tuple[float, int]:
        st = self.path.stat()
        return st.st_mtime, st.st_size

    def doc(self) -> dict:
        pkg = Package.open(self.path)
        h = Header(pkg)
        chars = bullet_chars(h)
        names = pkg.section_names()
        ps = _tops(pkg.xml(names[0]))
        levels = heading_levels(ps)
        blocks = []
        for i, p in enumerate(ps):
            tbl = next(p.iter(q("hp:tbl")), None)
            if tbl is not None:
                blocks.append({"i": i, "kind": "table", "rows": _rows(tbl)})
                continue
            if next(p.iter(q("hp:pic")), None) is not None or next(p.iter(q("hp:equation")), None) is not None:
                if not own_text(p).strip():
                    blocks.append({"i": i, "kind": "object", "text": "[그림·수식]"})
                    continue
            role, _ = classify(p, h, chars, levels)
            blocks.append({"i": i, "kind": "para", "role": role or "other", "text": own_text(p),
                           **_looks(p, h)})
        return {"version": self.version, "name": self.path.name, "external_change": self._external,
                "sections": len(names), "blocks": blocks}


def _rows(tbl) -> list[list[dict]]:
    rows = []
    for tr in tbl.findall(q("hp:tr")):
        row = []
        for tc in tr.findall(q("hp:tc")):
            addr, span = tc.find(q("hp:cellAddr")), tc.find(q("hp:cellSpan"))
            texts = [own_text(p) for p in tc.find(q("hp:subList")).findall(q("hp:p"))]
            row.append({"r": int(addr.get("rowAddr")), "c": int(addr.get("colAddr")), "text": "\n".join(texts),
                        "rs": int(span.get("rowSpan")), "cs": int(span.get("colSpan"))})
        rows.append(row)
    return rows


def _looks(p, h: Header) -> dict:
    """화면에서 문서처럼 흉내 내는 데 쓰는 겉모양 (첫 글자 모양·문단 왼쪽 여백)."""
    ids = [run.get("charPrIDRef") for run in p.findall(q("hp:run")) if run.find(q("hp:t")) is not None]
    cp = h.get("charPr", ids[0] if ids else p.find(q("hp:run")).get("charPrIDRef"))
    pp = h.get("paraPr", p.get("paraPrIDRef"))
    left = next((m.get("value") for m in pp.iter(q("hc:left"))), "0")
    return {"size": int(cp.get("height", "1000")) / 100, "bold": cp.find(q("hh:bold")) is not None,
            "indent": int(left) / 100, "mixed": len(set(ids)) > 1}
```

`hwpxkit/editor/queue.py`도 이 Task에서 빈 클래스로 만든다(import가 깨지지 않게, Task 3에서 채움):

```python
# hwpxkit/editor/queue.py
"""부탁 대기 목록 (JSONL)."""
from __future__ import annotations


class AskQueue:
    pass
```

`EditDoc.edit_para`는 Task 2에서 만든다. 이 Task에서는 `test_existing_copy_is_reused`가 아직 실패해도 된다 — Step 4에서 그 시험만 빼고 확인한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_editor.py -q -k "not reused"`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/editor tests/test_editor.py
git commit -m "feat: edit 문서 모델 — 사본 준비와 화면용 블록"
```

---

### Task 2: 문단·칸 고치기, 판 번호, 이력·되돌리기, 외부 변경 (doc.py 쓰기)

**Files:**
- Modify: `hwpxkit/editor/doc.py`
- Test: `tests/test_editor.py`

**Interfaces:**
- Consumes: Task 1 `EditDoc`, `EditError`
- Produces:
  - `EditDoc.edit_para(version: int, i: int, text: str) -> int` (새 판 번호)
  - `EditDoc.edit_cell(version: int, i: int, r: int, c: int, text: str) -> int`
  - `EditDoc.undo() -> int`
  - `EditDoc.write(mutate: Callable[[Package], None]) -> int` — 잠금 안에서 열기→mutate→이력 저장→사본 바꾸기→판 번호 올림. Task 4가 씀.
  - `EditDoc.check_external() -> bool` — `doc()` 첫머리에서 부름
  - 오류: 판 번호 다름 409 "그 사이 문서가 바뀌었어요. 새로 불러올게요.", 줄바꿈 400 "여러 문단은 '부탁하기'로 남겨 주세요.", 개체만 있는 문단 400 "표·그림만 있는 문단은 글을 고칠 수 없어요.", 잠김 423 "한글에서 이 사본을 닫은 뒤 다시 저장해 주세요.", 되돌릴 것 없음 400 "되돌릴 단계가 없어요."

- [ ] **Step 1: Write the failing tests**

```python
def test_edit_para_keeps_formats(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    before = tops(d.path)[2]
    v = d.edit_para(1, 2, "새로 쓴 문단")
    after = tops(d.path)[2]
    assert v == 2 == d.version
    assert own_text(after) == "새로 쓴 문단"
    assert after.get("paraPrIDRef") == before.get("paraPrIDRef")
    assert after.find(q("hp:run")).get("charPrIDRef") == before.find(q("hp:run")).get("charPrIDRef")
    assert next(after.iter(q("hp:linesegarray")), None) is None


def test_edit_merges_mixed_runs_into_first(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    from hwpxkit.header import Header
    pkg = Package.open(blank)
    p = para("앞 글 ")
    bold = Header(pkg).derive_charpr("0", bold=True)
    run = p.makeelement(q("hp:run"), {"charPrIDRef": bold})
    t = run.makeelement(q("hp:t"), {})
    t.text = "굵은 글"
    run.append(t)
    p.append(run)
    append_to_body(pkg, p)
    d = EditDoc(pkg.save(tmp_path / "섞임.hwpx"))
    assert next(b for b in d.doc()["blocks"] if b["i"] == 1)["mixed"] is True
    d.edit_para(1, 1, "하나로")
    p1 = tops(d.path)[1]
    assert [own_text(p1)] == ["하나로"] and len(p1.findall(q("hp:run"))) == 1


def test_edit_keeps_section_controls(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    d.edit_para(1, 0, "첫 문단 글")
    p0 = tops(d.path)[0]
    assert own_text(p0) == "첫 문단 글" and next(p0.iter(q("hp:secPr")), None) is not None


def test_edit_refuses_object_only(blank, tmp_path):
    from hwpxkit.editor import EditDoc, EditError
    d = EditDoc(make_doc(blank, tmp_path))
    with pytest.raises(EditError) as e:
        d.edit_para(1, 4, "표 문단")
    assert e.value.status == 400 and "표·그림" in str(e.value)


def test_edit_refuses_newline_and_stale_version(blank, tmp_path):
    from hwpxkit.editor import EditDoc, EditError
    d = EditDoc(make_doc(blank, tmp_path))
    with pytest.raises(EditError, match="부탁하기") as e:
        d.edit_para(1, 2, "두\n줄")
    assert e.value.status == 400
    d.edit_para(1, 2, "한 번")
    with pytest.raises(EditError) as e:
        d.edit_para(1, 2, "옛 판에서")
    assert e.value.status == 409


def test_edit_cell(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    d.edit_cell(1, 4, 1, 1, "12개월\n(연장)")
    tbl = next(b for b in d.doc()["blocks"] if b["i"] == 4)
    assert tbl["rows"][1][1]["text"] == "12개월\n(연장)"


def test_undo_and_history_limit(blank, tmp_path, monkeypatch):
    from hwpxkit.editor import EditDoc, EditError
    from hwpxkit.editor import doc as docmod
    monkeypatch.setattr(docmod, "HISTORY_KEEP", 3)
    d = EditDoc(make_doc(blank, tmp_path))
    for k in range(5):
        d.edit_para(d.version, 2, f"판 {k}")
    assert len(list(d.history_dir.glob("*.hwpx"))) == 3
    d.undo()
    assert own_text(tops(d.path)[2]) == "판 3" and d.version == 7
    for _ in range(2):
        d.undo()
    with pytest.raises(EditError, match="되돌릴"):
        d.undo()


def test_external_change_detected(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    pkg = Package.open(d.path)
    _p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
    _p.find(q("hp:run")).find(q("hp:t")).text = "한글에서 고침"
    tmp = pkg.save(tmp_path / "x.hwpx")
    time.sleep(0.05)
    tmp.replace(d.path)
    out = d.doc()
    assert out["external_change"] is True and out["version"] == 2
    assert d.doc()["external_change"] is False


def test_locked_copy_is_not_damaged(blank, tmp_path, monkeypatch):
    from hwpxkit.editor import EditDoc, EditError
    from hwpxkit.editor import doc as docmod
    d = EditDoc(make_doc(blank, tmp_path))
    before = d.path.read_bytes()

    def locked(*a, **k):
        raise PermissionError("locked")
    monkeypatch.setattr(docmod.os, "replace", locked)
    with pytest.raises(EditError) as e:
        d.edit_para(1, 2, "막힘")
    assert e.value.status == 423 and "한글에서" in str(e.value)
    assert d.path.read_bytes() == before and d.version == 1
    assert list(d.history_dir.glob("*.hwpx")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_editor.py -q`
Expected: FAIL — `AttributeError: 'EditDoc' object has no attribute 'edit_para'` 등

- [ ] **Step 3: Write implementation** (doc.py에 추가)

파일 첫머리 import에 `import os`, `import tempfile`, `from typing import Callable`, `from ..body import strip_lineseg`를 더한다. `EditDoc` 안에 아래 메서드를, 모듈 끝에 `_set_text`를 더한다. `doc()` 첫 줄에 `self.check_external()`을 넣는다.

```python
    def check_external(self) -> bool:
        """한글 등 다른 프로그램이 사본을 바꿨으면 판 번호를 올리고 한 번만 알린다."""
        with self.lock:
            now = self._stat()
            if now != self._stamp:
                self._stamp = now
                self.version += 1
                self._external = True
                return True
            return False

    # Task 1의 doc()에서 두 군데만 바꾼다:
    #   첫 줄에   changed = self.check_external()
    #   return의  "external_change": self._external  →  "external_change": changed
    # 그리고 __init__의 self._external = False 줄은 지운다(더 쓰지 않음).

    def _expect(self, version: int) -> None:
        if version != self.version:
            raise EditError("그 사이 문서가 바뀌었어요. 새로 불러올게요.", 409)

    def write(self, mutate: Callable[[Package], None], version: int | None = None, history: bool = True) -> int:
        with self.lock:
            if version is not None:
                self._expect(version)
            pkg = Package.open(self.path)
            mutate(pkg)
            fd, tmp = tempfile.mkstemp(suffix=".hwpx", dir=self.path.parent)
            os.close(fd)
            tmp = Path(tmp)
            try:
                tmp.unlink()
                pkg.save(tmp)
                hist = None
                if history:
                    self.history_dir.mkdir(exist_ok=True)
                    hist = self.history_dir / f"{self.version:05d}.hwpx"
                    shutil.copyfile(self.path, hist)
                try:
                    os.replace(tmp, self.path)
                except PermissionError as e:
                    if hist is not None:
                        hist.unlink(missing_ok=True)
                    raise EditError("한글에서 이 사본을 닫은 뒤 다시 저장해 주세요.", 423) from e
            finally:
                tmp.unlink(missing_ok=True)
            if history:
                for old in sorted(self.history_dir.glob("*.hwpx"))[:-HISTORY_KEEP]:
                    old.unlink()
            self.version += 1
            self._stamp = self._stat()
            return self.version

    def edit_para(self, version: int, i: int, text: str) -> int:
        if "\n" in text or "\r" in text:
            raise EditError("여러 문단은 '부탁하기'로 남겨 주세요.", 400)

        def mutate(pkg):
            ps = _tops(pkg.edit(_section(pkg)))
            if not 0 <= i < len(ps):
                raise EditError("그 문단을 찾지 못했어요. 새로 불러올게요.", 409)
            p = ps[i]
            has_obj = any(next(p.iter(q(t)), None) is not None for t in ("hp:tbl", "hp:pic", "hp:equation"))
            if has_obj and not own_text(p).strip():
                raise EditError("표·그림만 있는 문단은 글을 고칠 수 없어요.", 400)
            _set_text(p, text)

        return self.write(mutate, version)

    def edit_cell(self, version: int, i: int, r: int, c: int, text: str) -> int:
        lines = text.replace("\r\n", "\n").split("\n")

        def mutate(pkg):
            ps = _tops(pkg.edit(_section(pkg)))
            tbl = next(ps[i].iter(q("hp:tbl")), None) if 0 <= i < len(ps) else None
            tc = None if tbl is None else next(
                (tc for tc in tbl.iter(q("hp:tc"))
                 if (int(tc.find(q("hp:cellAddr")).get("rowAddr")), int(tc.find(q("hp:cellAddr")).get("colAddr"))) == (r, c)),
                None)
            if tc is None:
                raise EditError("그 칸을 찾지 못했어요. 새로 불러올게요.", 409)
            sub = tc.find(q("hp:subList"))
            cps = sub.findall(q("hp:p"))
            first = cps[0]
            for extra in cps[1:]:
                sub.remove(extra)
            _set_text(first, lines[0])
            at = sub.index(first)
            for k, line in enumerate(lines[1:], 1):
                clone = etree.fromstring(etree.tostring(first))
                _set_text(clone, line)
                sub.insert(at + k, clone)

        return self.write(mutate, version)

    def undo(self) -> int:
        hist = sorted(self.history_dir.glob("*.hwpx")) if self.history_dir.exists() else []
        if not hist:
            raise EditError("되돌릴 단계가 없어요.", 400)
        last = hist[-1]
        restored = Package.open(last)

        def mutate(pkg):
            for name in pkg.names():
                pkg.remove(name)
            for name in restored.names():
                pkg.write(name, restored.read(name))

        # 되돌리기는 이력을 새로 남기지 않고, 되살린 이력을 지운다: 거듭하면 더 옛 판으로 간다
        v = self.write(mutate, history=False)
        last.unlink(missing_ok=True)
        return v
```

```python
def _set_text(p, text: str) -> None:
    """문단 글을 바꾼다. 글이 든 첫 줄의 글자 모양을 쓰고, 다른 글 조각은 지운다. 구역 설정·개체는 남긴다."""
    runs = p.findall(q("hp:run"))
    with_t = [run for run in runs if run.find(q("hp:t")) is not None]
    keep = with_t[0] if with_t else (runs[-1] if runs else etree.SubElement(p, q("hp:run"), {"charPrIDRef": "0"}))
    for run in runs:
        for t in run.findall(q("hp:t")):
            run.remove(t)
        if run is not keep and len(run) == 0:
            p.remove(run)
    t = etree.SubElement(keep, q("hp:t"))
    t.text = text
    strip_lineseg(p)
```

`undo`의 `pkg.remove`/`pkg.write` 사용: `Package.write(name, data)`는 이미 있고 `Package.remove`는 live 작업에서 추가됨. `mimetype`의 압축 방식은 `save`가 STORED로 처리한다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_editor.py -q`
Expected: PASS (모든 시험, `test_existing_copy_is_reused` 포함)

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/editor/doc.py tests/test_editor.py
git commit -m "feat: edit 문단·칸 고치기, 판 번호, 이력·되돌리기, 외부 변경 감지"
```

---

### Task 3: 부탁 대기 목록과 범위 다시 찾기 (queue.py)

**Files:**
- Modify: `hwpxkit/editor/queue.py`
- Test: `tests/test_editor.py`

**Interfaces:**
- Produces:
  - `AskQueue(path: Path)` — `path`는 `<사본 stem>.부탁.jsonl`
  - `AskQueue.for_copy(copy: Path) -> AskQueue`
  - `AskQueue.add(version: int, start: int, end: int, texts: list[str], text: str) -> dict` — `{"id": "a1", "version", "start", "end", "texts", "text", "status": "pending", "message": "", "time"}`; id는 `a` + 순번
  - `AskQueue.all() -> list[dict]`, `AskQueue.get(id) -> dict` (없으면 `KeyError`)
  - `AskQueue.set(id: str, status: str, message: str = "") -> dict` — status ∈ pending/done/stale/error
  - `locate(current: list[str], ask: dict) -> tuple[int, int] | None`

- [ ] **Step 1: Write the failing tests**

```python
def test_queue_add_and_status(tmp_path):
    from hwpxkit.editor import AskQueue
    qu = AskQueue.for_copy(tmp_path / "보고서_수정.hwpx")
    assert qu.path == tmp_path / "보고서_수정.부탁.jsonl"
    a = qu.add(3, 2, 4, ["가", "나"], "두 줄로 줄여줘")
    b = qu.add(3, 5, 6, ["다"], "표로 바꿔줘")
    assert (a["id"], b["id"], a["status"]) == ("a1", "a2", "pending")
    qu.set("a1", "done")
    again = AskQueue.for_copy(tmp_path / "보고서_수정.hwpx")
    assert [x["status"] for x in again.all()] == ["done", "pending"]
    assert again.get("a2")["text"] == "표로 바꿔줘"
    with pytest.raises(KeyError):
        again.get("a9")


def test_locate_same_place():
    from hwpxkit.editor.queue import locate
    assert locate(["x", "가", "나", "y"], {"start": 1, "end": 3, "texts": ["가", "나"]}) == (1, 3)


def test_locate_shifted():
    from hwpxkit.editor.queue import locate
    assert locate(["x", "새", "가", "나", "y"], {"start": 1, "end": 3, "texts": ["가", "나"]}) == (2, 4)


def test_locate_ambiguous_or_missing():
    from hwpxkit.editor.queue import locate
    ask = {"start": 1, "end": 2, "texts": ["가"]}
    assert locate(["x", "바뀜", "가", "가"], ask) is None
    assert locate(["x", "없음"], ask) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_editor.py -q -k "queue or locate"`
Expected: FAIL — `AttributeError: type object 'AskQueue' has no attribute 'for_copy'`

- [ ] **Step 3: Write implementation**

```python
# hwpxkit/editor/queue.py
"""부탁 대기 목록 (JSONL, 한 줄에 부탁 하나). 범위는 남길 때의 문단 번호와 글을 함께 적는다."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class AskQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    @classmethod
    def for_copy(cls, copy: Path) -> "AskQueue":
        copy = Path(copy)
        return cls(copy.with_name(f"{copy.stem}.부탁.jsonl"))

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _save(self, asks: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in asks), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, ask_id: str) -> dict:
        for a in self.all():
            if a["id"] == ask_id:
                return a
        raise KeyError(ask_id)

    def add(self, version: int, start: int, end: int, texts: list[str], text: str) -> dict:
        with self.lock:
            asks = self.all()
            ask = {"id": f"a{len(asks) + 1}", "version": version, "start": start, "end": end, "texts": texts,
                   "text": text, "status": "pending", "message": "", "time": time.strftime("%Y-%m-%d %H:%M")}
            self._save(asks + [ask])
            return ask

    def set(self, ask_id: str, status: str, message: str = "") -> dict:
        with self.lock:
            asks = self.all()
            for a in asks:
                if a["id"] == ask_id:
                    a["status"], a["message"] = status, message
                    self._save(asks)
                    return a
        raise KeyError(ask_id)


def locate(current: list[str], ask: dict) -> tuple[int, int] | None:
    """부탁 범위를 지금 문서에서 찾는다: 같은 자리 → 밀린 자리(한 곳일 때만) → 못 찾음(None)."""
    texts, start, end = ask["texts"], ask["start"], ask["end"]
    n = len(texts)
    if current[start:end] == texts:
        return start, end
    hits = [k for k in range(len(current) - n + 1) if current[k:k + n] == texts]
    return (hits[0], hits[0] + n) if len(hits) == 1 else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_editor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/editor/queue.py tests/test_editor.py
git commit -m "feat: edit 부탁 대기 목록과 범위 다시 찾기"
```

---

### Task 4: 부탁 범위 읽기·반영 (doc.py)

**Files:**
- Modify: `hwpxkit/editor/doc.py`
- Test: `tests/test_editor.py`

**Interfaces:**
- Consumes: Task 2 `EditDoc.write`, Task 3 `AskQueue`, `locate`
- Produces:
  - `EditDoc.texts() -> list[str]` — 첫 구역 최상위 문단마다 `all_text(p).strip()` (표 글 포함)
  - `EditDoc.ask(queue: AskQueue, version: int, start: int, end: int, text: str) -> dict` — 판 번호 확인(409), 범위 확인(400 "고른 범위가 올바르지 않아요."), `start >= 1`(0번은 400 "첫 문단(쪽 설정)은 부탁 범위에 넣을 수 없어요. 둘째 문단부터 골라 주세요.")
  - `EditDoc.range_markdown(start: int, end: int) -> str` — `reader.to_markdown(anchors=True)`에서 `start <= n < end` 블록만
  - `EditDoc.apply(queue: AskQueue, ask_id: str, md: str, base_dir: Path) -> dict` — `{"status": "done"|"stale"|"error", "message", "version", "warnings"}`; stale·error면 사본 안 바뀜

- [ ] **Step 1: Write the failing tests**

```python
def _ask(d, start, end, text="두 줄로 줄여줘"):
    from hwpxkit.editor import AskQueue
    qu = AskQueue.for_copy(d.path)
    return qu, d.ask(qu, d.version, start, end, text)


def test_ask_records_texts_and_refuses_bad_range(blank, tmp_path):
    from hwpxkit.editor import EditError
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 4)
    assert a["texts"] == [LONG, "둘째 본문 문단이며 " + LONG] and a["version"] == 1
    with pytest.raises(EditError, match="첫 문단"):
        d.ask(qu, d.version, 0, 2, "x")
    with pytest.raises(EditError, match="범위"):
        d.ask(qu, d.version, 3, 3, "x")


def test_range_markdown(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    md = d.range_markdown(2, 4)
    assert LONG in md and "둘째 본문" in md and "제1장" not in md and "셋째" not in md


def test_apply_replaces_range(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 4)
    r = d.apply(qu, a["id"], "줄인 문단 하나로 정리한 결과 문장이며 길이를 맞추기 위해 조금 더 씀\n", tmp_path)
    assert r["status"] == "done" and r["version"] == 2
    texts = d.texts()
    assert "줄인 문단 하나로" in texts[2] and texts[3].startswith("창고")
    assert qu.get(a["id"])["status"] == "done"


def test_apply_after_shift(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 5, 6)
    d.edit_para(d.version, 2, "앞 문단을 고침")
    def add_para(pkg):
        root = pkg.edit(SECTION)
        ps = [p for p in root if p.tag == q("hp:p")]
        root.insert(root.index(ps[1]) + 1, para("끼운 문단"))
    d.write(add_para)
    assert d.apply(qu, a["id"], "바뀐 셋째 문단\n", tmp_path)["status"] == "done"
    assert "바뀐 셋째 문단" in d.texts()[-1]


def test_apply_stale_keeps_copy(blank, tmp_path):
    from hwpxkit.editor import EditDoc
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 3)
    d.edit_para(d.version, 2, "완전히 다른 글")
    before = d.path.read_bytes()
    r = d.apply(qu, a["id"], "새 글\n", tmp_path)
    assert r["status"] == "stale" and "바뀌" in r["message"]
    assert d.path.read_bytes() == before and qu.get(a["id"])["status"] == "stale"


def test_apply_render_error_keeps_copy(blank, tmp_path, monkeypatch):
    from hwpxkit.editor import EditDoc
    from hwpxkit.editor import doc as docmod
    from hwpxkit.render import RenderError
    d = EditDoc(make_doc(blank, tmp_path))
    qu, a = _ask(d, 2, 3)
    before = d.path.read_bytes()

    def boom(*a, **k):
        raise RenderError("그림 파일을 찾을 수 없어요: 없음.png")
    monkeypatch.setattr(docmod, "render_into", boom)
    r = d.apply(qu, a["id"], "![x](없음.png)\n", tmp_path)
    assert r["status"] == "error" and "없음.png" in r["message"]
    assert d.path.read_bytes() == before and d.version == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_editor.py -q -k "ask or range_markdown or apply"`
Expected: FAIL — `AttributeError: 'EditDoc' object has no attribute 'ask'`

- [ ] **Step 3: Write implementation** (doc.py에 추가)

import에 `from ..body import all_text`, `from ..reader import to_markdown`, `from ..render import RenderError, render_into`, `from ..samples import infer`, `from .queue import AskQueue, locate`를 더한다.

```python
    def texts(self) -> list[str]:
        pkg = Package.open(self.path)
        return [all_text(p).strip() for p in _tops(pkg.xml(_section(pkg)))]

    def ask(self, queue: AskQueue, version: int, start: int, end: int, text: str) -> dict:
        self._expect(version)
        if start < 1:
            raise EditError("첫 문단(쪽 설정)은 부탁 범위에 넣을 수 없어요. 둘째 문단부터 골라 주세요.", 400)
        texts = self.texts()
        if not start < end <= len(texts) or not text.strip():
            raise EditError("고른 범위가 올바르지 않아요.", 400)
        return queue.add(version, start, end, texts[start:end], text.strip())

    def range_markdown(self, start: int, end: int) -> str:
        md = to_markdown(Package.open(self.path), anchors=True)
        out, keep = [], False
        for line in md.splitlines():
            if line.startswith("<!-- @") and line.endswith("-->"):
                n = int(line[6:-3].strip())
                keep = start <= n < end
                continue
            if keep:
                out.append(line)
        return "\n".join(out).strip() + "\n"

    def apply(self, queue: AskQueue, ask_id: str, md: str, base_dir: Path) -> dict:
        ask = queue.get(ask_id)
        rng = locate(self.texts(), ask)
        if rng is None:
            msg = "부탁을 남긴 뒤 그 부분이 바뀌어서 어디에 반영할지 다시 확인이 필요해요."
            queue.set(ask_id, "stale", msg)
            return {"status": "stale", "message": msg, "version": self.version, "warnings": []}
        warnings: list[str] = []

        def mutate(pkg):
            warnings.extend(render_into(pkg, infer(pkg), md, replace=rng, base_dir=Path(base_dir)))

        try:
            v = self.write(mutate)
        except (RenderError, ValueError) as e:
            queue.set(ask_id, "error", str(e))
            return {"status": "error", "message": str(e), "version": self.version, "warnings": []}
        queue.set(ask_id, "done")
        return {"status": "done", "message": "", "version": v, "warnings": warnings}
```

`render_into`는 `infer(pkg)` 카탈로그로 견본 서식을 복제한다. `write`는 mutate가 예외를 내면 사본을 바꾸지 않는다(이력도 남기지 않음 — Task 2 `write`에서 mutate가 tmp 생성보다 먼저 실행되므로).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_editor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/editor/doc.py tests/test_editor.py
git commit -m "feat: edit 부탁 범위 읽기와 양식 서식 그대로 반영"
```

---

### Task 5: 로컬 서버 (server.py)

**Files:**
- Create: `hwpxkit/editor/server.py`, `hwpxkit/editor/page.html`(Task 7에서 채울 최소 HTML: `<!doctype html><meta charset="utf-8"><title>한글 편집</title><div id="app"></div>`)
- Test: `tests/test_editor.py`

**Interfaces:**
- Consumes: `EditDoc`, `EditError`, `AskQueue`
- Produces:
  - `make_server(doc: EditDoc, queue: AskQueue, key: str, *, port: int = 0, idle: float = 7200, base_dir: Path | None = None) -> ThreadingHTTPServer` — 서버에 `.url`(`http://127.0.0.1:<port>/?k=<key>`), `.last`(마지막 요청 시각) 속성
  - `state_path(copy: Path) -> Path` — `<사본 stem>.서버.json`
  - `serve(src: Path, idle: float = 7200) -> None` — 사본 준비, 상태 파일 `{"port","key","pid","url"}` 쓰기, 유휴 감시 스레드, `serve_forever`, 끝나면 상태 파일 지움
  - API: 스펙 4장 표. 응답은 JSON, 오류는 `{"error": "<한국어>"}`와 해당 코드. `POST /api/stop`(열쇠 필요)도 둔다(CLI `edit stop`용).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.fixture
def server(blank, tmp_path):
    from hwpxkit.editor import AskQueue, EditDoc
    from hwpxkit.editor.server import make_server
    d = EditDoc(make_doc(blank, tmp_path))
    srv = make_server(d, AskQueue.for_copy(d.path), "열쇠", base_dir=tmp_path)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv, d
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None, key="열쇠"):
    url = f"http://127.0.0.1:{srv.server_address[1]}{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-Key": urllib.parse.quote(key), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_server_rejects_wrong_key(server):
    srv, _ = server
    assert call(srv, "GET", "/api/doc", key="틀림")[0] == 403
    assert call(srv, "GET", "/", key="틀림")[0] == 403


def test_server_page_with_key_in_query(server):
    srv, _ = server
    with urllib.request.urlopen(srv.url, timeout=10) as r:
        assert r.status == 200 and "한글 편집" in r.read().decode("utf-8")


def test_server_edit_flow(server):
    srv, d = server
    st, doc = call(srv, "GET", "/api/doc")
    assert st == 200 and doc["version"] == 1
    st, r = call(srv, "POST", "/api/edit", {"version": 1, "i": 2, "text": "서버로 고침"})
    assert st == 200 and r["version"] == 2
    assert call(srv, "POST", "/api/edit", {"version": 1, "i": 2, "text": "옛 판"})[0] == 409
    st, r = call(srv, "POST", "/api/edit", {"version": 2, "i": 4, "r": 0, "c": 0, "text": "창고명"})
    assert st == 200
    st, r = call(srv, "POST", "/api/undo", {})
    assert st == 200 and r["version"] == 4


def test_server_ask_and_apply(server):
    srv, d = server
    st, a = call(srv, "POST", "/api/ask", {"version": 1, "start": 2, "end": 3, "text": "줄여줘"})
    assert st == 200 and a["id"] == "a1"
    st, asks = call(srv, "GET", "/api/asks")
    assert [x["status"] for x in asks["asks"]] == ["pending"]
    st, r = call(srv, "POST", "/api/apply", {"id": "a1", "md": "줄인 결과 문장입니다\n"})
    assert st == 200 and r["status"] == "done"
    assert "줄인 결과" in d.texts()[2]


def test_server_bad_json_is_400(server):
    srv, _ = server
    st, r = call(srv, "POST", "/api/edit", {"version": 1})
    assert st == 400 and r["error"]


def test_idle_shutdown(blank, tmp_path):
    from hwpxkit.editor import AskQueue, EditDoc
    from hwpxkit.editor.server import make_server, watch_idle
    d = EditDoc(make_doc(blank, tmp_path))
    srv = make_server(d, AskQueue.for_copy(d.path), "k", idle=0.3)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    watch_idle(srv, every=0.1)
    th.join(timeout=5)
    assert not th.is_alive()
    srv.server_close()
```

파일 첫머리 import에 `import urllib.parse`를 더한다.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_editor.py -q -k "server or idle"`
Expected: FAIL — `ModuleNotFoundError: No module named 'hwpxkit.editor.server'`

- [ ] **Step 3: Write implementation**

```python
# hwpxkit/editor/server.py
"""편집 화면 로컬 서버. 127.0.0.1에만 묶고 모든 요청에 열쇠값을 확인한다."""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .doc import EditDoc, EditError
from .queue import AskQueue

_PAGE = Path(__file__).with_name("page.html")


def state_path(copy: Path) -> Path:
    copy = Path(copy)
    return copy.with_name(f"{copy.stem}.서버.json")


def make_server(doc: EditDoc, queue: AskQueue, key: str, *, port: int = 0, idle: float = 7200,
                base_dir: Path | None = None) -> ThreadingHTTPServer:
    pages_dir = Path(tempfile.mkdtemp(prefix="hwpx-edit-pages-"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 조용히
            pass

        def _send(self, status: int, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self, query: dict) -> bool:
            given = urllib.parse.unquote(self.headers.get("X-Key", "")) or query.get("k", [""])[0]
            return secrets.compare_digest(given.encode("utf-8"), key.encode("utf-8"))

        def _route(self, method: str):
            srv.last = time.monotonic()
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if not self._authorized(query):
                return self._send(403, {"error": "열쇠값이 맞지 않아요."})
            try:
                body = {}
                if method == "POST":
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                return self._dispatch(method, url.path, body)
            except EditError as e:
                return self._send(e.status, {"error": str(e)})
            except (KeyError, TypeError, ValueError) as e:
                return self._send(400, {"error": f"요청을 이해하지 못했어요: {e}"})

        def _dispatch(self, method: str, path: str, body: dict):
            if method == "GET" and path == "/":
                return self._send(200, _PAGE.read_bytes(), "text/html; charset=utf-8")
            if method == "GET" and path == "/api/doc":
                return self._send(200, doc.doc())
            if method == "GET" and path == "/api/asks":
                return self._send(200, {"asks": queue.all()})
            if method == "GET" and path.startswith("/pages/"):
                f = pages_dir / Path(path).name
                if not f.is_file():
                    return self._send(404, {"error": "쪽 그림이 없어요."})
                return self._send(200, f.read_bytes(), "image/png")
            if method == "POST" and path == "/api/edit":
                if "r" in body:
                    v = doc.edit_cell(int(body["version"]), int(body["i"]), int(body["r"]), int(body["c"]),
                                      str(body["text"]))
                else:
                    v = doc.edit_para(int(body["version"]), int(body["i"]), str(body["text"]))
                return self._send(200, {"version": v})
            if method == "POST" and path == "/api/ask":
                return self._send(200, doc.ask(queue, int(body["version"]), int(body["start"]), int(body["end"]),
                                               str(body["text"])))
            if method == "POST" and path == "/api/apply":
                return self._send(200, doc.apply(queue, str(body["id"]), str(body["md"]),
                                                 Path(body.get("base_dir") or base_dir or doc.path.parent)))
            if method == "POST" and path == "/api/undo":
                return self._send(200, {"version": doc.undo()})
            if method == "POST" and path == "/api/pages":
                from .. import bridge
                if not bridge.available():
                    raise EditError("한글이 있어야 실제 쪽 모양을 볼 수 있어요.", 400)
                for old in pages_dir.glob("*.png"):
                    old.unlink()
                files = bridge.page_images(doc.path, pages_dir)
                return self._send(200, {"pages": [f"/pages/{f.name}" for f in files]})
            if method == "POST" and path == "/api/stop":
                threading.Thread(target=srv.shutdown, daemon=True).start()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "없는 주소예요."})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    srv.last = time.monotonic()
    srv.idle = idle
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}/?k={urllib.parse.quote(key)}"
    return srv


def watch_idle(srv: ThreadingHTTPServer, every: float = 60) -> threading.Thread:
    def loop():
        while True:
            time.sleep(every)
            if time.monotonic() - srv.last > srv.idle:
                srv.shutdown()
                return
    th = threading.Thread(target=loop, daemon=True)
    th.start()
    return th


def serve(src: Path, idle: float = 7200) -> None:
    doc = EditDoc(Path(src))
    queue = AskQueue.for_copy(doc.path)
    key = secrets.token_urlsafe(16)
    srv = make_server(doc, queue, key, idle=idle, base_dir=doc.path.parent)
    state = state_path(doc.path)
    state.write_text(json.dumps({"port": srv.server_address[1], "key": key, "pid": os.getpid(), "url": srv.url},
                                ensure_ascii=False), encoding="utf-8")
    watch_idle(srv)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        state.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_editor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/editor/server.py hwpxkit/editor/page.html tests/test_editor.py
git commit -m "feat: edit 로컬 서버 — 열쇠값, 고치기·부탁·반영·되돌리기, 유휴 종료"
```

---

### Task 6: CLI `edit` (start/serve/asks/apply/watch/stop)

**Files:**
- Modify: `hwpxkit/cli.py` (`_cmd_edit` 추가, `_parser`에 `edit` 하위 명령)
- Test: `tests/test_editor.py`

**Interfaces:**
- Consumes: `serve`, `state_path`, `EditDoc`, `AskQueue`, `copy_path`
- Produces (CLI):
  - `edit start <원본>` — 상태 파일의 PID가 살아 있고 `/api/doc`가 응답하면 그 주소를 출력(새로 안 띄움). 아니면 `[sys.executable, <플러그인 루트>/hwpx.py, "edit", "serve", <원본>]`를 분리된 프로세스로 띄우고 상태 파일을 최대 15초 기다려 주소 출력. 출력 형식: 첫 줄 `편집 화면: <url>`, 둘째 줄 `사본: <사본 경로> (원본은 그대로)`.
  - `edit serve <원본>` — 내부용, `serve()` 실행.
  - `edit asks <원본> [--json]` — 대기(pending) 부탁마다 `{"id","text","start","end","markdown"}`; 글 출력은 `[a1] 2~3번 문단: 두 줄로 줄여줘` 뒤에 범위 마크다운.
  - `edit apply <원본> <id> <새내용.md>` — 서버가 있으면 `/api/apply`(base_dir=md 폴더), 없으면 `EditDoc` 직접. 결과 출력: done → `반영했어요.`, stale/error → 메시지, 종료 코드 1.
  - `edit watch <원본>` — 2초마다 부탁 목록을 보고, 새 pending id가 생기면 `새 부탁 <id>: <글>` 한 줄 출력(flush). 서버 상태 파일이 사라지면 `편집 화면이 꺼졌어요.` 출력 후 종료.
  - `edit stop <원본>` — `/api/stop`, 상태 파일 정리, `편집 화면을 껐어요.`

- [ ] **Step 1: Write the failing tests**

```python
def _cli(*args):
    from hwpxkit.cli import main
    return main(["edit", *map(str, args)])


def test_cli_asks_and_apply_without_server(blank, tmp_path, capsys):
    from hwpxkit.editor import AskQueue, EditDoc
    src = make_doc(blank, tmp_path)
    d = EditDoc(src)
    d.ask(AskQueue.for_copy(d.path), 1, 2, 3, "줄여줘")
    assert _cli("asks", src, "--json") == 0
    asks = json.loads(capsys.readouterr().out)
    assert asks[0]["id"] == "a1" and LONG in asks[0]["markdown"]
    md = tmp_path / "새.md"
    md.write_text("CLI로 바꾼 문장입니다\n", encoding="utf-8")
    assert _cli("apply", src, "a1", md) == 0
    assert "반영했어요" in capsys.readouterr().out
    assert "CLI로 바꾼" in EditDoc(src).texts()[2]


def test_cli_apply_stale_exit_1(blank, tmp_path, capsys):
    from hwpxkit.editor import AskQueue, EditDoc
    src = make_doc(blank, tmp_path)
    d = EditDoc(src)
    d.ask(AskQueue.for_copy(d.path), 1, 2, 3, "줄여줘")
    d.edit_para(d.version, 2, "딴 글")
    md = tmp_path / "새.md"
    md.write_text("새 글\n", encoding="utf-8")
    assert _cli("apply", src, "a1", md) == 1
    assert "다시 확인" in capsys.readouterr().out


def test_start_serve_stop(blank, tmp_path, capsys):
    src = make_doc(blank, tmp_path)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    try:
        assert _cli("start", src) == 0
        out = capsys.readouterr().out
        url = out.splitlines()[0].split(": ", 1)[1]
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200
    finally:
        assert _cli("stop", src) == 0
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    assert not (tmp_path / "보고서_수정.서버.json").exists()


def test_start_reuses_running_server(blank, tmp_path, capsys):
    src = make_doc(blank, tmp_path)
    try:
        _cli("start", src)
        first = capsys.readouterr().out.splitlines()[0]
        _cli("start", src)
        assert capsys.readouterr().out.splitlines()[0] == first
    finally:
        _cli("stop", src)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_editor.py -q -k "cli or start"`
Expected: FAIL — argparse `invalid choice: 'edit'` (SystemExit 2)

- [ ] **Step 3: Write implementation** (cli.py)

```python
def _edit_state(src: Path) -> dict | None:
    """살아 있는 편집 서버의 상태 (없거나 죽었으면 None, 죽은 상태 파일은 지운다)."""
    import urllib.request
    from .editor import copy_path
    from .editor.server import state_path
    st_file = state_path(copy_path(src))
    if not st_file.exists():
        return None
    st = json.loads(st_file.read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{st['port']}/api/doc",
                                     headers={"X-Key": urllib.parse.quote(st["key"])})
        with urllib.request.urlopen(req, timeout=5):
            return st
    except OSError:
        st_file.unlink(missing_ok=True)
        return None


def _edit_post(st: dict, path: str, body: dict) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{st['port']}{path}", method="POST",
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"X-Key": urllib.parse.quote(st["key"]), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _cmd_edit(args, workdir) -> int:
    import subprocess
    import time
    from .editor import AskQueue, EditDoc, copy_path
    from .editor.server import serve, state_path
    src = Path(args.file)
    if not src.is_file():
        raise PackageError(f"파일을 찾을 수 없어요: {src}")
    act = args.edit_action
    if act == "serve":
        serve(src)
        return 0
    if act == "start":
        st = _edit_state(src)
        if st is None:
            EditDoc(src)  # 사본을 먼저 만들어 오류를 여기서 알린다
            root = Path(__file__).resolve().parents[1]
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([sys.executable, str(root / "hwpx.py"), "edit", "serve", str(src)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=flags, close_fds=True)
            for _ in range(60):
                time.sleep(0.25)
                st = _edit_state(src)
                if st:
                    break
            if st is None:
                raise PackageError("편집 화면을 띄우지 못했어요. 다시 시도해 주세요.")
        print(f"편집 화면: {st['url']}")
        print(f"사본: {copy_path(src)} (원본은 그대로)")
        return 0
    if act == "stop":
        st = _edit_state(src)
        if st:
            _edit_post(st, "/api/stop", {})
            for _ in range(20):
                time.sleep(0.25)
                if not state_path(copy_path(src)).exists():
                    break
        state_path(copy_path(src)).unlink(missing_ok=True)
        print("편집 화면을 껐어요.")
        return 0
    queue = AskQueue.for_copy(copy_path(src))
    if act == "asks":
        doc = EditDoc(src)
        pending = [{"id": a["id"], "text": a["text"], "start": a["start"], "end": a["end"],
                    "markdown": doc.range_markdown(a["start"], a["end"])}
                   for a in queue.all() if a["status"] == "pending"]
        if args.json:
            print(json.dumps(pending, ensure_ascii=False))
        elif not pending:
            print("대기 중인 부탁이 없어요.")
        for a in [] if args.json else pending:
            print(f"[{a['id']}] {a['start']}~{a['end'] - 1}번 문단: {a['text']}\n{a['markdown']}")
        return 0
    if act == "watch":
        seen = {a["id"] for a in queue.all()}
        while state_path(copy_path(src)).exists():
            for a in queue.all():
                if a["id"] not in seen and a["status"] == "pending":
                    seen.add(a["id"])
                    print(f"새 부탁 {a['id']}: {a['text']}", flush=True)
            time.sleep(2)
        print("편집 화면이 꺼졌어요.", flush=True)
        return 0
    # apply
    md_path = Path(args.md)
    if not md_path.is_file():
        raise PackageError(f"내용 파일을 찾을 수 없어요: {md_path}")
    md = md_path.read_text(encoding="utf-8-sig")
    st = _edit_state(src)
    if st:
        code, r = _edit_post(st, "/api/apply", {"id": args.ask_id, "md": md, "base_dir": str(md_path.parent)})
        if code != 200:
            raise PackageError(r.get("error", "반영하지 못했어요."))
    else:
        r = EditDoc(src).apply(queue, args.ask_id, md, md_path.parent)
    for w in r.get("warnings", []):
        print(f"[주의] {w}")
    if r["status"] == "done":
        print("반영했어요. 편집 화면이 새로 고쳐져요.")
        return 0
    print(r["message"])
    return 1
```

cli.py 첫머리에 `import urllib.parse`를 더한다. `_parser()`의 `live` 뒤에:

```python
    s = sub.add_parser("edit", help="앱 브라우저 창에서 사본을 보며 고치기 (원본은 그대로)")
    s.add_argument("edit_action", choices=["start", "serve", "asks", "apply", "watch", "stop"])
    s.add_argument("file", help="원본 .hwpx (또는 .hwp)")
    s.add_argument("ask_id", nargs="?", default="", help="apply: 부탁 번호 (예: a1)")
    s.add_argument("md", nargs="?", default="", help="apply: 새 내용 .md")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_edit)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_editor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/cli.py tests/test_editor.py
git commit -m "feat: edit 명령 — start/asks/apply/watch/stop"
```

---

### Task 7: 화면 (page.html)

**Files:**
- Modify: `hwpxkit/editor/page.html`
- Test: `tests/test_editor.py` (정적 검사) + 앱 브라우저 창 수동 확인

**Interfaces:**
- Consumes: 서버 API (Task 5). 열쇠값은 `location.search`의 `k`를 읽어 모든 fetch에 `X-Key` 헤더로 붙인다.

- [ ] **Step 1: Write the failing test**

```python
def test_page_is_self_contained_and_uses_api():
    html = (Path(__file__).parents[1] / "hwpxkit" / "editor" / "page.html").read_text(encoding="utf-8")
    assert "http://" not in html.replace("http://127.0.0.1", "") and "https://" not in html
    for api in ("/api/doc", "/api/edit", "/api/ask", "/api/asks", "/api/undo", "/api/pages", "X-Key"):
        assert api in html, api
    for word in ("고치기", "부탁하기", "되돌리기", "쪽 모양 확인"):
        assert word in html, word
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_editor.py -q -k page_is`
Expected: FAIL — `AssertionError: /api/doc`

- [ ] **Step 3: Write the page**

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>한글 편집</title>
<style>
:root{--bg:#eef0f3;--paper:#fff;--ink:#1d1f23;--muted:#6b7078;--line:#d7dbe0;--accent:#2f6fde;--accent-bg:#e8f0fd;
--warn-bg:#fdf3dc;--warn:#7a5200;--ok-bg:#e3f4e8;--ok:#1d6b3a;--bad-bg:#fde6e6;--bad:#9b1c1c}
@media (prefers-color-scheme:dark){:root{--bg:#17191c;--paper:#22252a;--ink:#e8eaed;--muted:#a0a6ae;--line:#3a3f46;
--accent:#7aa7f5;--accent-bg:#1f2c44;--warn-bg:#3a2f12;--warn:#f1c76b;--ok-bg:#163222;--ok:#7fd49c;--bad-bg:#3d1b1b;--bad:#f3a0a0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 "맑은 고딕","Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 16px;
background:var(--paper);border-bottom:1px solid var(--line)}
header .name{font-weight:600;margin-right:auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:50vw}
header .meta{color:var(--muted);font-size:13px}
button{font:inherit;font-size:13px;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--paper);color:var(--ink);cursor:pointer}
button:hover{border-color:var(--accent)}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
#notice{display:none;margin:8px auto 0;max-width:820px;padding:8px 12px;border-radius:6px;background:var(--warn-bg);color:var(--warn);font-size:13px}
main{max-width:820px;margin:16px auto 64px;padding:56px 64px;background:var(--paper);border:1px solid var(--line);border-radius:4px;min-height:80vh}
@media (max-width:700px){main{padding:24px 16px;margin:8px}}
.b{position:relative;border-radius:4px;padding:1px 4px;margin:0 -4px;cursor:pointer;white-space:pre-wrap;word-break:keep-all}
.b:hover{background:var(--accent-bg)}.b.sel{outline:2px solid var(--accent)}.b.blank{min-height:1.2em}
.b.h1,.b.h2{margin-top:.6em}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:.92em}td{border:1px solid var(--muted);padding:3px 6px;vertical-align:top;white-space:pre-wrap;cursor:pointer}
td:hover{background:var(--accent-bg)}.obj{color:var(--muted);font-style:italic}
.tools{display:flex;gap:6px;margin:4px 0 6px}
textarea{width:100%;font:inherit;padding:6px;border:1px solid var(--accent);border-radius:6px;background:var(--paper);color:var(--ink)}
.err{color:var(--bad);font-size:13px}
.ask{display:inline-block;font-size:12px;padding:0 6px;border-radius:4px;margin-left:4px}
.ask.pending{background:var(--warn-bg);color:var(--warn)}.ask.done{background:var(--ok-bg);color:var(--ok)}
.ask.stale,.ask.error{background:var(--bad-bg);color:var(--bad)}
#pages{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10;overflow:auto;padding:24px}
#pages .box{max-width:900px;margin:0 auto;background:var(--paper);border-radius:8px;padding:12px}
#pages img{width:100%;border:1px solid var(--line);margin:8px 0}
</style>
</head>
<body>
<header>
  <span class="name" id="name">불러오는 중…</span>
  <span class="meta" id="meta"></span>
  <button id="undo">되돌리기</button>
  <button id="pagesBtn">쪽 모양 확인</button>
</header>
<div id="notice"></div>
<main id="doc"></main>
<div id="pages"><div class="box"><div class="tools"><b style="margin-right:auto">실제 쪽 모양 (한글이 그림)</b><button id="pagesClose">닫기</button></div><div id="pagesBody"></div></div></div>
<script>
const KEY = new URLSearchParams(location.search).get("k") || "";
const H = {"X-Key": encodeURIComponent(KEY), "Content-Type": "application/json"};
let state = {version: 0, blocks: [], asks: []}, sel = null, editing = false;

async function api(method, path, body) {
  const r = await fetch(path, {method, headers: H, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.error || "오류가 났어요."); e.status = r.status; throw e; }
  return data;
}
function notice(text) { const n = document.getElementById("notice"); n.textContent = text; n.style.display = text ? "block" : "none"; }
function esc(s) { return s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

async function load(force) {
  const d = await api("GET", "/api/doc");
  if (!force && d.version === state.version) return;
  const a = await api("GET", "/api/asks");
  if (d.external_change) notice("한글 등에서 바뀐 내용을 불러왔어요.");
  if (d.sections > 1) notice("구역이 여러 개인 문서예요. 첫 구역만 보여 드려요.");
  state = {version: d.version, blocks: d.blocks, asks: a.asks};
  document.getElementById("name").textContent = d.name;
  const pending = a.asks.filter(x => x.status === "pending").length;
  document.getElementById("meta").textContent = `판 ${d.version}` + (pending ? ` · 대기 부탁 ${pending}개` : "");
  if (!editing) render();
}

function askBadges(i) {
  return state.asks.filter(a => a.start <= i && i < a.end && a.start === i).map(a => {
    const label = {pending: "부탁 대기 중", done: "반영됨", stale: "다시 확인 필요", error: "반영 못 함"}[a.status];
    return `<span class="ask ${a.status}" title="${esc(a.text + (a.message ? " — " + a.message : ""))}">${label}: ${esc(a.text.slice(0, 20))}</span>`;
  }).join("");
}

function render() {
  const root = document.getElementById("doc");
  root.innerHTML = "";
  for (const b of state.blocks) {
    if (b.kind === "table") {
      const t = document.createElement("table");
      for (const row of b.rows) {
        const tr = t.insertRow();
        for (const c of row) {
          const td = tr.insertCell(); td.textContent = c.text; td.rowSpan = c.rs; td.colSpan = c.cs;
          td.onclick = ev => { ev.stopPropagation(); editCell(td, b.i, c); };
        }
      }
      const wrap = document.createElement("div"); wrap.className = "b"; wrap.dataset.i = b.i;
      wrap.onclick = ev => pick(ev, wrap, b);
      wrap.appendChild(t); wrap.insertAdjacentHTML("beforeend", askBadges(b.i)); root.appendChild(wrap);
      continue;
    }
    const el = document.createElement("div");
    el.className = "b " + (b.role || "") + (b.kind === "para" && !b.text.trim() ? " blank" : "");
    el.dataset.i = b.i;
    if (b.kind === "object") { el.innerHTML = `<span class="obj">${esc(b.text)}</span>`; }
    else {
      el.style.fontSize = Math.max(11, Math.min(28, b.size * 1.05)) + "px";
      el.style.fontWeight = b.bold ? 700 : 400;
      el.style.paddingLeft = (4 + Math.min(120, b.indent / 4)) + "px";
      el.textContent = b.text;
    }
    el.insertAdjacentHTML("beforeend", askBadges(b.i));
    el.onclick = ev => pick(ev, el, b);
    root.appendChild(el);
  }
}

function clearTools() { document.querySelectorAll(".tools.inline").forEach(t => t.remove()); document.querySelectorAll(".b.sel").forEach(e => e.classList.remove("sel")); }

function pick(ev, el, b) {
  if (editing) return;
  if (ev.shiftKey && sel) { sel = {start: Math.min(sel.start, b.i), end: Math.max(sel.end, b.i + 1)}; }
  else sel = {start: b.i, end: b.i + 1};
  clearTools();
  document.querySelectorAll(".b").forEach(e => { const i = +e.dataset.i; if (sel.start <= i && i < sel.end) e.classList.add("sel"); });
  const tools = document.createElement("div"); tools.className = "tools inline";
  const n = sel.end - sel.start;
  if (n === 1 && b.kind === "para") tools.appendChild(btn("고치기", () => editPara(el, b)));
  tools.appendChild(btn(n > 1 ? `부탁하기 (${n}문단)` : "부탁하기", () => askBox(tools)));
  tools.appendChild(btn("닫기", () => { sel = null; clearTools(); }));
  document.querySelector(`.b[data-i="${sel.end - 1}"]`).after(tools);
}

function btn(label, fn, primary) { const x = document.createElement("button"); x.textContent = label; if (primary) x.className = "primary"; x.onclick = e => { e.stopPropagation(); fn(); }; return x; }

function editor(initial, onSave, place) {
  editing = true;
  const box = document.createElement("div"); box.className = "tools inline"; box.style.flexDirection = "column";
  const ta = document.createElement("textarea"); ta.value = initial; ta.rows = Math.max(2, Math.ceil(initial.length / 45));
  const err = document.createElement("div"); err.className = "err";
  const row = document.createElement("div"); row.className = "tools";
  const done = () => { editing = false; box.remove(); load(true); };
  row.appendChild(btn("저장", async () => {
    try { await onSave(ta.value); done(); }
    catch (e) { err.textContent = e.message; if (e.status === 409) { editing = false; await load(true); editing = true; } }
  }, true));
  row.appendChild(btn("취소", done));
  box.append(ta, err, row); place(box); ta.focus();
  ta.onclick = e => e.stopPropagation();
  return ta;
}

function editPara(el, b) {
  clearTools();
  if (b.mixed && !confirm("이 문단에는 굵게 등 여러 글자 모양이 섞여 있어요. 고치면 첫 글자 모양 하나로 합쳐져요. 계속할까요?")) return;
  editor(b.text, text => api("POST", "/api/edit", {version: state.version, i: b.i, text}), box => el.after(box));
}

function editCell(td, i, c) {
  if (editing) return;
  clearTools();
  editor(c.text, text => api("POST", "/api/edit", {version: state.version, i, r: c.r, c: c.c, text}),
         box => td.closest(".b").after(box));
}

function askBox(tools) {
  const range = {...sel};
  tools.remove();
  editor("", text => {
    if (!text.trim()) { const e = new Error("부탁 내용을 적어 주세요."); throw e; }
    return api("POST", "/api/ask", {version: state.version, start: range.start, end: range.end, text});
  }, box => document.querySelector(`.b[data-i="${range.end - 1}"]`).after(box));
}

document.getElementById("undo").onclick = async () => { try { await api("POST", "/api/undo", {}); notice(""); await load(true); } catch (e) { notice(e.message); } };
document.getElementById("pagesBtn").onclick = async () => {
  const p = document.getElementById("pages"), body = document.getElementById("pagesBody");
  p.style.display = "block"; body.textContent = "한글로 쪽 그림을 만드는 중이에요… (몇 초 걸려요)";
  try { const r = await api("POST", "/api/pages", {}); body.innerHTML = "";
    for (const src of r.pages) { const img = new Image(); img.alt = "쪽 그림";
      fetch(src, {headers: H}).then(x => x.blob()).then(bl => img.src = URL.createObjectURL(bl)); body.appendChild(img); } }
  catch (e) { body.textContent = e.message; }
};
document.getElementById("pagesClose").onclick = () => document.getElementById("pages").style.display = "none";
document.addEventListener("keydown", e => { if (e.key === "Escape" && !editing) { sel = null; clearTools(); } });

load(true).catch(e => notice(e.message));
setInterval(() => { if (!editing) load(false).catch(() => notice("편집 화면 서버에 연결할 수 없어요. 'edit start'로 다시 켜 주세요.")); }, 2000);
</script>
</body>
</html>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_editor.py -q`
Expected: PASS

- [ ] **Step 5: 앱 브라우저 창 수동 확인**

1. 시험 문서 만들기: `python -c "..."` 대신 `tests/fixtures/blank.hwpx`에 프리셋으로 짧은 보고서를 렌더: `python hwpx.py render <프리셋 gov-brief 경로> <짧은.md> %TEMP%\edit-check\보고서.hwpx` (프리셋 경로는 `python hwpx.py presets --json`).
2. `python hwpx.py edit start %TEMP%\edit-check\보고서.hwpx` → 주소를 `.claude/launch.json` 없이 `mcp__Claude_Browser__preview_start(url=...)`로 연다.
3. 확인: 문단 누르기 → [고치기] → 저장 → 판 번호 오름; 표 칸 고치기; Shift로 두 문단 골라 [부탁하기] → "부탁 대기 중" 표시; `edit asks` → `edit apply` → 화면이 "반영됨"으로 바뀜; [되돌리기]; [쪽 모양 확인](한글 있을 때 그림). 폭 375px(`resize_window mobile`)에서 가로 스크롤 없음.
4. `edit stop`. 결과(스크린샷 요지)를 ledger에 한 줄로 남긴다.

- [ ] **Step 6: Commit**

```bash
git add hwpxkit/editor/page.html tests/test_editor.py
git commit -m "feat: edit 화면 — 문서처럼 보며 고치기·부탁하기·되돌리기·쪽 모양 확인"
```

---

### Task 8: 한글 쪽 그림 시험, 스킬 안내, 0.3.0

**Files:**
- Create: `skills/hwp-helper/reference/editor.md`
- Modify: `skills/hwp-helper/SKILL.md`, `tests/test_plugin_files.py`(허용 옵션 변경 없음 — `--json`만 씀), `.claude-plugin/plugin.json`(0.3.0), `.claude-plugin/marketplace.json`(버전이 있으면 0.3.0), `README.md`(기능 표에 한 줄)
- Test: `tests/test_editor.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.hangul
def test_server_pages_with_hangul(server):
    srv, _ = server
    st, r = call(srv, "POST", "/api/pages", {})
    assert st == 200 and r["pages"] and r["pages"][0].startswith("/pages/")
    st, png = call(srv, "GET", r["pages"][0])
    assert st == 200 and png[:4] == b"\x89PNG"


def test_skill_documents_edit():
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "editor.md").read_text(encoding="utf-8")
    for cmd in ("edit start", "edit watch", "edit asks", "edit apply", "edit stop"):
        assert cmd in text, cmd
    assert "reference/editor.md" in (root / "SKILL.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_editor.py -q -k "skill_documents or pages_with"`
Expected: `test_skill_documents_edit` FAIL (`FileNotFoundError`); `test_server_pages_with_hangul`은 한글 있는 PC에서 PASS일 수 있다 — 이미 Task 5가 구현했으므로 이 시험은 회귀 고정용(Ruling 없이 기록만).

- [ ] **Step 3: Write docs**

`skills/hwp-helper/reference/editor.md`:

```markdown
# 앱 안 편집 화면 (edit)

사용자가 "앱에서 보면서 고칠래", "화면으로 띄워 줘"라고 하면 쓴다. 원본은 그대로 두고 `<이름>_수정.hwpx` 사본을 고친다.

| 단계 | 하는 일 |
|---|---|
| 1 | `python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" edit start <원본.hwpx>` → 출력된 `편집 화면:` 주소를 앱 브라우저 창으로 연다(`preview_start`의 url) |
| 2 | 부탁 알림 받기: Monitor로 `python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" edit watch <원본.hwpx>` (한 줄 = 새 부탁 하나) |
| 3 | 새 부탁이 오면 `edit asks <원본.hwpx> --json` → 그 범위 마크다운과 부탁 글을 읽고 새 내용을 `.md`로 쓴다(보고서 마크다운 규칙 그대로) |
| 4 | `edit apply <원본.hwpx> <부탁번호> <새내용.md>` → 화면이 저절로 새로 고쳐짐 |
| 5 | 끝나면 `edit stop <원본.hwpx>`, 사용자에게 사본 경로를 알린다 |

- 사용자가 화면에서 직접 고친 글은 서버가 바로 사본에 저장한다. Claude가 따로 할 일이 없다.
- 부탁 반영에서 원문에 없는 수치·사실·고유명사를 넣지 않는다. 필요하면 `( )`로 비우고 대화에서 알린다.
- `edit apply`가 "다시 확인이 필요해요"를 내면(그 사이 사용자가 그 부분을 고침) 대화에서 어떻게 할지 묻는다.
- 대화가 없을 때 쌓인 부탁은 사용자가 "부탁 반영해줘"라고 하면 `edit asks`로 모아 차례로 반영한다.
- 사본을 한글에서 열어 두면 화면에서 저장이 막힌다. "한글에서 사본을 닫아 주세요"라고 안내한다.
```

`SKILL.md`의 live 안내(§6-1) 아래에 한 단락:

```markdown
사용자가 "앱에서 보면서 고칠래", "화면에 띄워서 고치자"처럼 Claude 앱 안에서 문서를 보며 고치려 하면 `edit` 명령을 쓴다. 원본은 그대로 두고 사본을 고친다. 절차는 `reference/editor.md`.
```

README 기능 표에 `| 앱 안에서 보며 고치기 | Claude 앱 브라우저 창에서 문서처럼 보며 직접 고치거나 부탁을 남기면 서식 그대로 반영 (사본에만) |`. plugin.json `"version": "0.3.0"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -m "not hangul"` 그리고 `python -m pytest -q tests/test_editor.py -m hangul`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add skills/hwp-helper tests/test_editor.py .claude-plugin README.md
git commit -m "feat: edit 스킬 안내, 쪽 그림 시험, 0.3.0"
```

---

## Self-Review 결과

- 스펙 대응: 3장 흐름 → Task 6·7·8, 4장 구성·API → Task 1·5·6, 5장 규칙(문단·칸 고치기, 판 번호, 이력, 외부 변경, 보안·수명, 쪽 모양) → Task 2·3·4·5, 6장 화면 → Task 7, 7장 오류 표 → Task 2·4·5·6(.hwp 원본은 `EditDoc.__init__`의 `bridge.convert`), 9장 시험 → 각 Task.
- 스펙에 없는 추가: `edit watch`(스펙 3장 "Monitor로 지켜본다"를 위한 명령), `/api/stop`(CLI `edit stop`용). 스펙 범위 안의 수단이다.
- 포트 사용 중: `port=0`(빈 포트를 운영체제가 고름)으로 해결.
