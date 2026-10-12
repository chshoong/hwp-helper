"""엑셀(.xlsx)·CSV를 보고서 마크다운 표로. 표준 라이브러리와 lxml만 쓴다 (설계 4장)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile
from decimal import ROUND_HALF_UP, Decimal
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
        pr = wb.find(f"{_M}workbookPr")
        shift = 1462 if pr is not None and pr.get("date1904") in ("1", "true") else 0  # 1904 체계 → 1900 체계
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
            grid[(r, col)] = Value("number", number=float(v.text) + (shift if code == "date" else 0), fmt=code)
        elif c.find(f"{_M}f") is not None:
            grid[(r, col)] = Value("text", "")  # 범위에는 넣고 빈 칸으로
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
            if _NUMBER_TEXT.match(cell) and not re.match(r"^[-+]?0\d", cell):
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


def _round(x: float, dec: int, group: bool) -> str:
    """엑셀처럼 반올림(0.5는 올림)하고 자리를 맞춘다."""
    q = Decimal(repr(x)).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
    return f"{q:,.{dec}f}" if group else f"{q:.{dec}f}"


_LITERAL = re.compile(r'"([^"]*)"|\\(.)')
_UNKNOWN = re.compile(r"@|\?/|[eE][+-]")


def _show(v: Value, col_dec: int, group: bool = True, unknown: set | None = None) -> str:
    if v.kind != "number":
        return v.text
    if v.fmt == "date":
        d = dt.date(1899, 12, 30) + dt.timedelta(days=int(v.number))
        return f"{d.year}. {d.month}. {d.day}."
    if v.fmt == "General":
        return _round(v.number, col_dec, group)
    section = v.fmt.split(";")[0]
    clean = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", section)  # 따옴표 글자·[색]·\x·_x 빼고
    if _UNKNOWN.search(clean) or not re.search(r"[0#?]", clean):
        if unknown is not None:
            unknown.add(v.fmt)
        return _round(v.number, _plain_decimals(v.number), group)
    lits = [(m.start(), m.group(1) if m.group(1) is not None else m.group(2)) for m in _LITERAL.finditer(section)]
    masked = _LITERAL.sub(lambda m: " " * len(m.group(0)), section)  # 따옴표 속 기호는 서식이 아님
    first = re.search(r"[0#?]", masked).start()
    last = max(m.end() for m in re.finditer(r"[0#?%,.]", masked))
    prefix = "".join(t for pos, t in lits if pos < first)
    suffix = "".join(t for pos, t in lits if pos >= last)
    x = v.number
    scale = re.search(r"[0#?](,+)(?![0#?])", clean)
    if scale:
        x /= 1000 ** len(scale.group(1))
    if "%" in clean:
        x *= 100
    body = _round(x, _decimals(clean), bool(re.search(r"[0#?],[0#?]", clean)))
    return f"{prefix}{body}{'%' if '%' in clean else ''}{suffix}"


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
    keys = list(grid)
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
    col_dec, aligns, groups, unknown = [], [], [], set()
    for c in range(nc):
        body = [cell(r, c) for r in range(header, nr) if (r, c) not in marks]
        nums = [v for v in body if v.kind == "number"]
        general = [v.number for v in nums if v.fmt == "General"]
        col_dec.append(max((_plain_decimals(x) for x in general), default=0))
        # 연도 열(1900~2100 정수만)은 쉼표를 넣지 않는다 (2,026 방지)
        groups.append(not (general and all(x == int(x) and 1900 <= x <= 2100 for x in general)))
        filled = [v for v in body if v.kind != "empty" and (v.kind == "number" or v.text)]
        numeric = bool(filled) and all((v.kind == "number" and v.fmt != "date") or
                                       (v.kind == "text" and _NUMERIC_LOOK.match(v.text)) for v in filled)
        aligns.append("---:" if numeric else "---")
    lines = [f"표: {caption}"] if caption else []
    for r in range(nr):
        out = []
        for c in range(nc):
            if (r, c) in marks:
                out.append(marks[(r, c)])
            else:
                v = cell(r, c)
                out.append(_cell_text(_raw(v) if r < header else _show(v, col_dec[c], groups[c], unknown)))
        lines.append("| " + " | ".join(out) + " |")
        if r == max(header, 1) - 1:  # 보고서 마크다운은 첫 행을 머리로 본다
            lines.append("|" + "|".join(aligns) + "|")
    for code in sorted(unknown):
        warnings.append(f"엑셀 서식 '{code}'은(는) 그대로 보여 주지 못해 일반 숫자로 넣었어요. 표를 확인해 주세요.")
    if nc > MAX_COLS:
        warnings.append(f"열이 {nc}개라 한글 쪽 폭에 다 들어가지 않을 수 있어요. 필요한 열만 범위로 골라 보세요.")
    return "\n".join(lines) + "\n", warnings
