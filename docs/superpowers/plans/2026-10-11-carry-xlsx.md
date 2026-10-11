# 매달 이어받기(carry)와 엑셀·CSV 표(table-from) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지난달 월간보고서로 이번 달 `fill` 지시문 초안과 확인할 것 목록을 만드는 `carry`, 엑셀·CSV를 서식 맞춘 보고서 마크다운 표로 바꾸는 `table-from`, 그리고 마크다운 표의 `---:` 정렬을 만든다.

**Architecture:** `hwpxkit/carry.py`는 `review`의 기간·날짜 판정과 `form`의 칸 목록·주소를 써서 지시문 글을 만든다(문서는 바꾸지 않음). `hwpxkit/sheet.py`는 zipfile+lxml로 xlsx를, `csv`로 CSV를 읽어 마크다운 표를 만든다. `mdparse`가 구분 줄의 정렬을 읽고 렌더러가 칸 문단 모양 정렬을 바꾼다.

**Tech Stack:** Python 3.10+, lxml, 표준 라이브러리(zipfile, csv, datetime).

**Spec:** docs/superpowers/specs/2026-10-11-carry-xlsx-design.md

## Global Constraints

- 새 의존성 없음(openpyxl 쓰지 않음).
- `carry`는 지난달 파일을 바꾸지 않는다. 실제 변경은 `fill`이 한다.
- 숫자를 지어내지 않는다. 누적·진행률·새 계획·보고일은 확인할 것으로만 알린다.
- 사용자에게 보이는 글은 한국어 존댓말, 쉬운 말.
- 사용자 실제 문서(private/)는 시험·공개 파일에 쓰지 않는다.
- 구분 줄에 콜론이 없는 기존 표는 렌더 결과가 전과 같아야 한다.

## Review Focus

1. 따로 떨어진 "9월"이나 "19월", 다른 해의 같은 달 — 바꾸기 줄을 만들지 않아야 한다 (Task 4 `test_isolated_month_not_replaced`).
2. 계획·실적 칸이 병합되어 여러 행에 걸침, 또는 칸 안에 표 — 옮기지 않아야 한다 (Task 5 `test_merged_or_object_cells_skipped`).
3. 엑셀 범위가 병합 영역의 일부만 잘라냄 — 마크다운 병합 규칙(첫 행 `^^`, 첫 열 `<<` 금지)을 어기지 않아야 한다 (Task 2 `test_range_cuts_merge`).
4. CSV 칸 안의 `|`와 줄바꿈 — 표가 깨지지 않아야 한다 (Task 2 `test_pipe_and_newline_escaped`).
5. 수식 결과가 저장되지 않은 xlsx — 빈 칸 + 경고 (Task 2 `test_formula_without_value_warns`).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `hwpxkit/mdparse.py`, `hwpxkit/render.py` | 표 열 정렬(`aligns`) 읽기·적용 |
| `hwpxkit/sheet.py` (새로) | xlsx·CSV 읽기, 숫자 서식, 마크다운 표 |
| `hwpxkit/carry.py` (새로) | 기간 찾기, 바꾸기 줄, 보고일 제안, 계획 → 실적, 확인할 것 |
| `hwpxkit/cli.py` | `table-from`, `carry` 명령 |
| `skills/hwp-helper/reference/monthly.md`, `SKILL.md`, `reference/form.md`, `reference/markdown.md`, `README.md`, `.claude-plugin/plugin.json`, `tests/test_plugin_files.py` | 안내, 0.5.0 |
| `tests/test_sheet.py`, `tests/test_carry.py` (새로) | 시험 |

---

### Task 1: 마크다운 표 열 정렬 (`---:`)

**Files:**
- Modify: `hwpxkit/mdparse.py`, `hwpxkit/render.py`
- Test: `tests/test_sheet.py`

**Interfaces:**
- Produces: `mdparse.Table.aligns: list[str]` (열마다 "left"|"center"|"right"|"", 구분 줄이 없으면 빈 목록). 렌더러가 "right"·"center" 열의 머리 아닌 칸 문단에 정렬 바꾼 문단 모양을 쓴다.

- [ ] **Step 1: Write the failing test**

```python
"""엑셀·CSV를 보고서 마크다운 표로 (table-from), 표 열 정렬."""
import zipfile
from pathlib import Path

import pytest

from helpers import LONG, SECTION, append_to_body, para
from hwpxkit.header import Header
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import render_into
from hwpxkit.samples import infer


def test_parse_aligns():
    from hwpxkit.mdparse import parse
    t = parse("| 가 | 나 | 다 |\n|:---|:---:|---:|\n| 1 | 2 | 3 |\n")[0]
    assert t.aligns == ["left", "center", "right"]
    assert parse("| 가 |\n|---|\n| 1 |\n")[0].aligns == [""]


def _align_of(pkg, p):
    return Header(pkg).get("paraPr", p.get("paraPrIDRef")).find(q("hh:align")).get("horizontal")


def test_render_right_aligned_column(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), "| 구분 | 금액 |\n|---|---:|\n| 가 | 1,200 |\n| 나 | 30 |\n")
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    rows = tbl.findall(q("hp:tr"))
    body = [tc for tr in rows[1:] for tc in tr.findall(q("hp:tc"))]
    amount = [tc for tc in body if tc.find(q("hp:cellAddr")).get("colAddr") == "1"]
    label = [tc for tc in body if tc.find(q("hp:cellAddr")).get("colAddr") == "0"]
    assert all(_align_of(pkg, tc.find(q("hp:subList")).find(q("hp:p"))) == "RIGHT" for tc in amount)
    assert all(_align_of(pkg, tc.find(q("hp:subList")).find(q("hp:p"))) != "RIGHT" for tc in label)
    head = rows[0].findall(q("hp:tc"))[1].find(q("hp:subList")).find(q("hp:p"))
    assert _align_of(pkg, head) != "RIGHT"


def test_no_colon_table_unchanged(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), "| 구분 | 금액 |\n|---|---|\n| 가 | 1 |\n")
    tbl = next(pkg.xml(SECTION).iter(q("hp:tbl")))
    assert all(_align_of(pkg, p) != "RIGHT" for p in tbl.iter(q("hp:p")))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sheet.py -q`
Expected: FAIL — `AttributeError: 'Table' object has no attribute 'aligns'`

- [ ] **Step 3: Write implementation**

`hwpxkit/mdparse.py`:
- `Table` dataclass에 `aligns: list[str] = field(default_factory=list)`을 `lineno` 앞에 더한다.
- `parse()`의 표 읽기에서 구분 줄을 버리지 말고 정렬을 읽는다.

```python
        if line.startswith("|"):
            rows, aligns = [], []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                if _TABLE_SEP.match(row):
                    aligns = [_align(c) for c in _cells(row)]
                else:
                    rows.append(_cells(row))
                i += 1
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            aligns = (aligns + [""] * width)[:width] if aligns else []
            text, attrs, _ = caption or ("", {}, 0)
            caption = None
            blocks.append(Table(rows, text, attrs.get("label"), attrs.get("widths"), aligns=aligns, lineno=lineno))
            continue
```

그리고 모듈 함수:

```python
def _align(sep: str) -> str:
    """구분 줄 한 칸(':---', ':---:', '---:')의 정렬."""
    s = sep.strip()
    left, right = s.startswith(":"), s.endswith(":")
    return "center" if left and right else "right" if right else "left" if left else ""
```

