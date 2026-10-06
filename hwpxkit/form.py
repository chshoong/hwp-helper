"""양식 채우기: 표 칸 찾기, 칸 채우기(칸의 글머리·글자 서식·메모 유지), 행 수 맞추기, 글자 바꾸기.

칸 주소는 '표 번호 + 행 머리 + 열 머리'(공백 무시 부분 일치) 또는 1부터 세는 행·열 번호.
칸 서식은 그 칸 → 같은 열 → 같은 표 → 문서의 다른 표 칸 순서로 견본을 찾는다.
"""
from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .body import all_text, own_text, section_of, t_text
from .header import Header
from .mdparse import Bullet, Para, parse
from .ns import q
from .package import Package
from .render import Renderer
from .samples import Catalog, bullet_chars, learn, style_of


class FormError(ValueError):
    """양식 채우기 오류. 메시지는 사용자용 한국어."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


@dataclass
class Cell:
    table: int
    row: int
    col: int
    rowspan: int
    colspan: int
    tc: etree._Element = field(repr=False)
    row_header: str = ""
    col_header: str = ""

    @property
    def text(self) -> str:
        sub = self.tc.find(q("hp:subList"))
        return "\n".join(own_text(p) for p in sub.findall(q("hp:p"))).strip()

    def label(self) -> str:
        where = " × ".join(x for x in (self.row_header, self.col_header) if x)
        return f"[표{self.table}] " + (where or f"{self.row + 1}행 {self.col + 1}열")


def tables(pkg: Package, section: str | None = None) -> list[etree._Element]:
    """문서의 표 (구역 순서, 구역 안에서는 문서 순서). section을 주면 그 구역만."""
    names = [section] if section else pkg.section_names()
    return [tbl for name in names for tbl in pkg.xml(name).iter(q("hp:tbl"))]


def _table_cells(tbl: etree._Element, number: int) -> list[Cell]:
    out: list[Cell] = []
    grid: dict[tuple[int, int], Cell] = {}
    for tr in tbl.findall(q("hp:tr")):
        for tc in tr.findall(q("hp:tc")):
            a, s = tc.find(q("hp:cellAddr")), tc.find(q("hp:cellSpan"))
            cell = Cell(number, int(a.get("rowAddr")), int(a.get("colAddr")),
                        int(s.get("rowSpan")) if s is not None else 1, int(s.get("colSpan")) if s is not None else 1, tc)
            out.append(cell)
            for i in range(cell.row, cell.row + cell.rowspan):
                for j in range(cell.col, cell.col + cell.colspan):
                    grid[(i, j)] = cell
    for cell in out:
        head = grid.get((0, cell.col))
        if cell.row > 0 and head is not None and head is not cell:
            cell.col_header = _one_line(head.text)
        left = grid.get((cell.row, 0))
        if cell.col > 0 and left is not None and left is not cell:
            cell.row_header = _one_line(left.text)
    return out


def cells(pkg: Package, section: str | None = None) -> list[Cell]:
    out: list[Cell] = []
    for n, tbl in enumerate(tables(pkg, section), 1):
        out += _table_cells(tbl, n)
    return out


def _score(cell: Cell, key, kind: str) -> int:
    """칸이 키에 맞는 정도: 2 정확(번호 일치 포함), 1 부분 일치, 0 안 맞음. 키가 없으면 1."""
    if key is None:
        return 1
    if isinstance(key, int):
        start, span = (cell.row, cell.rowspan) if kind == "row" else (cell.col, cell.colspan)
        return 2 if start <= key - 1 < start + span else 0
    header = cell.row_header if kind == "row" else cell.col_header
    if not header:
        return 0
    if _norm(key) == _norm(header):
        return 2
    return 1 if _norm(key) in _norm(header) else 0


def find_cell(pkg: Package, table: int, row_key, col_key, section: str | None = None) -> Cell:
    """칸 찾기. 문자열 키는 행·열 머리(정확히 같은 머리를 먼저, 없으면 부분 일치), 정수 키는 1부터 행·열 번호."""
    all_cells = cells(pkg, section)
    count = max((c.table for c in all_cells), default=0)
    in_table = [c for c in all_cells if c.table == table]
    if not in_table:
        raise FormError(f"표{table}이(가) 없어요. 이 문서에는 표가 {count}개 있어요.")
    scored = [(_score(c, row_key, "row") + _score(c, col_key, "col"), c) for c in in_table]
    scored = [(n, c) for n, c in scored if n and _score(c, row_key, "row") and _score(c, col_key, "col")]
    if scored:
        best = max(n for n, _ in scored)
        found = [c for n, c in scored if n == best]
        if len(found) == 1:
            return found[0]
        listing = "\n".join(f"  - {c.label()}" for c in found[:6])
        raise FormError(f"표{table}에서 여러 칸이 맞아요. 행·열 머리를 정확히 쓰거나 '#2'처럼 번호로 써 주세요:\n{listing}")
    listing = "\n".join(f"  - {c.label()}" for c in in_table if c.row > 0 and c.col > 0)
    raise FormError(f"표{table}에서 맞는 칸이 없어요. 이 표의 칸:\n{listing}")


@dataclass
class CellOp:
    table: int
    row: str | int | None
    col: str | int | None
    content: str
    lineno: int


@dataclass
class RowsOp:
    table: int
    rows: int
    lineno: int


@dataclass
class ReplaceOp:
    old: str
    new: str
    lineno: int


_DIRECTIVE = re.compile(r"^@(\S+)\s*(.*)$")


def _table_no(text: str, lineno: int) -> int:
    m = re.fullmatch(r"표\s*(\d+)", text.strip())
    if not m:
        raise FormError(f"{lineno}번째 줄: 표 번호는 '표3'처럼 써 주세요 (받은 값: {text.strip()})")
    return int(m.group(1))


def _key(text: str):
    """'-'·빈칸은 생략, '#2'는 2번째 행/열, 그 밖(숫자만 있어도)은 머리 글자."""
    text = text.strip()
    if text in ("", "-"):
        return None
    if re.fullmatch(r"#\s*\d+", text):
        return int(text[1:].strip())
    return text


def parse_fill(md: str) -> list:
    ops: list = []
    current: CellOp | None = None
    body: list[str] = []

    def close():
        if current is not None:
            current.content = "\n".join(body).strip()
            ops.append(current)

    for i, raw in enumerate(md.lstrip("\ufeff").replace("\r\n", "\n").split("\n"), 1):
        line = raw.strip()
        m = _DIRECTIVE.match(line)
        if not m:
            if current is None and line and not (line.startswith("<!--") and line.endswith("-->")):
                raise FormError(f"{i}번째 줄: 첫 지시문(@칸, @행수, @바꾸기) 앞에는 글을 쓸 수 없어요.")
            if current is not None:
                body.append(raw)
            continue
        close()
        current, body = None, []
        name, rest = m.group(1), m.group(2)
        if name == "칸":
            parts = rest.split("|")
            if len(parts) != 3:
                raise FormError(f"{i}번째 줄: '@칸 표번호 | 행 | 열' 형식이어야 해요 (행·열을 안 쓰면 '-').")
            current = CellOp(_table_no(parts[0], i), _key(parts[1]), _key(parts[2]), "", i)
        elif name == "행수":
            parts = rest.split("|")
            if len(parts) != 2 or not parts[1].strip().isdigit():
                raise FormError(f"{i}번째 줄: '@행수 표번호 | 숫자' 형식이어야 해요.")
            ops.append(RowsOp(_table_no(parts[0], i), int(parts[1].strip()), i))
        elif name == "바꾸기":
            if "=>" not in rest:
                raise FormError(f"{i}번째 줄: '@바꾸기 옛 글자 => 새 글자' 형식이어야 해요.")
            old, new = rest.split("=>", 1)
            ops.append(ReplaceOp(old.strip(), new.strip(), i))
        else:
            raise FormError(f"{i}번째 줄: 알 수 없는 지시문이에요: @{name} (가능: @칸, @행수, @바꾸기)")
    close()
    return ops


def _cell_paragraphs(tc: etree._Element) -> list[etree._Element]:
    return tc.find(q("hp:subList")).findall(q("hp:p"))


def cell_catalog(pkg: Package, cell: Cell) -> Catalog:
    """칸 견본: 그 칸 → 같은 열 → 같은 표 → 문서의 모든 표 칸."""
    h = Header(pkg)
    chars = bullet_chars(h)
    every = cells(pkg)
    same_table = [c for c in every if c.table == cell.table and c.row > 0]
    pools = [
        _cell_paragraphs(cell.tc),
        [p for c in same_table if c.col == cell.col and c is not cell for p in _cell_paragraphs(c.tc)],
        [p for c in same_table for p in _cell_paragraphs(c.tc)],
        [p for c in every for p in _cell_paragraphs(c.tc)],
    ]
    paras: dict = {}
    for pool in pools:
        learned, _, _ = learn(pool, h, chars)
        for role, st in learned.items():
            paras.setdefault(role, st)
    if "body" not in paras:
        flat = [p for pool in pools for p in pool]
        plain = next((p for p in flat if own_text(p).strip() and not style_of(p, h).auto_bullet), None)
        paras["body"] = style_of(plain if plain is not None else flat[0], h)
    return Catalog(paras)


def _memo_text(begin_ctrl: etree._Element) -> str:
    return " ".join(all_text(begin_ctrl).split())


def _take_memos(sub: etree._Element) -> list[tuple]:
    """칸의 메모(fieldBegin MEMO ~ fieldEnd)와, 메모가 붙어 있던 글."""
    out = []
    for begin in list(sub.iter(q("hp:fieldBegin"))):
        if begin.get("type") != "MEMO":
            continue
        bctrl = begin.getparent()
        end = next((e for e in sub.iter(q("hp:fieldEnd")) if e.get("beginIDRef") == begin.get("id")), None)
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
        out.append((copy.deepcopy(bctrl), copy.deepcopy(ectrl) if ectrl is not None else None, anchor.strip()))
    return out


def _restore_memos(paragraphs: list[etree._Element], memos: list[tuple]) -> list[str]:
    warnings = []
    for bctrl, ectrl, anchor in memos:
        target = next((p for p in paragraphs if anchor and anchor in own_text(p)), None)
        if target is None:
            target = paragraphs[0]
            warnings.append(f"메모('{_memo_text(bctrl)[:30]}')가 붙어 있던 글 '{anchor}'이(가) 새 내용에 없어 칸 첫 줄에 붙였어요.")
        runs = target.findall(q("hp:run"))
        if not runs:
            runs = [etree.SubElement(target, q("hp:run"), {"charPrIDRef": "0"})]
        runs[0].insert(0, bctrl)
        if ectrl is not None:
            runs[-1].append(ectrl)
    return warnings


def fill_cell(pkg: Package, cell: Cell, content: str, *, base_dir: Path = Path(".")) -> list[str]:
    """칸 내용을 바꾼다. 칸의 서식 견본을 복제하고, 메모는 같은 글(없으면 첫 줄)에 다시 붙인다."""
    blocks = parse(content)
    if any(not isinstance(b, (Bullet, Para)) for b in blocks):
        raise FormError("칸 안에는 글, 글머리(□ ○ - ·), 문단 속 수식($…$)만 넣을 수 있어요.")
    if any(next(cell.tc.find(q("hp:subList")).iter(q(tag)), None) is not None for tag in ("hp:tbl", "hp:pic")):
        raise FormError(f"{cell.label()} 칸에는 표나 그림이 들어 있어 채우면 지워져요. 한글에서 직접 고치거나 "
                        "그 안쪽 표를 주소로 지정해 주세요.")
    for name in pkg.section_names():
        pkg.edit(name)
    cat = cell_catalog(pkg, cell)
    renderer = Renderer(pkg, cat, base_dir=base_dir)
    elements = renderer.build(blocks)
    if not elements:  # 빈 내용: 본문 견본 모양의 빈 문단 하나
        st = cat.require("body")
        empty = etree.Element(q("hp:p"), {"id": "0", "paraPrIDRef": st.para_pr, "styleIDRef": st.style,
                                          "pageBreak": "0", "columnBreak": "0", "merged": "0"})
        etree.SubElement(empty, q("hp:run"), {"charPrIDRef": st.char_pr})
        elements = [empty]
    sub = cell.tc.find(q("hp:subList"))
    memos = _take_memos(sub)
    for p in sub.findall(q("hp:p")):
        sub.remove(p)
    for el in elements:
        sub.append(el)
    return renderer.warnings + _restore_memos(sub.findall(q("hp:p")), memos)


def _clear_cell(tc: etree._Element) -> None:
    """칸의 첫 문단 모양과 글자모양만 남긴 빈 칸으로 만든다 (메모·개체도 지움)."""
    sub = tc.find(q("hp:subList"))
    first = sub.find(q("hp:p"))
    attrs = dict(first.attrib) if first is not None else {"id": "0", "paraPrIDRef": "0", "styleIDRef": "0",
                                                          "pageBreak": "0", "columnBreak": "0", "merged": "0"}
    run = first.find(q("hp:run")) if first is not None else None
    char = run.get("charPrIDRef") if run is not None else "0"
    for p in sub.findall(q("hp:p")):
        sub.remove(p)
    p = etree.SubElement(sub, q("hp:p"), attrs)
    etree.SubElement(p, q("hp:run"), {"charPrIDRef": char})


def _signature(tr: etree._Element) -> tuple:
    return tuple((int(tc.find(q("hp:cellAddr")).get("colAddr")),
                  int(tc.find(q("hp:cellSpan")).get("colSpan")) if tc.find(q("hp:cellSpan")) is not None else 1)
                 for tc in tr.findall(q("hp:tc")))


def set_rows(pkg: Package, table: int, total: int) -> None:
    """표의 행 수를 total(머리 행 포함)로 맞춘다.

    데이터 행 = 머리 아래에서 가장 흔한 칸 구조의 행. 늘릴 때는 마지막 데이터 행을 복제한 빈 행을
    그 바로 뒤(요청사항·합계처럼 모양이 다른 끝 행보다 앞)에 넣고, 줄일 때는 데이터 행을 끝에서부터 지운다.
    """
    all_tables = tables(pkg)
    if not 1 <= table <= len(all_tables):
        raise FormError(f"표{table}이(가) 없어요. 이 문서에는 표가 {len(all_tables)}개 있어요.")
    if total < 2:
        raise FormError("행 수는 머리 행을 포함해 2 이상이어야 해요.")
    tbl = all_tables[table - 1]
    trs = tbl.findall(q("hp:tr"))
    n = len(trs)
    if total == n:
        return
    for name in pkg.section_names():
        pkg.edit(name)
    common = Counter(_signature(tr) for tr in trs[1:]).most_common(1)[0][0]
    data = [i for i in range(1, n) if _signature(trs[i]) == common]
    last = data[-1]
    block = [i for i in data if all(j in data for j in range(i, last + 1))]
    grid = _table_cells(tbl, table)
    touched = {last} if total > n else set(block[len(block) - (n - total):]) if n - total <= len(block) else None
    if touched is None:
        raise FormError(f"표{table}에서 지울 수 있는 같은 모양의 행이 {len(block)}개뿐이에요.")
    for cell in grid:
        rows = set(range(cell.row, cell.row + cell.rowspan))
        if cell.rowspan > 1 and rows & touched:
            raise FormError(f"표{table}의 {cell.row + 1}행이 세로로 병합돼 있어 행 수를 바꿀 수 없어요.")
    if total > n:
        anchor = trs[last]
        for _ in range(total - n):
            new = copy.deepcopy(trs[last])
            for tc in new.findall(q("hp:tc")):
                _clear_cell(tc)
            anchor.addnext(new)
            anchor = new
    else:
        for i in sorted(touched):
            tbl.remove(trs[i])
    for r, tr in enumerate(tbl.findall(q("hp:tr"))):
        for tc in tr.findall(q("hp:tc")):
            tc.find(q("hp:cellAddr")).set("rowAddr", str(r))
    height = int(tbl.find(q("hp:sz")).get("height"))
    tbl.set("rowCnt", str(total))
    tbl.find(q("hp:sz")).set("height", str(height * total // n))


def replace_text(pkg: Package, old: str, new: str) -> int:
    """문서의 글자(hp:t)에서 old를 new로 바꾸고 바꾼 수를 돌려준다.

    숫자로 시작·끝나는 글자는 숫자 경계를 지킨다('2월'이 '12월'을 바꾸지 않음). 메모 내용은 바꾸지 않는다.
    """
    if not old:
        raise FormError("바꿀 글자가 비어 있어요.")
    pattern = re.compile(("(?<!\\d)" if old[0].isdigit() else "") + re.escape(old)
                         + ("(?!\\d)" if old[-1].isdigit() else ""))
    count = 0

    def sub(text):
        nonlocal count
        result, n = pattern.subn(lambda m: new, text)
        count += n
        return result

    for name in pkg.section_names():
        root = pkg.edit(name)
        for t in root.iter(q("hp:t")):
            if any(a.tag == q("hp:fieldBegin") for a in t.iterancestors()):
                continue
            if t.text:
                t.text = sub(t.text)
            for ch in t:
                if ch.tail:
                    ch.tail = sub(ch.tail)
    if count == 0:
        raise FormError(f"'{old}'를 문서에서 찾지 못했어요. 글자가 여러 서식으로 나뉘어 있으면 찾지 못할 수 있어요.")
    return count


def fill(pkg: Package, ops: list, *, base_dir: Path = Path(".")) -> list[str]:
    warnings: list[str] = []
    for op in ops:
        try:
            if isinstance(op, ReplaceOp):
                n = replace_text(pkg, op.old, op.new)
                warnings.append(f"{op.lineno}번째 줄: '{op.old}' → '{op.new}' {n}곳을 바꿨어요.")
            elif isinstance(op, RowsOp):
                set_rows(pkg, op.table, op.rows)
            else:
                cell = find_cell(pkg, op.table, op.row, op.col)
                warnings += [f"{op.lineno}번째 줄: {w}" for w in fill_cell(pkg, cell, op.content, base_dir=base_dir)]
        except ValueError as e:
            raise FormError(f"{op.lineno}번째 줄: {e}") from None
    return warnings


def _address_part(cell: Cell, kind: str) -> str:
    header = cell.row_header if kind == "row" else cell.col_header
    if header and "|" not in header and not header.startswith("@"):
        return header
    return f"#{(cell.row if kind == 'row' else cell.col) + 1}"


def list_fields(pkg: Package) -> list[dict]:
    """칸 목록과 칸마다 쓸 주소. 머리 글자 주소가 그 칸을 정확히 가리키지 않으면 '#번호' 주소로 바꾼다."""
    out = []
    for c in cells(pkg):
        address = f"@칸 표{c.table} | {_address_part(c, 'row')} | {_address_part(c, 'col')}"
        op = parse_fill(address + "\nx")[0]
        try:
            same = find_cell(pkg, op.table, op.row, op.col).tc is c.tc
        except FormError:
            same = False
        if not same:
            address = f"@칸 표{c.table} | #{c.row + 1} | #{c.col + 1}"
        out.append({"table": c.table, "row": c.row + 1, "col": c.col + 1, "label": c.label(), "text": c.text,
                    "filled": bool(c.text.strip()), "address": address})
    return out
