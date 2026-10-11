"""매달 이어받기: 지난달 월간보고서 → 이번 달 fill 지시문 초안과 확인할 것 (설계 3장).

문서는 바꾸지 않는다. 숫자(누적·진행률)·새 계획·보고일은 지어내지 않고 확인할 것으로 알린다.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re

from .form import cells, list_fields
from .ns import q
from .package import Package
from .review import _CURRENT, _NEXT, _REPORT_DATE_WORDS, _add_month, _period, _texts, _year

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
    moves, move_ask = _plan_moves(pkg)
    lines += [""] + moves if moves else []
    ask = _report_dates(texts) + move_ask + _numbers(pkg)
    spec = "\n".join(lines) + "\n" if lines else ""
    return {"from": frm, "to": to, "spec": spec, "ask": ask, "warnings": warnings}