`hwpxkit/render.py`:
- `_table_para`의 칸 채우기를 `self._fill_cell(tc, rows[r][c], b.aligns[c] if r > 0 and b.aligns else "")`로 바꾼다.
- `_fill_cell`에 정렬 인자를 받는다.

```python
    def _fill_cell(self, tc: etree._Element, text: str, align: str = "") -> None:
        sub = tc.find(q("hp:subList"))
        tmpl = sub.find(q("hp:p"))
        char = _cell_char(tmpl)
        attrs = dict(tmpl.attrib)
        if align in ("right", "center"):
            attrs["paraPrIDRef"] = self._aligned(attrs["paraPrIDRef"], align.upper())
        for old in list(sub):
            sub.remove(old)
        for line in text.split("<br>"):
            p = etree.SubElement(sub, q("hp:p"), attrs)
            self._fill_runs(p, char, parse_inline(line.strip()))

    def _aligned(self, para_pr: str, horizontal: str) -> str:
        """정렬만 바꾼 문단 모양 (같은 조합은 다시 씀)."""
        key = (para_pr, horizontal)
        if key not in self._align_cache:
            self._align_cache[key] = self.h.derive(
                "paraPr", para_pr, lambda e: e.find(q("hh:align")).set("horizontal", horizontal))
        return self._align_cache[key]
```

- `Renderer.__init__`에 `self._align_cache: dict = {}`를 더한다(다른 캐시 옆).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sheet.py -q` 그리고 `python -m pytest -q -m "not hangul"`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/mdparse.py hwpxkit/render.py tests/test_sheet.py
git commit -m "feat: 마크다운 표 열 정렬(---:, :---:)"
```

---

### Task 2: 엑셀·CSV 읽기와 마크다운 표 (`sheet.py`)

**Files:**
- Create: `hwpxkit/sheet.py`
- Test: `tests/test_sheet.py`

**Interfaces:**
- Produces:
  - `class SheetError(ValueError)`
  - `table_from(path: Path, *, sheet: str | None = None, rng: str | None = None, header: int = 1, caption: str | None = None) -> tuple[str, list[str]]` — (마크다운, 경고)

- [ ] **Step 1: Write the failing tests**

```python
M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def make_xlsx(path, sheets, shared=(), numfmts=(), xfs=(0,)):
    """시험용 최소 xlsx. sheets = {이름: '<row>…</row> 문자열', …} (병합은 이름: (rows, ['A1:B1']))."""
    z = zipfile.ZipFile(path, "w")
    names = list(sheets)
    z.writestr("xl/workbook.xml", f'<workbook xmlns="{M}" xmlns:r="{R}"><sheets>' + "".join(
        f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + "</sheets></workbook>")
    z.writestr("xl/_rels/workbook.xml.rels",
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
                   f'<Relationship Id="rId{i + 1}" Type="x" Target="worksheets/sheet{i + 1}.xml"/>'
                   for i in range(len(names))) + "</Relationships>")
    z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{M}">' + "".join(
        f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
    z.writestr("xl/styles.xml", f'<styleSheet xmlns="{M}"><numFmts>' + "".join(
        f'<numFmt numFmtId="{i}" formatCode="{c}"/>' for i, c in numfmts) + "</numFmts><cellXfs>" + "".join(
        f'<xf numFmtId="{n}"/>' for n in xfs) + "</cellXfs></styleSheet>")
    for i, n in enumerate(names):
        body = sheets[n]
        rows, merges = (body if isinstance(body, tuple) else (body, []))
        mc = (f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges)
              + "</mergeCells>") if merges else ""
        z.writestr(f"xl/worksheets/sheet{i + 1}.xml", f'<worksheet xmlns="{M}"><sheetData>{rows}</sheetData>{mc}</worksheet>')
    z.close()
    return path


def row(r, *cells):
    return f'<row r="{r}">' + "".join(cells) + "</row>"


def s(ref, idx, style=0):
    return f'<c r="{ref}" t="s" s="{style}"><v>{idx}</v></c>'


def n(ref, value, style=0, formula=None):
    f = f"<f>{formula}</f>" if formula else ""
    v = f"<v>{value}</v>" if value is not None else ""
    return f'<c r="{ref}" s="{style}">{f}{v}</c>'


def test_xlsx_numbers_formats_and_align(tmp_path):
    from hwpxkit.sheet import table_from
    # 스타일 0 일반, 1 #,##0, 2 0.00%, 3 날짜(14), 4 사용자 '0.0'
    p = make_xlsx(tmp_path / "a.xlsx", {"실적": row(1, s("A1", 0), s("B1", 1), s("C1", 2), s("D1", 3), s("E1", 4))
                                        + row(2, s("A2", 5), n("B2", 1234567, 1), n("C2", 0.4567, 2), n("D2", 46295, 3), n("E2", 3.14159, 4))
                                        + row(3, s("A3", 6), n("B3", -89, 1), n("C3", 1, 2), n("D3", 46296, 3), n("E3", 12, 4))},
                  shared=["구분", "금액", "비율", "날짜", "값", "가", "나"], numfmts=[(164, "0.0")], xfs=(0, 3, 10, 14, 164))
    md, warnings = table_from(p, caption="실적 요약")
    lines = md.strip().splitlines()
    assert lines[0] == "표: 실적 요약"
    assert lines[1] == "| 구분 | 금액 | 비율 | 날짜 | 값 |"
    assert lines[2] == "|---|---:|---:|---|---:|"
    assert lines[3] == "| 가 | 1,234,567 | 45.67% | 2026. 9. 30. | 3.1 |"
    assert lines[4] == "| 나 | -89 | 100.00% | 2026. 10. 1. | 12.0 |"
    assert warnings == []


def test_general_numbers_use_column_decimals(tmp_path):
    from hwpxkit.sheet import table_from
    p = make_xlsx(tmp_path / "g.xlsx", {"S": row(1, s("A1", 0)) + row(2, n("A2", 1500)) + row(3, n("A3", 2.25))},
                  shared=["값"])
    md, _ = table_from(p)
    assert md.strip().splitlines()[2:] == ["| 1,500.00 |", "| 2.25 |"]


def test_merges_and_sheet_choice(tmp_path):
    from hwpxkit.sheet import SheetError, table_from
    rows = (row(1, s("A1", 0), s("B1", 1)) + row(2, s("A2", 2), n("B2", 1)) + row(3, n("B3", 2)),
            ["A2:A3"])
    p = make_xlsx(tmp_path / "m.xlsx", {"첫": row(1, s("A1", 0)), "둘": rows}, shared=["항목", "값", "묶음"])
    md, _ = table_from(p, sheet="둘")
    assert md.strip().splitlines()[2:] == ["| 묶음 | 1 |", "| ^^ | 2 |"]
    with pytest.raises(SheetError, match="첫, 둘"):
        table_from(p, sheet="셋")


def test_range_cuts_merge(tmp_path):
    from hwpxkit.sheet import table_from
    rows = (row(1, s("A1", 0), s("B1", 1)) + row(2, s("A2", 2), n("B2", 1)) + row(3, n("B3", 2)), ["A1:A3"])
    p = make_xlsx(tmp_path / "c.xlsx", {"S": rows}, shared=["항목", "값", "x"])
    md, warnings = table_from(p, rng="A2:B3")
    lines = md.strip().splitlines()
    assert "^^" not in lines[0] and lines[0].startswith("| ")
    assert warnings and "병합" in warnings[0]


def test_formula_without_value_warns(tmp_path):
    from hwpxkit.sheet import table_from
    p = make_xlsx(tmp_path / "f.xlsx", {"S": row(1, s("A1", 0)) + row(2, n("A2", None, formula="SUM(1,2)"))},
                  shared=["합"])
    md, warnings = table_from(p)
    assert md.strip().splitlines()[2] == "|  |"
    assert any("수식" in w for w in warnings)


def test_not_xlsx_and_old_xls(tmp_path):
    from hwpxkit.sheet import SheetError, table_from
    bad = tmp_path / "x.xlsx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(SheetError, match=".xlsx로 저장"):
        table_from(bad)
    old = tmp_path / "y.xls"
    old.write_bytes(b"x")
    with pytest.raises(SheetError, match=".xlsx로 저장"):
        table_from(old)


def test_csv_encodings_and_tsv(tmp_path):
    from hwpxkit.sheet import table_from
    (tmp_path / "u.csv").write_text("구분,금액\n가,1200\n나,30.5\n", encoding="utf-8-sig")
    (tmp_path / "k.csv").write_bytes("구분,금액\n가,1200\n".encode("cp949"))
    (tmp_path / "t.tsv").write_text("구분\t금액\n가\t7\n", encoding="utf-8")
    md, _ = table_from(tmp_path / "u.csv")
    assert md.strip().splitlines() == ["| 구분 | 금액 |", "|---|---:|", "| 가 | 1,200.0 |", "| 나 | 30.5 |"]
    assert table_from(tmp_path / "k.csv")[0].strip().splitlines()[2] == "| 가 | 1,200 |"
    assert table_from(tmp_path / "t.tsv")[0].strip().splitlines()[2] == "| 가 | 7 |"


def test_pipe_and_newline_escaped(tmp_path):
    from hwpxkit.mdparse import parse
    from hwpxkit.sheet import table_from
    (tmp_path / "p.csv").write_text('구분,설명\n가,"A|B\n둘째 줄"\n', encoding="utf-8")
    md, _ = table_from(tmp_path / "p.csv")
    t = parse(md)[0]
    assert t.rows[1] == ["가", "A｜B 둘째 줄"]


def test_wide_table_warns(tmp_path):
    from hwpxkit.sheet import table_from
    (tmp_path / "w.csv").write_text(",".join(f"c{i}" for i in range(13)) + "\n" + ",".join("1" * 13) + "\n", encoding="utf-8")
    assert any("열이 13개" in w for w in table_from(tmp_path / "w.csv")[1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sheet.py -q -k "xlsx or csv or merge or formula or wide or pipe or general or range"`
Expected: FAIL — `ModuleNotFoundError: No module named 'hwpxkit.sheet'`

- [ ] **Step 3: Write implementation**

```python
"""엑셀(.xlsx)·CSV를 보고서 마크다운 표로. 표준 라이브러리와 lxml만 쓴다 (설계 4장)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_BUILTIN = {0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%"}
_DATE_IDS = set(range(14, 23)) | {45, 46, 47}
_NUMBER_TEXT = re.compile(r"^[-+]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
_NUMERIC_LOOK = re.compile(r"^[-+]?[\d,]*\.?\d+\s*%?$")
_SAVE_AS = "엑셀에서 .xlsx로 저장해 주세요."
MAX_COLS = 12


class SheetError(ValueError):
    """엑셀·CSV 읽기 오류. 메시지는 사용자용 한국어."""


@dataclass
class Value:
    kind: str  # "text" | "number" | "empty"
    text: str = ""
    number: float = 0.0
    fmt: str = "General"  # 서식 코드, 날짜는 "date"


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _ref(ref: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", ref.strip())
    if not m:
        raise SheetError(f"칸 주소를 읽지 못했어요: {ref} (예: B2)")
    return int(m.group(2)) - 1, _col(m.group(1))


def _range(text: str) -> tuple[int, int, int, int]:
    a, _, b = text.partition(":")
    (r1, c1), (r2, c2) = _ref(a), _ref(b or a)
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def _xml(z: zipfile.ZipFile, name: str):
    try:
        return etree.fromstring(z.read(name))
    except KeyError:
        return None


def _read_xlsx(path: Path, sheet: str | None):
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise SheetError(f"엑셀 파일을 열지 못했어요(암호가 걸렸거나 옛 형식일 수 있어요). {_SAVE_AS}") from None
    warnings: list[str] = []
    with z:
        wb = _xml(z, "xl/workbook.xml")
        rels = _xml(z, "xl/_rels/workbook.xml.rels")
        if wb is None or rels is None:
            raise SheetError(f"엑셀 파일 구조를 읽지 못했어요. {_SAVE_AS}")
        sheets = [(s.get("name"), s.get(f"{_R}id")) for s in wb.iter(f"{_M}sheet")]
        names = [n for n, _ in sheets]
        if sheet is None:
            sheet = names[0]
        if sheet not in names:
            raise SheetError(f"'{sheet}' 시트가 없어요. 있는 시트: {', '.join(names)}")
        rid = dict(sheets)[sheet]
        target = next(r.get("Target") for r in rels.iter(f"{_PR}Relationship") if r.get("Id") == rid)
        part = target.lstrip("/") if target.startswith("/") else "xl/" + target
        shared = []
        sst = _xml(z, "xl/sharedStrings.xml")
        if sst is not None:
            for si in sst.iter(f"{_M}si"):
                shared.append("".join(t.text or "" for t in si.findall(f"{_M}t") + si.findall(f"{_M}r/{_M}t")))
        fmts = dict(_BUILTIN)
        xf_fmt: list[int] = []
        styles = _xml(z, "xl/styles.xml")
        if styles is not None:
            for nf in styles.iter(f"{_M}numFmt"):
                fmts[int(nf.get("numFmtId"))] = nf.get("formatCode")
            cell_xfs = styles.find(f"{_M}cellXfs")
            if cell_xfs is not None:
                xf_fmt = [int(xf.get("numFmtId", "0")) for xf in cell_xfs.findall(f"{_M}xf")]
        ws = _xml(z, part)
    grid: dict[tuple[int, int], Value] = {}
    for c in ws.iter(f"{_M}c"):
        r, col = _ref(c.get("r"))
        t = c.get("t", "n")
        v = c.find(f"{_M}v")
        if t == "s" and v is not None:
            grid[(r, col)] = Value("text", shared[int(v.text)])
        elif t == "inlineStr":
            grid[(r, col)] = Value("text", "".join(c.find(f"{_M}is").itertext()))
        elif t in ("str", "e") and v is not None:
            grid[(r, col)] = Value("text", v.text or "")
        elif t == "b" and v is not None:
            grid[(r, col)] = Value("text", "참" if v.text == "1" else "거짓")
        elif v is not None and v.text:
            fid = xf_fmt[int(c.get("s", "0"))] if xf_fmt else 0
            code = "date" if fid in _DATE_IDS or _is_date(fmts.get(fid, "General")) else fmts.get(fid, "General")
            grid[(r, col)] = Value("number", number=float(v.text), fmt=code)
        elif c.find(f"{_M}f") is not None:
            warnings.append(f"{c.get('r')} 칸의 수식 결과가 저장되어 있지 않아 비워 두었어요. 엑셀에서 열어 저장한 뒤 다시 해 주세요.")
    merges = [_range(m.get("ref")) for m in ws.iter(f"{_M}mergeCell")]
    return grid, merges, warnings


def _is_date(code: str) -> bool:
    plain = re.sub(r'"[^"]*"|\[[^\]]*\]', "", code.lower())
    return bool(re.search(r"y|d|h:|m{3,}", plain)) or ("m" in plain and ("y" in plain or "d" in plain))


def _read_csv(path: Path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SheetError("CSV 글자 인코딩을 알아보지 못했어요. UTF-8로 저장해 주세요.")
    if path.suffix.lower() == ".tsv":
        delim = "\t"
    else:
        try:
            delim = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
        except csv.Error:
            delim = ","
    grid: dict[tuple[int, int], Value] = {}
    for r, cells in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
        for c, cell in enumerate(cells):
            cell = cell.strip()
            if _NUMBER_TEXT.match(cell):
                grid[(r, c)] = Value("number", number=float(cell.replace(",", "")))
            elif cell:
                grid[(r, c)] = Value("text", cell)
    return grid, [], []


def _decimals(code: str) -> int:
    first = code.split(";")[0]
    m = re.search(r"\.([0#]+)", first)
    return len(m.group(1)) if m else 0


def _plain_decimals(x: float) -> int:
    s = f"{x:.10g}"
    return min(4, len(s.split(".")[1])) if "." in s and "e" not in s else 0


def _show(v: Value, col_dec: int) -> str:
    if v.kind != "number":
        return v.text
    if v.fmt == "date":
        d = dt.date(1899, 12, 30) + dt.timedelta(days=int(v.number))
        return f"{d.year}. {d.month}. {d.day}."
    if "%" in v.fmt:
        return f"{v.number * 100:,.{_decimals(v.fmt)}f}%"
    if v.fmt == "General":
        return f"{v.number:,.{col_dec}f}"
    dec = _decimals(v.fmt)
    return f"{v.number:,.{dec}f}" if "," in v.fmt else f"{v.number:.{dec}f}"


def _raw(v: Value) -> str:
    return v.text if v.kind != "number" else f"{v.number:.10g}"


def _cell_text(s: str) -> str:
    return s.replace("|", "｜").replace("\r\n", " ").replace("\n", " ").strip()


def table_from(path, *, sheet: str | None = None, rng: str | None = None, header: int = 1,
               caption: str | None = None) -> tuple[str, list[str]]:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".xls":
        raise SheetError(f"옛 엑셀 형식(.xls)은 읽지 못해요. {_SAVE_AS}")
    if ext in (".csv", ".tsv", ".txt"):
        grid, merges, warnings = _read_csv(path)
    else:
        grid, merges, warnings = _read_xlsx(path, sheet)
    keys = [k for k, v in grid.items() if v.kind != "empty" and (v.kind == "number" or v.text)]
    if rng:
        r1, c1, r2, c2 = _range(rng)
    elif keys:
        r1, c1 = min(k[0] for k in keys), min(k[1] for k in keys)
        r2, c2 = max(k[0] for k in keys), max(k[1] for k in keys)
    else:
        raise SheetError("읽을 값이 없어요. 범위나 시트를 확인해 주세요.")
    nr, nc = r2 - r1 + 1, c2 - c1 + 1
    cell = lambda r, c: grid.get((r1 + r, c1 + c), Value("empty"))  # noqa: E731
    marks: dict[tuple[int, int], str] = {}
    for mr1, mc1, mr2, mc2 in merges:
        if mr2 < r1 or mr1 > r2 or mc2 < c1 or mc1 > c2:
            continue
        if not (r1 <= mr1 and c1 <= mc1 and mr2 <= r2 and mc2 <= c2):
            warnings.append("범위가 병합 칸의 일부만 잘라서, 그 병합은 풀어서 넣었어요.")
            continue
        for r in range(mr1, mr2 + 1):
            for c in range(mc1, mc2 + 1):
                if (r, c) != (mr1, mc1):
                    marks[(r - r1, c - c1)] = "<<" if r == mr1 else "^^"
    col_dec, aligns = [], []
    for c in range(nc):
        body = [cell(r, c) for r in range(header, nr) if (r, c) not in marks]
        nums = [v for v in body if v.kind == "number"]
        col_dec.append(max((_plain_decimals(v.number) for v in nums if v.fmt == "General"), default=0))
        filled = [v for v in body if v.kind != "empty" and (v.kind == "number" or v.text)]
        numeric = bool(filled) and all(v.kind == "number" or _NUMERIC_LOOK.match(v.text) for v in filled)
        aligns.append("---:" if numeric else "---")
    lines = [f"표: {caption}"] if caption else []
    for r in range(nr):
        out = []
        for c in range(nc):
            if (r, c) in marks:
                out.append(marks[(r, c)])
            else:
                v = cell(r, c)
                out.append(_cell_text(_raw(v) if r < header else _show(v, col_dec[c])))
        lines.append("| " + " | ".join(out) + " |")
        if r == max(header, 1) - 1:  # 보고서 마크다운은 첫 행을 머리로 본다
            lines.append("|" + "|".join(aligns) + "|")
    if nc > MAX_COLS:
        warnings.append(f"열이 {nc}개라 한글 쪽 폭에 다 들어가지 않을 수 있어요. 필요한 열만 범위로 골라 보세요.")
    return "\n".join(lines) + "\n", warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sheet.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/sheet.py tests/test_sheet.py
git commit -m "feat: 엑셀(.xlsx)·CSV를 보고서 마크다운 표로 (표준 라이브러리)"
```

---

### Task 3: `table-from` 명령

**Files:**
- Modify: `hwpxkit/cli.py`
- Test: `tests/test_sheet.py`

**Interfaces:**
- Consumes: `sheet.table_from`, `sheet.SheetError`
- Produces: CLI `table-from <file> [--sheet] [--range] [--caption] [--header N] [--out FILE]` — 마크다운을 표준 출력(또는 `--out` 파일), 경고는 `[주의] …`를 표준 오류로.

- [ ] **Step 1: Write the failing test**

```python
def test_cli_table_from(tmp_path, capsys):
    from hwpxkit.cli import main
    (tmp_path / "u.csv").write_text("구분,금액\n가,1200\n", encoding="utf-8")
    assert main(["table-from", str(tmp_path / "u.csv"), "--caption", "금액"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "표: 금액" and "| 가 | 1,200 |" in out
    assert main(["table-from", str(tmp_path / "u.csv"), "--out", str(tmp_path / "t.md")]) == 0
    assert "| 가 | 1,200 |" in (tmp_path / "t.md").read_text(encoding="utf-8")


def test_cli_table_from_error(tmp_path, capsys):
    from hwpxkit.cli import main
    (tmp_path / "y.xls").write_bytes(b"x")
    assert main(["table-from", str(tmp_path / "y.xls")]) == 2
    assert ".xlsx로 저장" in capsys.readouterr().err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sheet.py -q -k cli`
Expected: FAIL — argparse `invalid choice: 'table-from'`

- [ ] **Step 3: Write implementation** (cli.py)

```python
def _cmd_table_from(args, workdir) -> int:
    from .sheet import table_from
    src = Path(args.file)
    if not src.is_file():
        raise PackageError(f"파일을 찾을 수 없어요: {src}")
    md, warnings = table_from(src, sheet=args.sheet, rng=args.range, header=args.header, caption=args.caption)
    for w in warnings:
        print(f"[주의] {w}", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"저장했어요: {args.out}")
    else:
        print(md, end="")
    return 0
```

`_parser()`의 `toc` 다음에:

```python
    s = sub.add_parser("table-from", help="엑셀(.xlsx)·CSV를 보고서 마크다운 표로")
    s.add_argument("file")
    s.add_argument("--sheet", help="시트 이름 (기본: 첫 시트)")
    s.add_argument("--range", help="범위 (예: B2:F10, 기본: 값이 있는 영역)")
    s.add_argument("--caption", help="표 제목 (표: … 줄)")
    s.add_argument("--header", type=int, default=1, help="머리 행 수 (기본 1)")
    s.add_argument("--out", help="마크다운을 저장할 파일 (없으면 화면에)")
    s.set_defaults(func=_cmd_table_from)
```

`main()`의 오류 처리(`except (PackageError, bridge.BridgeError, ValueError)`)가 `SheetError`(ValueError)를 이미 받아 종료 코드 2로 끝낸다.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sheet.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/cli.py tests/test_sheet.py
git commit -m "feat: table-from 명령"
```

---

### Task 4: 이어받기 — 기간 찾기와 날짜 바꾸기 줄, 보고일 제안

**Files:**
- Create: `hwpxkit/carry.py`
- Test: `tests/test_carry.py`

**Interfaces:**
- Produces:
  - `class CarryError(ValueError)`
  - `carry(pkg, to: tuple[int, int] | None = None) -> dict` — `{"from": (y, m), "to": (y, m), "spec": str, "ask": list[dict], "warnings": list[str]}`. 이 Task에서는 `@바꾸기`와 보고일 `ask`까지(계획 → 실적·숫자는 Task 5).
  - 내부: `_replacements(texts, frm) -> list[tuple[str, str]]`

- [ ] **Step 1: Write the failing tests**

```python
"""매달 이어받기 (carry): 지난달 보고서 → 이번 달 fill 지시문 초안 + 확인할 것."""
import pytest

from helpers import SECTION, append_to_body, para, table
from hwpxkit.form import fill, parse_fill
from hwpxkit.package import Package


def monthly(blank, period="‘26년 9월", report="2026. 10. 5.(월)", months=("9월", "10월")):
    pkg = Package.open(blank)
    append_to_body(pkg, para(f"{period} 월간 보고"))
    append_to_body(pkg, para(f"보고일: {report}"))
    append_to_body(pkg, para("보고 기간: 2026. 9. 1. ~ 9. 30. (26. 09.)"))
    append_to_body(pkg, table(3, 3, texts={(0, 0): "과제", (0, 1): f"금월({months[0]}) 실적", (0, 2): f"차월({months[1]}) 계획",
                                            (1, 0): "과제 1", (1, 1): "자료 수집", (1, 2): ["모형 시험", "- 시범 자료 검증"],
                                            (2, 0): "과제 2", (2, 1): "보고서 초안", (2, 2): ""}))
    append_to_body(pkg, table(3, 2, texts={(0, 0): "구분", (0, 1): "값", (1, 0): "진행률", (1, 1): "45%",
                                            (2, 0): "누적 집행액", (2, 1): "1,200"}))
    append_to_body(pkg, para("9월 중 협의를 마쳤고 10월 초에 시험한다. 19월이라는 글이나 2025년 9월은 그대로."))
    return pkg


def replaces(spec):
    return [tuple(line[len("@바꾸기 "):].split(" => ")) for line in spec.splitlines() if line.startswith("@바꾸기 ")]


def test_period_and_replacements_order(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    assert r["from"] == (2026, 9) and r["to"] == (2026, 10)
    pairs = replaces(r["spec"])
    assert ("‘26년 9월", "‘26년 10월") in pairs
    assert ("2026. 9. 1. ~ 9. 30.", "2026. 10. 1. ~ 10. 31.") in pairs
    assert ("(26. 09.)", "(26. 10.)") in pairs
    assert ("10월) 계획", "11월) 계획") not in pairs  # 괄호 안 달은 달 머리 꼴이 아님
    olds = [o for o, _ in pairs]
    assert olds.index("10월 초") < olds.index("9월 중")  # 뒤 달 먼저


def test_isolated_month_not_replaced(blank):
    from hwpxkit.carry import carry
    olds = [o for o, _ in replaces(carry(monthly(blank))["spec"])]
    assert "9월" not in olds and not any("19월" in o or "2025년" in o for o in olds)


def test_report_date_suggestion(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    ask = next(a for a in r["ask"] if a["kind"] == "report-date")
    assert ask["current"] == "2026. 10. 5.(월)" and ask["suggest"] == "2026. 11. 5.(목)"
    assert not any("10. 5." in o for o, _ in replaces(r["spec"]))


def test_december_rolls_year(blank):
    from hwpxkit.carry import carry
    pkg = monthly(blank, period="‘26년 12월", report="2027. 1. 6.(수)")
    append_to_body(pkg, para("12월 실적과 1월 계획을 정리한다."))
    r = carry(pkg)
    assert r["to"] == (2027, 1)
    pairs = replaces(r["spec"])
    assert ("‘26년 12월", "‘27년 1월") in pairs
    olds = [o for o, _ in pairs]
    assert olds.index("1월 계획") < olds.index("12월 실적")
    assert ("1월 계획", "2월 계획") in pairs and ("12월 실적", "1월 실적") in pairs


def test_period_missing_needs_to(blank):
    from hwpxkit.carry import CarryError, carry
    pkg = Package.open(blank)
    append_to_body(pkg, para("기간 표시가 없는 문서"))
    with pytest.raises(CarryError, match="--to"):
        carry(pkg)
    assert carry(pkg, to=(2026, 10))["from"] == (2026, 9)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_carry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'hwpxkit.carry'`

- [ ] **Step 3: Write implementation**

```python
"""매달 이어받기: 지난달 월간보고서 → 이번 달 fill 지시문 초안과 확인할 것 (설계 3장).

문서는 바꾸지 않는다. 숫자(누적·진행률)·새 계획·보고일은 지어내지 않고 확인할 것으로 알린다.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

from .package import Package
from .review import _REPORT_DATE_WORDS, _add_month, _period, _texts, _year

_WEEK = "월화수목금토일"
_YM = re.compile(r"([‘'’]?\s*)(\d{4}|\d{2})(\s*년\s*)(\d{1,2})(\s*월)")
_PAREN = re.compile(r"\(\s*(\d{2})(\s*\.\s*)(\d{1,2})(\s*\.?\s*)\)")
_RANGE = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*~\s*(?:(\d{4})\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?")
_DOT = re.compile(r"(?<![\d.])(\d{4})(\s*\.\s*)(\d{1,2})(\s*\.?)(?![\s.]*\d)")
_HEAD = re.compile(r"(?<![\d(])(\d{1,2})(\s*월)(\s*)(실적|계획|분|추진|현황|말|중|초)")
_REPORT_DAY = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*(?:\(\s*[월화수목금토일]\s*\))?")


class CarryError(ValueError):
    """이어받기 오류. 메시지는 사용자용 한국어."""


def _pad(old: str, new: int) -> str:
    return f"{new:02d}" if len(old) == 2 and old.startswith("0") else str(new)


def _year_text(old: str, y: int) -> str:
    return f"{y % 100:02d}" if len(old) == 2 else str(y)


def _last(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _replacements(texts: list[str], frm: tuple[int, int]) -> list[tuple[str, str]]:
    """지난달(M)·다음 달(M+1)이 들어간 글 → 한 달 뒤 글. 뒤 달 먼저, 같은 달은 긴 글 먼저."""
    nxt = _add_month(*frm, 1)
    found: dict[str, tuple[str, int]] = {}  # 옛 글 → (새 글, 0=M+1 / 1=M)

    def put(old: str, new: str, ym: tuple[int, int]) -> None:
        if ym == nxt:
            found.setdefault(old, (new, 0))
        elif ym == frm:
            found.setdefault(old, (new, 1))

    for text in texts:
        for m in _RANGE.finditer(text):
            y, mo = int(m.group(1)), int(m.group(2))
            if (y, mo) not in (frm, nxt):
                continue
            ny, nm = _add_month(y, mo, 1)
            d1, d2 = int(m.group(3)), int(m.group(6))
            whole = d1 == 1 and d2 == _last(y, int(m.group(5)))
            nd1, nd2 = (1, _last(ny, nm)) if whole else (min(d1, _last(ny, nm)), min(d2, _last(ny, nm)))
            put(m.group(0).strip(), f"{ny}. {nm}. {nd1}. ~ {nm}. {nd2}.", (y, mo))
        for m in _YM.finditer(text):
            y, mo = _year(m.group(2)), int(m.group(4))
            ny, nm = _add_month(y, mo, 1)
            new = f"{m.group(1)}{_year_text(m.group(2), ny)}{m.group(3)}{_pad(m.group(4), nm)}{m.group(5)}"
            put(m.group(0).strip(), new.strip(), (y, mo))
        for m in _PAREN.finditer(text):
            y, mo = _year(m.group(1)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            put(m.group(0), f"({_year_text(m.group(1), ny)}{m.group(2)}{_pad(m.group(3), nm)}{m.group(4)})", (y, mo))
        for m in _DOT.finditer(text):
            y, mo = int(m.group(1)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            put(m.group(0), f"{ny}{m.group(2)}{_pad(m.group(3), nm)}{m.group(4)}", (y, mo))
        for m in _HEAD.finditer(text):
            mo = int(m.group(1))
            for ym in (frm, nxt):
                if ym[1] == mo:
                    nm = _add_month(*ym, 1)[1]
                    put(m.group(0), f"{nm}{m.group(2)}{m.group(3)}{m.group(4)}", ym)
    return [(old, new) for old, (new, _) in sorted(found.items(), key=lambda kv: (kv[1][1], -len(kv[0])))]


def _report_dates(texts: list[str]) -> list[dict]:
    out = []
    for text in texts:
        if not _REPORT_DATE_WORDS.search(text):
            continue
        for m in _REPORT_DAY.finditer(text):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            ny, nm = _add_month(y, mo, 1)
            day = dt.date(ny, nm, min(d, _last(ny, nm)))
            out.append({"kind": "report-date", "where": text[:40], "address": "", "current": m.group(0).strip(),
                        "suggest": f"{day.year}. {day.month}. {day.day}.({_WEEK[day.weekday()]})",
                        "message": "이번 달 보고일을 알려 주세요"})
    return out


def carry(pkg: Package, to: tuple[int, int] | None = None) -> dict:
    texts_ctx = _texts(pkg)
    found = _period(texts_ctx)
    warnings: list[str] = []
    if to is not None:
        frm = _add_month(*to, -1)
        if found and found != frm:
            warnings.append(f"문서의 보고 기간은 {found[0]}년 {found[1]}월인데 {frm[0]}년 {frm[1]}월 기준으로 만들었어요.")
    elif found:
        frm, to = found, _add_month(*found, 1)
    else:
        raise CarryError("지난달 보고 기간을 찾지 못했어요. --to 2026-10처럼 이번 달을 알려 주세요.")
    texts = [t for t, _ in texts_ctx]
    plain = [t for t, ctx in texts_ctx if not _REPORT_DATE_WORDS.search(ctx)]
    lines = [f"@바꾸기 {old} => {new}" for old, new in _replacements(plain, frm)]
    ask = _report_dates(texts)
    return {"from": frm, "to": to, "spec": "\n".join(lines) + ("\n" if lines else ""), "ask": ask,
            "warnings": warnings}
```

시험 문서의 "금월(9월) 실적"처럼 괄호 안 달은 `_HEAD`가 보지 않는다(`(?<![\d(])`). 표 머리의 달이 바뀌어야 하면 칸 머리를 사용자가 고친다(확인할 것으로 알리지 않음, 범위 밖). 단, `_HEAD`는 "9월 중"처럼 붙은 꼴을 바꾼다.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_carry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/carry.py tests/test_carry.py
git commit -m "feat: 매달 이어받기 — 기간 찾기, 날짜 바꾸기 줄, 보고일 제안"
```

---

### Task 5: 이어받기 — 계획 → 실적, 누적·진행률, `carry` 명령

**Files:**
- Modify: `hwpxkit/carry.py`, `hwpxkit/cli.py`
- Test: `tests/test_carry.py`

**Interfaces:**
- Consumes: `form.cells`, `form.list_fields`, `review._CURRENT`, `review._NEXT`
- Produces: `carry()`의 `spec`에 `@칸` 묶음, `ask`에 `next-plan`·`plan-columns`·`number`. CLI `carry <file> <out.md> [--to YYYY-MM] [--json]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_plan_moves_to_actual(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    spec = r["spec"]
    assert "@칸 표1 | 과제 1 | 금월(9월) 실적\n모형 시험\n- 시범 자료 검증\n" in spec
    assert "@칸 표1 | 과제 1 | 차월(10월) 계획\n\n" in spec
    assert "과제 2 | 금월" not in spec  # 계획이 빈 행은 건너뜀
    plans = [a for a in r["ask"] if a["kind"] == "next-plan"]
    assert len(plans) == 1 and "과제 1" in plans[0]["where"]


def test_numbers_asked_not_invented(blank):
    from hwpxkit.carry import carry
    r = carry(monthly(blank))
    nums = {a["current"]: a for a in r["ask"] if a["kind"] == "number"}
    assert set(nums) == {"45%", "1,200"}
    assert nums["45%"]["address"].startswith("@칸 표2 | 진행률")
    assert "45%" not in r["spec"]


def test_ambiguous_plan_columns(blank):
    from hwpxkit.carry import carry
    pkg = Package.open(blank)
    append_to_body(pkg, para("‘26년 9월 월간 보고"))
    append_to_body(pkg, table(2, 4, texts={(0, 0): "과제", (0, 1): "금월 실적", (0, 2): "차월 계획", (0, 3): "연간 계획",
                                            (1, 0): "가", (1, 1): "a", (1, 2): "b", (1, 3): "c"}))
    r = carry(pkg)
    assert "@칸" not in r["spec"] and any(a["kind"] == "plan-columns" for a in r["ask"])


def test_merged_or_object_cells_skipped(blank):
    from hwpxkit.carry import carry
    pkg = Package.open(blank)
    append_to_body(pkg, para("‘26년 9월 월간 보고"))
    append_to_body(pkg, table(3, 3, texts={(0, 0): "과제", (0, 1): "금월 실적", (0, 2): "차월 계획",
                                            (1, 0): "가", (1, 1): "a", (1, 2): "b"}, spans={(1, 2): (2, 1)}, skip={(2, 2)}))
    r = carry(pkg)
    assert "@칸" not in r["spec"]


def test_spec_applies_with_fill(blank, tmp_path):
    from hwpxkit.carry import carry
    from hwpxkit.form import cells
    pkg = monthly(blank)
    spec = carry(pkg)["spec"]
    fill(pkg, parse_fill(spec), base_dir=tmp_path)
    by = {(c.table, c.row_header, c.col_header): c.text for c in cells(pkg)}
    assert by[(1, "과제 1", "금월(9월) 실적")] == "모형 시험\n- 시범 자료 검증"
    assert by[(1, "과제 1", "차월(10월) 계획")] == ""
    assert by[(1, "과제 2", "금월(9월) 실적")] == "보고서 초안"
    texts = [t for t in (p.text or "" for p in pkg.xml(SECTION).iter()) if t]
    assert any("‘26년 10월" in t for t in texts) and any("2026. 10. 1. ~ 10. 31." in t for t in texts)


def test_cli_carry(blank, tmp_path, capsys):
    from hwpxkit.cli import main
    src = monthly(blank).save(tmp_path / "9월.hwpx")
    out = tmp_path / "초안.md"
    assert main(["carry", str(src), str(out)]) == 0
    text = capsys.readouterr().out
    assert "2026년 9월 → 2026년 10월" in text and "확인할 것" in text and "2026. 11. 5.(목)" in text
    assert "@바꾸기 ‘26년 9월 => ‘26년 10월" in out.read_text(encoding="utf-8")
    assert main(["carry", str(src), str(out), "--json"]) == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["to"] == "2026-10" and data["ask"]


def test_cli_carry_to_option(blank, tmp_path, capsys):
    from hwpxkit.cli import main
    pkg = Package.open(blank)
    append_to_body(pkg, para("기간 없음"))
    src = pkg.save(tmp_path / "x.hwpx")
    assert main(["carry", str(src), str(tmp_path / "o.md")]) == 2
    assert "--to" in capsys.readouterr().err
    assert main(["carry", str(src), str(tmp_path / "o.md"), "--to", "2026-10"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_carry.py -q -k "plan or numbers or ambiguous or merged or applies or cli"`
Expected: FAIL — spec에 `@칸`이 없음, argparse `invalid choice: 'carry'`

- [ ] **Step 3: Write implementation**

carry.py에 import(`from .form import cells, list_fields`, `from .ns import q`, `from .review import _CURRENT, _NEXT` — 기존 review import 줄에 합친다)와 아래를 더한다.

```python
_NUM_HEAD = re.compile(r"누적|진행률|진척률|달성률|공정률|집행률|%")
_NUM_TEXT = re.compile(r"^[-+]?[\d,]*\.?\d+\s*%?$")
_OBJ = ("hp:tbl", "hp:pic", "hp:equation")


def _has_object(tc) -> bool:
    sub = tc.find(q("hp:subList"))
    return any(next(p.iter(q(t)), None) is not None for p in sub.findall(q("hp:p")) for t in _OBJ)


def _is_current(head: str) -> bool:
    return bool(_CURRENT.search(head) or "실적" in head) and not (_NEXT.search(head) or "계획" in head)


def _is_next(head: str) -> bool:
    return bool(_NEXT.search(head) or "계획" in head) and not (_CURRENT.search(head) or "실적" in head)


def _plan_moves(pkg: Package) -> tuple[list[str], list[dict]]:
    """금월 실적 ← 차월 계획 (같은 표·같은 행), 차월 계획 칸은 비움."""
    all_cells = cells(pkg)
    address = {(f["table"], f["row"] - 1, f["col"] - 1): f["address"] for f in list_fields(pkg)}
    lines, ask = [], []
    for t in sorted({c.table for c in all_cells}):
        tc = [c for c in all_cells if c.table == t]
        heads = {c.col: c.text for c in tc if c.row == 0 and c.colspan == 1}
        cur = [col for col, h in heads.items() if _is_current(h)]
        nxt = [col for col, h in heads.items() if _is_next(h)]
        if not cur and not nxt:
            continue
        if len(cur) != 1 or len(nxt) != 1:
            ask.append({"kind": "plan-columns", "where": f"표{t}", "address": "", "current": "", "suggest": "",
                        "message": "계획·실적 열을 정확히 찾지 못했어요. 이 표는 직접 확인해 주세요."})
            continue
        grid = {(c.row, c.col): c for c in tc}
        for r in sorted({c.row for c in tc if c.row > 0}):
            src, dst = grid.get((r, nxt[0])), grid.get((r, cur[0]))
            if src is None or dst is None or src.rowspan != 1 or dst.rowspan != 1:
                continue
            if not src.text or _has_object(src.tc) or _has_object(dst.tc):
                continue
            a_dst, a_src = address.get((t, r, cur[0])), address.get((t, r, nxt[0]))
            if not a_dst or not a_src:
                continue
            lines += [a_dst, src.text, "", a_src, "", ""]
            ask.append({"kind": "next-plan", "where": f"표{t} {src.row_header or f'{r + 1}행'}", "address": a_src,
                        "current": "", "suggest": "", "message": "다음 달 계획을 새로 알려 주세요"})
    return lines, ask


def _numbers(pkg: Package) -> list[dict]:
    address = {(f["table"], f["row"] - 1, f["col"] - 1): f["address"] for f in list_fields(pkg)}
    out = []
    for c in cells(pkg):
        if c.row == 0 or c.col == 0:
            continue
        text = c.text.strip()
        if _NUM_HEAD.search(f"{c.row_header} {c.col_header}") and _NUM_TEXT.match(text):
            out.append({"kind": "number", "where": c.label(), "address": address.get((c.table, c.row, c.col), ""),
                        "current": text, "suggest": "", "message": "이번 달 값이 필요해요"})
    return out
```

`carry()`의 반환 직전을 다음으로 바꾼다.

```python
    moves, move_ask = _plan_moves(pkg)
    lines += [""] + moves if moves else []
    ask = _report_dates(texts) + move_ask + _numbers(pkg)
    spec = "\n".join(lines) + "\n" if lines else ""
    return {"from": frm, "to": to, "spec": spec, "ask": ask, "warnings": warnings}
```

`@칸` 뒤 빈 내용(계획 칸 비우기)은 다음 `@칸` 앞까지 빈 줄이라 `parse_fill`이 빈 칸으로 읽는다.

`hwpxkit/cli.py`:

```python
def _cmd_carry(args, workdir) -> int:
    from . import carry as carry_mod
    src, out = _resolve_template(args.file), Path(args.out)
    if out.suffix.lower() != ".md":
        raise ValueError(f"초안은 .md 파일로 저장해요: {out.name}")
    to = None
    if args.to:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", args.to.strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise ValueError("--to는 2026-10처럼 써 주세요.")
        to = (int(m.group(1)), int(m.group(2)))
    r = carry_mod.carry(_open_any(src, workdir), to=to)
    out.write_text(r["spec"], encoding="utf-8")
    if args.json:
        print(json.dumps({"from": "%d-%02d" % r["from"], "to": "%d-%02d" % r["to"], "spec": r["spec"],
                          "ask": r["ask"], "warnings": r["warnings"]}, ensure_ascii=False))
        return 0
    (fy, fm), (ty, tm) = r["from"], r["to"]
    print(f"{fy}년 {fm}월 → {ty}년 {tm}월 초안을 만들었어요: {out}")
    for w in r["warnings"]:
        print(f"[주의] {w}")
    if r["ask"]:
        print("확인할 것:")
        for a in r["ask"]:
            extra = f" (지금: {a['current']})" if a["current"] else ""
            extra += f" → 제안: {a['suggest']}" if a["suggest"] else ""
            print(f"  - {a['where']}: {a['message']}{extra}")
    return 0
```

`import re`가 cli.py 첫머리에 없으면 더한다. `CarryError`는 ValueError라 `main()`이 종료 코드 2로 처리한다. `_parser()`의 `table-from` 다음에:

```python
    s = sub.add_parser("carry", help="지난달 보고서로 이번 달 채우기 지시문 초안 만들기")
    s.add_argument("file", help="지난달 보고서 (.hwpx/.hwp)")
    s.add_argument("out", help="초안 지시문 .md")
    s.add_argument("--to", help="이번 달 (예: 2026-10). 문서에서 보고 기간을 못 찾을 때")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_carry)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_carry.py -q` 그리고 `python -m pytest -q -m "not hangul"`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add hwpxkit/carry.py hwpxkit/cli.py tests/test_carry.py
git commit -m "feat: 이어받기 — 계획→실적, 누적·진행률 확인, carry 명령"
```

---

### Task 6: 안내 문서와 0.5.0

**Files:**
- Create: `skills/hwp-helper/reference/monthly.md`
- Modify: `skills/hwp-helper/SKILL.md`, `skills/hwp-helper/reference/form.md`, `skills/hwp-helper/reference/markdown.md`, `tests/test_plugin_files.py`, `README.md`, `.claude-plugin/plugin.json`
- Test: `tests/test_carry.py`

- [ ] **Step 1: Write the failing test**

```python
def test_skill_documents_monthly():
    from pathlib import Path
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "monthly.md").read_text(encoding="utf-8")
    for word in ('hwpx.py" carry', "table-from", "--to", "확인할 것", "지어내지"):
        assert word in text, word
    assert "reference/monthly.md" in (root / "SKILL.md").read_text(encoding="utf-8")
    assert "---:" in (root / "reference" / "markdown.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_carry.py -q -k skill_documents`
Expected: FAIL — `FileNotFoundError`

- [ ] **Step 3: Write docs**

`skills/hwp-helper/reference/monthly.md`:

```markdown
# 매달 이어받기와 엑셀 표

## 지난달 보고서로 이번 달 만들기

1. `python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" carry <지난달.hwpx> <초안.md>` (보고 기간을 못 찾으면 `--to 2026-10`)
2. 출력의 "확인할 것"을 사용자에게 한 번에 묻는다: 이번 달 보고일, 칸마다 새 다음 달 계획, 누적·진행률 같은 이번 달 수치.
3. 답을 초안에 더한다: 수치는 출력에 나온 `@칸 …` 줄 아래에 값을 쓰고, 새 계획은 비운 계획 칸 `@칸` 줄 아래에 쓴다. 보고일은 `@바꾸기 옛 날짜 => 새 날짜`.
4. 초안을 사용자에게 보여 주고 `fill <지난달.hwpx> <초안.md> <이번달.hwpx>`로 만든다. 그다음 `review`로 날짜·요일을 확인한다.

- 숫자·계획·날짜는 지어내지 않는다. 사용자가 모르면 칸을 비우고 알린다.
- 초안의 "이번 달 실적"은 지난달에 쓴 계획을 옮긴 것이다. 실제로 한 일과 다르면 사용자 말대로 고친다.
- 표 머리의 달(예: "금월(9월) 실적")은 칸 머리라 자동으로 바꾸지 않는다. 필요하면 `@바꾸기 금월(9월) => 금월(10월)`을 더한다(뒤 달부터).

## 엑셀·CSV를 표로

`python "${CLAUDE_PLUGIN_ROOT}/hwpx.py" table-from <파일.xlsx|.csv> [--sheet 시트] [--range B2:F10] [--caption 제목]`

- 출력된 마크다운 표를 보고서 내용(.md)에 그대로 넣는다. 숫자는 천 단위 쉼표·소수 자리·오른쪽 정렬(`---:`)이 맞춰져 있다.
- 수식은 엑셀이 저장한 계산 결과만 쓴다. "수식 결과가 저장되어 있지 않아" 경고가 나오면 사용자에게 엑셀에서 열어 저장해 달라고 한다.
- `.xls`는 엑셀에서 `.xlsx`로 저장해 달라고 한다.
- 표 칸(@칸)에는 표를 넣을 수 없다. 양식의 기존 표를 채울 때는 값을 `@칸`마다 옮긴다.
```

`SKILL.md`의 toc 단락 다음에:

```markdown
매달 같은 양식을 쓰는 보고서는 `carry`로 지난달 파일에서 이번 달 초안을 만들고, 엑셀·CSV 값은 `table-from`으로 표로 바꾼다. 절차는 `reference/monthly.md`.
```

`reference/form.md` 맨 끝에 한 줄: `지난달 보고서에서 시작할 때는 \`carry\`가 이 지시문의 초안을 만든다(reference/monthly.md).`

`reference/markdown.md` 표 설명(병합 줄 다음)에 한 줄: `- 정렬: 구분 줄에 \`---:\`(오른쪽), \`:---:\`(가운데), \`:---\`(왼쪽). 숫자 열은 \`---:\`가 보기 좋다. 머리 행은 그대로.`

`tests/test_plugin_files.py`의 허용 옵션에 `"--to", "--sheet", "--range", "--caption", "--header", "--out"`을 더한다. `README.md` 명령 표에 두 줄:

```markdown
| `carry 지난달 초안.md` | 지난달 보고서로 이번 달 채우기 지시문 초안 (날짜 넘기기, 계획→실적, 확인할 수치) | .hwp일 때만 |
| `table-from 파일.xlsx` | 엑셀·CSV를 보고서 마크다운 표로 (천 단위 쉼표, 소수 자리, 오른쪽 정렬) | 아니요 |
```

`plugin.json` 버전 `"0.5.0"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -m "not hangul"`
Expected: 모두 PASS

- [ ] **Step 5: 실제 흐름 수동 확인**

1. 시험용 월간보고서(`tests/test_carry.py`의 `monthly()`와 같은 내용)를 저장하고 `carry` → 초안 확인 → 값 몇 개 직접 더해 `fill` → `review` → 한글이 있으면 `preview`로 쪽 그림 확인.
2. 작은 엑셀 파일(시험 helper로 만든 것)로 `table-from` → `render`로 표 넣기 → 쪽 그림에서 숫자 오른쪽 정렬 확인.
3. 결과를 ledger에 한 줄로 남긴다.

- [ ] **Step 6: Commit**

```bash
git add skills tests .claude-plugin README.md
git commit -m "feat: 매달 이어받기·엑셀 표 안내, 0.5.0"
```

---

## Self-Review 결과

- 스펙 대응: 3장 → Task 4·5, 4장 → Task 1·2·3, 5장 오류 → Task 2(시트·범위·xls·수식·열 수)·Task 4(기간), 6장 범위 밖 지킴, 7장 시험 → 각 Task.
- 스펙과 다른 점(실행 때 Ruling으로 기록): 칸 글의 `|`를 `\|`가 아니라 전각 `｜`로 바꾼다(엔진의 표 파서가 `\|`를 모름). `table-from`에 `--out`을 더했다(긴 표를 파일로 받기). `--header 0`은 구분 줄을 첫 행 뒤에 둔다(보고서 마크다운은 첫 행을 머리로 봄).
- 이름 일관성: `table_from(path, *, sheet, rng, header, caption)`, `carry(pkg, to)` 반환 키 `from/to/spec/ask/warnings`, ask 항목 키 `kind/where/address/current/suggest/message`를 Task 2~5에서 같게 썼다.
